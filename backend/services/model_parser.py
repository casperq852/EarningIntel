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

import anthropic

MODEL = "claude-sonnet-4-20250514"

_SYSTEM = """You are a financial data extraction specialist. You receive the raw cell content
of a Bloomberg aggregate analyst model Excel export and must extract quarterly financial data.

Return ONLY valid JSON — no preamble, no markdown fences, no explanation.

Critical rules:
- fiscal_period format MUST be "Q1-2026", "Q2-2025" etc. Derive from column headers.
  Bloomberg often shows calendar quarters; map to fiscal quarters if the company has
  a non-calendar fiscal year (use context clues or default to calendar).
- All monetary values in MILLIONS. Convert: billions → ×1000, thousands → ÷1000.
- is_estimate: true = forward consensus estimate, false = historical reported actual.
  Actuals are marked "A", "Act", "Actual", or are in past columns. Estimates are marked
  "E", "Est", "Consensus", or are in future columns.
- Use null for fields not found — never invent numbers.
- revenue, ebit, ebitda, net_income are the consensus MEAN (or reported actual for history).
  If only median is available, use it.
- analyst_count: number of contributing analysts if shown, else null.
- segment_breakdown: extract if a segment/divisional table is present.
  Format: {"SegmentName": {"revenue": 1200.0, "margin_pct": 18.5}} — null if not present.
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
    client: anthropic.AsyncAnthropic,
    content_bytes: bytes,
    filename: str,
) -> Dict[str, Any]:
    """
    Parse a Bloomberg aggregate analyst model Excel file.
    Returns dict with 'company_name', 'currency', and 'quarters' list.
    Each quarter has is_estimate flag, financials, and optional segment_breakdown.
    """
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

    response = await client.messages.create(
        model=MODEL,
        max_tokens=6000,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = "".join(b.text for b in response.content if hasattr(b, "text"))
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.I)
    raw = re.sub(r"\s*```$", "", raw.strip())
    return json.loads(raw)
