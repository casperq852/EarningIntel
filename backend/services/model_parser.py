"""
Bloomberg analyst model parser.

Reads an uploaded .xlsx file, converts to text, then asks Claude to extract:
  - Historical actuals (past quarters that have already reported)
  - Forward consensus estimates (future quarters)
  - Segment/divisional breakdown if present

Returns structured JSON ready to persist into the earnings table.
"""
from __future__ import annotations

import io
import json
import re
from typing import Any, Dict, List, Optional

MODEL = "claude-sonnet-4-20250514"

_SYSTEM = """You are a financial data extraction specialist. You receive the raw cell content
of a Bloomberg aggregate analyst model Excel export and must extract quarterly financial data.

Return ONLY valid JSON — no preamble, no markdown fences, no explanation.

Critical rules:

PERIOD IDENTIFICATION:
- fiscal_period format MUST be "Q1-2026", "Q2-2025" etc.
- Bloomberg "Multiple Periods" format uses headers like "2024 Q2 (Rep)" or "2026 Q2 (Fwd)".
  Convert "2024 Q2" → "Q2-2024", "2025 Q3" → "Q3-2025", etc.
- "(Rep)" or "(Reported)" = historical reported actual → is_estimate: false
- "(Fwd)" or "(Forward)" or "(Est)" = forward consensus estimate → is_estimate: true
- Also recognize: "A" / "Act" / "Actual" = actual; "E" / "Est" / "Consensus" = estimate
- The header row with period labels is usually row 3; the date row below it confirms calendar end.

FIELD MAPPING (Bloomberg field codes → output fields):
- Revenue: IS_COMP_SALES, SALES_REV_TURN (consolidated), IS902 → revenue
- EPS: IS_COMP_EPS_ADJUSTED_OLD, IS_EPS → eps
- EBIT / Adj Operating Income: IS_COMPARABLE_EBIT, IS_ADJ_EBIT_OP_INC_AS_REPORTED, IM132 → ebit
- EBITDA / Adj EBITDA: IS_COMPARABLE_EBITDA, IS_ADJUSTED_EBITDA_AS_REPORTED, IM131 → ebitda
- Net Income: IS_COMP_NET_INCOME_GAAP, IS904 → net_income
- Use the TOP-LEVEL consolidated rows (no Segment Id), not the per-segment rows for these totals.

MONETARY VALUES:
- All values in MILLIONS. File header usually states "In Millions of EUR/USD/GBP".
- If header says "In Billions" → multiply by 1000.

SEGMENT BREAKDOWN:
- Look for rows with a "Segment Id" column (e.g. "SEG1092246393 Segment").
- For top-level segments only (1 indent level), extract revenue and EBITDA/EBIT margin if present.
- Format: {"SegmentName": {"revenue": 1200.0, "margin_pct": 18.5}}

OTHER:
- Use null for fields not found — never invent numbers.
- analyst_count: number of contributing analysts if shown, else null.
- Include ALL periods found, both historical and forward."""

_SCHEMA = """{
  "company_name": "string or null",
  "currency": "EUR",
  "quarters": [
    {
      "fiscal_period": "Q2-2025",
      "is_estimate": false,
      "revenue": 19800.0,
      "ebit": 3050.0,
      "ebitda": 4200.0,
      "net_income": 2100.0,
      "eps": 2.65,
      "ebit_margin_pct": 15.4,
      "ebitda_margin_pct": 21.2,
      "analyst_count": null,
      "segment_breakdown": {
        "Digital Industries": {"revenue": 6200.0, "margin_pct": 20.1},
        "Smart Infrastructure": {"revenue": 5900.0, "margin_pct": 14.8}
      },
      "extra": {}
    },
    {
      "fiscal_period": "Q3-2025",
      "is_estimate": true,
      "revenue": 20500.0,
      "ebit": 3200.0,
      "ebitda": 4400.0,
      "net_income": 2200.0,
      "eps": 2.78,
      "ebit_margin_pct": 15.6,
      "ebitda_margin_pct": 21.5,
      "analyst_count": 24,
      "segment_breakdown": null,
      "extra": {"capex_est": 800.0, "fcf_est": 2100.0}
    }
  ]
}"""


def _excel_to_text(content_bytes: bytes, max_chars: int = 45_000) -> str:
    """Convert all sheets in an Excel file to tab-separated text."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content_bytes), data_only=True)

    parts = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = []
        for row in ws.iter_rows(values_only=True):
            cells = []
            for c in row:
                if c is None:
                    cells.append("")
                elif isinstance(c, float):
                    # Avoid scientific notation for small numbers
                    cells.append(f"{c:g}")
                else:
                    cells.append(str(c))
            if any(c.strip() for c in cells):
                rows.append("\t".join(cells))
        if rows:
            parts.append(f"=== SHEET: {sheet_name} ===\n" + "\n".join(rows))

    text = "\n\n".join(parts)
    return text[:max_chars]


async def parse_bloomberg_model(
    content_bytes: bytes,
    filename: str,
    *,
    model: str = MODEL,
    provider: str = "anthropic",
    openrouter_api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Parse a Bloomberg aggregate analyst model Excel file.
    Returns dict with 'company_name', 'currency', and 'quarters' list.
    Each quarter has is_estimate flag, financials, and optional segment_breakdown.
    """
    from services.llm import call_llm

    excel_text = _excel_to_text(content_bytes)

    prompt = f"""Parse this Bloomberg analyst model export and extract all quarterly data.
Filename: {filename}

Instructions:
- Extract BOTH historical actuals (is_estimate: false) AND forward consensus estimates (is_estimate: true)
- Look carefully for segment/divisional breakdowns — Bloomberg models often have a separate sheet or section
- If the file has multiple sheets, check all of them for financial data
- Revenue and P&L lines are usually rows; quarters are usually columns
- Look for period labels like "Q1 25A", "2Q25E", "FY2025E", "H1 2026" etc.

File content:
{excel_text}

Return JSON matching exactly this schema (include ALL quarters found):
{_SCHEMA}"""

    return await call_llm(
        _SYSTEM,
        prompt,
        provider=provider,
        model=model,
        openrouter_api_key=openrouter_api_key,
        max_tokens=6000,
    )
