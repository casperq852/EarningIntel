"""
Bloomberg analyst model parser.

Reads an uploaded .xlsx file, extracts a text representation of the sheets,
then asks Claude to identify quarterly consensus estimates (revenue, EPS, EBIT,
net income, margins). Returns structured JSON ready to upsert into earnings.
"""
from __future__ import annotations

import io
import json
import re
from typing import Any, Dict, List, Optional

import anthropic

MODEL = "claude-sonnet-4-20250514"

_SYSTEM = """You are a financial data parser specialising in Bloomberg analyst model exports.
You will be given the raw cell content of an Excel file and must extract quarterly consensus estimates.

Return ONLY valid JSON — no preamble, no markdown fences.

Rules:
- fiscal_period format: "Q1-2026", "Q2-2025" etc. Infer from column headers.
- All monetary values in MILLIONS (convert billions → multiply by 1000, thousands → divide by 1000).
- Use null for any field not found.
- is_estimate: true if the period is a forward consensus estimate, false if it is a historical actual.
- Include both historical and forward periods if present.
- revenue_est, ebit_est, net_income_est, eps_est are the consensus MEAN values.
- If you see multiple estimate types (mean, median, high, low) — use mean. If only median present, use that.
- analyst_count: number of contributors if shown, else null.
- extra: any other relevant per-period metrics found (e.g. EBITDA, gross margin %) as key/value pairs."""

_SCHEMA = """{
  "company_name": "string or null — as shown in the file",
  "currency": "EUR | USD | GBP | etc.",
  "quarters": [
    {
      "fiscal_period": "Q2-2026",
      "is_estimate": true,
      "revenue_est": 5200.0,
      "ebit_est": 850.0,
      "net_income_est": 620.0,
      "eps_est": 1.42,
      "ebit_margin_est": 16.3,
      "analyst_count": 28,
      "extra": {"ebitda_est": 1100.0, "gross_margin_est": 42.1}
    }
  ]
}"""


def _excel_to_text(content_bytes: bytes, max_chars: int = 40_000) -> str:
    """Convert Excel file to a compact text representation for Claude."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content_bytes), data_only=True)

    parts = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = []
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) if c is not None else "" for c in row]
            # Skip rows that are entirely empty
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
    """
    excel_text = _excel_to_text(content_bytes)

    prompt = f"""Parse this Bloomberg analyst model export (filename: {filename}).
Extract all quarterly consensus estimates you can find.

File content:
{excel_text}

Return JSON matching exactly this schema:
{_SCHEMA}"""

    response = await client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = "".join(b.text for b in response.content if hasattr(b, "text"))
    # Strip markdown fences if Claude adds them despite instructions
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.I)
    raw = re.sub(r"\s*```$", "", raw.strip())
    return json.loads(raw)
