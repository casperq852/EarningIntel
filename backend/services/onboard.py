"""
Company onboarding agent — Claude orchestrates web research via tool use.

Claude is given two tools (search_web, fetch_page) and asked to:
  1. Find the IR website
  2. Get the earnings calendar
  3. Extract the last 2-3 quarters of results + segment data
  4. Identify sector-specific KPIs
  5. Give a qualitative assessment of the latest results

Returns structured JSON consumed by the onboard router.
"""
from __future__ import annotations

import json
import re
from typing import Any, AsyncGenerator, Dict, List, Optional

import anthropic

from services.scraper import _brave_search, _fetch_document, _is_skipped

MODEL = "claude-sonnet-4-20250514"
MAX_TOOL_ROUNDS = 16

# ---------------------------------------------------------------------------
# Tool definitions given to Claude
# ---------------------------------------------------------------------------

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "search_web",
        "description": (
            "Search the web. Use specific queries to find official investor relations pages, "
            "earnings press releases, and financial presentations. "
            "Avoid using vague queries — be specific about company, period, and document type."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_page",
        "description": (
            "Fetch and extract text from a URL (HTML page or PDF). "
            "Use this to read official IR pages, press releases, annual reports, and presentations. "
            "Returns up to 12,000 characters of extracted text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full URL to fetch"},
            },
            "required": ["url"],
        },
    },
]

_SYSTEM = """You are a senior equity research analyst onboarding a new company for coverage. \
You have two tools: search_web and fetch_page. Use them to research the company thoroughly.

Research methodology:
1. Search for the company's official investor relations website
2. Fetch the IR landing page to find links to recent earnings press releases and PDF reports
3. CRITICAL: Always try to fetch the actual PDF press release — PDFs contain the full financial tables \
with segment revenue, margins, and YoY comparisons that HTML pages often lack. \
Look for .pdf links in IR pages or search specifically for "{company} Q{n} {year} earnings press release PDF".
4. If an HTML press release lacks segment data, search explicitly for the PDF: \
"{company} annual report OR earnings report filetype:pdf site:{ir_domain}"
5. Extract divisional/segment breakdowns which are critical for industrial, pharma, and tech companies

Document fetching priority:
- PDF press releases > HTML press releases > investor presentations > IR summary pages
- For European companies (XETRA, Euronext, LSE), check the IR page for "Results" or "Financial Reports" PDF section
- Segment data is almost always in a PDF — do not give up after a single HTML fetch

Always prefer official company IR pages over news aggregators, analyst sites, or financial databases.

IMPORTANT — return JSON as soon as you have:
- The IR URL
- At least ONE quarter of financial data
- A company overview and KPI list

Do NOT keep searching trying to perfect every field. Null values are fine for missing fields.
Never fetch aggregator sites (coincodex, macrotrends, wisesheets, stockanalysis, etc) — they waste rounds.
After fetching any PDF press release, return the JSON immediately if you have data for 1+ quarters."""

_OUTPUT_SCHEMA = """{
  "ir_url": "string — official IR URL, e.g. https://www.infineon.com/cms/en/about-infineon/investor/",
  "next_earnings_date": "YYYY-MM-DD or null",
  "custom_kpis": ["snake_case_kpi", ...],
  "recent_quarters": [
    {
      "fiscal_period": "Q2-2026",
      "revenue": 4580.0,
      "ebit": 820.0,
      "ebit_margin_pct": 17.9,
      "net_income": 580.0,
      "eps": 0.58,
      "free_cash_flow": 420.0,
      "operating_cash_flow": 510.0,
      "capex": 90.0,
      "net_debt": 1200.0,
      "order_intake": 5100.0,
      "book_to_bill": 1.11,
      "yoy_revenue_growth_pct": 8.5,
      "beat_miss": "beat | miss | in_line | null",
      "guidance_tone": "raised | maintained | lowered | withdrawn | null",
      "mgmt_tone": "positive | neutral | cautious | negative",
      "guidance_detail": "text describing what guidance was given, or null",
      "segment_breakdown": {
        "SegmentName": {"revenue": 1200, "margin_pct": 18.5, "yoy_growth_pct": 5.0}
      },
      "key_highlights": ["bullet 1", "bullet 2", "bullet 3"],
      "red_flags": ["risk or concern 1"]
    }
  ],
  "company_overview": "2–3 sentence plain-language description of what this company does",
  "kpi_rationale": "Why these specific KPIs matter for analysts covering this company",
  "latest_earnings_summary": "3–4 sentence qualitative assessment of the most recent results — management tone, strategic themes, key risks"
}"""


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

async def _exec_search(query: str) -> str:
    try:
        urls = await _brave_search(query, count=6)
        if not urls:
            return "No results found for this query."
        return "Search results:\n" + "\n".join(f"- {u}" for u in urls)
    except Exception as e:
        return f"Search error: {e}"


async def _exec_fetch(url: str) -> str:
    if _is_skipped(url):
        return "Blocked: this domain is an aggregator or news site. Fetch a different URL."
    try:
        _, text, mime_type = await _fetch_document(url, timeout=30.0)
        # For HTML pages: surface any .pdf links so the agent can follow them
        if "html" in mime_type:
            pdf_links = re.findall(r'https?://[^\s"\'<>]+\.pdf[^\s"\'<>]*', text, re.I)
            unique_pdfs = list(dict.fromkeys(pdf_links))[:8]
            suffix = ""
            if unique_pdfs:
                suffix = "\n\nPDF links found on this page (fetch these for full financial tables):\n" + "\n".join(f"- {u}" for u in unique_pdfs)
            return f"[{mime_type}] {url}\n\n{text[:11_000]}{suffix}"
        snippet = text[:12_000]
        return f"[{mime_type}] {url}\n\n{snippet}"
    except Exception as e:
        return f"Fetch error: {e}"


# ---------------------------------------------------------------------------
# Agent loop — yields SSE-compatible event dicts
# ---------------------------------------------------------------------------

async def run_onboard_agent(
    client: anthropic.AsyncAnthropic,
    company_name: str,
    ticker: str,
    exchange: str,
    sector: str,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Async generator that yields event dicts:
      {"type": "progress", "message": str}
      {"type": "tool_call", "tool": str, "input": str}
      {"type": "tool_result", "tool": str, "preview": str}
      {"type": "done", "data": dict}
      {"type": "error", "message": str}
    """
    prompt = f"""Research {company_name} ({ticker}{', ' + exchange if exchange else ''}) for equity coverage.
Sector: {sector or 'not specified'}

Tasks — complete ALL of them before returning JSON:

1. EARNINGS CALENDAR (max 3 tool calls — find the IR financial calendar page)
   Search for or fetch the IR calendar/financial-calendar page and extract:
   - The most recent past earnings release date
   - The next scheduled earnings release date
   Strategy: first try fetching the IR landing page (you'll fetch it anyway for task 2).
   If the calendar dates are visible there, use them. If not, do ONE search for
   "{{company}} earnings calendar investor relations" and fetch the result.
   Stop after 3 attempts total. If still not found, set next_earnings_date to null and move on.

2. IR WEBSITE
   Find the official investor relations URL.
   This must be a direct link to the company's own IR section, not an aggregator.

3. RECENT FINANCIALS (fetch the PDF press release — HTML pages rarely have full tables)
   For each of the last 2–3 quarters, extract from the actual press release PDF:
   - Revenue (reported currency, millions or billions — convert to millions in JSON)
   - EBIT / Operating Profit and margin %
   - Net income and EPS (basic or diluted)
   - Free cash flow and operating cash flow if disclosed
   - Net debt / net cash position
   - YoY revenue growth % (comparable basis if stated)
   - Segment / divisional breakdown: each segment's revenue, profit margin %, YoY growth %
     (This is usually in a table in the PDF — look for "Segment results", "Divisional performance",
      "Business unit overview", or similar. This is critical for industrial, tech, and pharma companies.)
   - Order intake / bookings and book-to-bill ratio if reported
   - 3–5 key highlights as bullet points
   - Any red flags or risks mentioned
   - Guidance detail text (what management said about the outlook)

4. COMPANY-SPECIFIC KPIs
   For a {sector or 'diversified'} company, what 3–5 operational metrics do specialist analysts track
   beyond standard P&L lines? Examples:
   - Semiconductors: book-to-bill, order backlog, capacity utilisation
   - Industrials: order intake, order backlog, equipment utilisation
   - Pharma: pipeline stage counts, market share by drug, R&D spend ratio
   - Banks: NIM, CET1 ratio, cost-to-income ratio, NPL ratio
   - Consumer: like-for-like sales growth, store count, e-commerce mix
   Name them in snake_case (e.g. book_to_bill, order_backlog_bn).

5. LATEST QUALITATIVE ASSESSMENT
   Based on the most recent earnings release or call transcript:
   - Management tone (positive/neutral/cautious/negative)
   - 2–3 key strategic themes mentioned
   - Main risks or concerns raised

Return ONLY valid JSON matching this exact schema — no other text:
{_OUTPUT_SCHEMA}"""

    messages: List[Dict[str, Any]] = [{"role": "user", "content": prompt}]

    yield {"type": "progress", "message": f"Starting research on {company_name} ({ticker})…"}

    for round_num in range(MAX_TOOL_ROUNDS):
        try:
            response = await client.messages.create(
                model=MODEL,
                max_tokens=6000,
                system=_SYSTEM,
                tools=TOOLS,
                messages=messages,
            )
        except Exception as e:
            yield {"type": "error", "message": f"Claude API error: {e}"}
            return

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            raw_text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            try:
                json_match = re.search(r'\{[\s\S]*\}', raw_text)
                if not json_match:
                    raise ValueError("No JSON object found in response")
                data = json.loads(json_match.group())
                yield {"type": "done", "data": data}
            except Exception as e:
                yield {"type": "error", "message": f"JSON parse error: {e}\nRaw: {raw_text[:500]}"}
            return

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                tool_name = block.name
                tool_input = block.input

                if tool_name == "search_web":
                    query = tool_input.get("query", "")
                    yield {"type": "tool_call", "tool": "search_web", "input": query}
                    result = await _exec_search(query)
                    yield {"type": "tool_result", "tool": "search_web", "preview": result[:200].replace("\n", " ")}

                elif tool_name == "fetch_page":
                    url = tool_input.get("url", "")
                    yield {"type": "tool_call", "tool": "fetch_page", "input": url}
                    result = await _exec_fetch(url)
                    yield {"type": "tool_result", "tool": "fetch_page", "preview": result[:200].replace("\n", " ")}

                else:
                    result = f"Unknown tool: {tool_name}"

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

            if tool_results:
                messages.append({"role": "user", "content": tool_results})
        else:
            yield {"type": "error", "message": f"Unexpected stop_reason: {response.stop_reason}"}
            return

    yield {"type": "error", "message": f"Agent did not complete within {MAX_TOOL_ROUNDS} tool rounds."}
