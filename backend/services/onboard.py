"""
Company onboarding agent — qualitative research only.

Quantitative numbers (revenue, EPS, EBIT, margins) come from the Bloomberg
analyst model upload. This agent handles everything that Bloomberg can't:

  1. Find the official IR website
  2. Find the next earnings date
  3. Identify sector-specific KPIs to track
  4. Extract qualitative assessment of the latest 1-2 earnings releases
     (management tone, strategic themes, guidance narrative, red flags)
  5. Write a company overview

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
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "search_web",
        "description": (
            "Search the web. Use specific queries to find official investor relations pages "
            "and earnings press releases. Be specific about company, period, and document type."
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
            "Use this to read official IR pages, press releases, and presentations. "
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

_SYSTEM = """You are a senior equity research analyst onboarding a new company for coverage.
You have two tools: search_web and fetch_page.

Your goal is QUALITATIVE research only. You do NOT need to extract revenue, EPS, EBIT,
or other financial numbers — those come from a separate Bloomberg data upload.

Focus on:
- Finding the IR website and next earnings date
- Understanding what this company does and what drives its business
- Identifying which KPIs specialist analysts track for this sector
- Reading the most recent 1-2 earnings releases for management tone,
  strategic narrative, guidance language, and risks

Research methodology:
1. Search for and fetch the IR landing page (gives you the IR URL and often the calendar)
2. Find and fetch the most recent earnings press release or results announcement
   (HTML summary is fine — you do NOT need the full PDF financial tables)
3. If available, also read the prior quarter's release for trend context
4. Return JSON as soon as you have the IR URL, company overview, KPIs, and
   qualitative data for at least one recent quarter

Never fetch aggregator sites (coincodex, macrotrends, wisesheets, stockanalysis, etc).
Never spend more than 2 rounds trying to find a single document — move on."""

_OUTPUT_SCHEMA = """{
  "ir_url": "https://ir.company.com/",
  "next_earnings_date": "YYYY-MM-DD or null",
  "custom_kpis": ["snake_case_kpi_1", "snake_case_kpi_2"],
  "recent_quarters": [
    {
      "fiscal_period": "Q2-2026",
      "beat_miss": "beat | miss | in_line | null",
      "guidance_tone": "raised | maintained | lowered | withdrawn | null",
      "mgmt_tone": "positive | neutral | cautious | negative",
      "guidance_detail": "Concise description of what management guided for, or null",
      "key_highlights": [
        "Bullet point 1 — qualitative theme, strategic win, or operational milestone",
        "Bullet point 2",
        "Bullet point 3"
      ],
      "red_flags": [
        "Risk or concern raised by management or visible in the release"
      ]
    }
  ],
  "company_overview": "2-3 sentence plain-language description of what this company does, its end markets, and competitive position",
  "kpi_rationale": "Why these specific KPIs matter for analysts covering this sector/company",
  "latest_earnings_summary": "3-4 sentence qualitative assessment of the most recent results: management tone, key strategic themes, main risks, and what to watch next quarter"
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
        if "html" in mime_type:
            pdf_links = re.findall(r'https?://[^\s"\'<>]+\.pdf[^\s"\'<>]*', text, re.I)
            unique_pdfs = list(dict.fromkeys(pdf_links))[:6]
            suffix = ""
            if unique_pdfs:
                suffix = "\n\nPDF links found (fetch if you need the full release text):\n" + "\n".join(f"- {u}" for u in unique_pdfs)
            return f"[{mime_type}] {url}\n\n{text[:11_000]}{suffix}"
        return f"[{mime_type}] {url}\n\n{text[:12_000]}"
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
    Async generator — yields:
      {"type": "progress", "message": str}
      {"type": "tool_call", "tool": str, "input": str}
      {"type": "tool_result", "tool": str, "preview": str}
      {"type": "done", "data": dict}
      {"type": "error", "message": str}
    """
    prompt = f"""Research {company_name} ({ticker}{', ' + exchange if exchange else ''}) for equity coverage initiation.
Sector: {sector or 'not specified'}

Complete ALL tasks below, then return JSON:

1. IR WEBSITE & EARNINGS CALENDAR (1-3 tool calls)
   - Find the official investor relations URL
   - From the IR landing page or calendar page, find the next scheduled earnings date
   - If not visible after 2 attempts, set next_earnings_date to null

2. COMPANY OVERVIEW
   Write 2-3 sentences: what the company does, key end markets, competitive position.
   You can derive this from the IR landing page alone — no need for extra fetches.

3. SECTOR KPIs
   For a {sector or 'diversified'} company, name 3-5 operational KPIs that specialist
   analysts track beyond standard P&L lines. Use snake_case names. Examples:
   - Semiconductors: book_to_bill, order_backlog_bn, capacity_utilisation_pct
   - Industrials: order_intake_bn, order_backlog_bn, organic_growth_pct
   - Pharma: pipeline_assets, r_and_d_ratio_pct, key_drug_market_share_pct
   - Banks: net_interest_margin_pct, cet1_ratio_pct, cost_to_income_pct
   - Consumer: lfl_growth_pct, store_count, ecommerce_mix_pct

4. QUALITATIVE EARNINGS ASSESSMENT (fetch 1-2 recent press releases)
   For the most recent 1-2 quarters, read the earnings release and extract:
   - Whether results beat, missed, or were in line with expectations (qualitative judgement)
   - Guidance tone: did management raise, maintain, lower, or withdraw guidance?
   - Management tone: positive / neutral / cautious / negative
   - 3-5 key highlights as concise bullet points (themes, wins, strategic milestones)
   - Any red flags or risks mentioned
   - What management said about the outlook (guidance_detail)

   IMPORTANT: Do NOT extract revenue, EPS, EBIT, or financial figures.
   Those will be populated separately from a Bloomberg data upload.
   Focus purely on narrative, tone, and qualitative signals.

5. LATEST EARNINGS SUMMARY
   Write a 3-4 sentence qualitative assessment of the most recent quarter:
   management tone, key strategic themes, main risks, what to watch next quarter.

Return ONLY valid JSON matching this exact schema — no other text:
{_OUTPUT_SCHEMA}"""

    messages: List[Dict[str, Any]] = [{"role": "user", "content": prompt}]

    yield {"type": "progress", "message": f"Starting research on {company_name} ({ticker})…"}

    for round_num in range(MAX_TOOL_ROUNDS):
        try:
            response = await client.messages.create(
                model=MODEL,
                max_tokens=4000,
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
