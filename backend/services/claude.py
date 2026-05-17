"""
Claude synthesis service using the official Anthropic Python SDK.
Model: claude-sonnet-4-20250514
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional

import anthropic
from dotenv import load_dotenv

load_dotenv()

_ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

SYSTEM_PROMPT = """You are a senior equity analyst assistant specialising in European equities. You receive raw earnings data and earnings call transcript excerpts for a company. Your job is to synthesise these into a structured, concise brief for a portfolio management team.

Rules:
- Always respond in valid JSON exactly matching the schema provided. No preamble, no markdown.
- Be precise with numbers. Round to 2 decimal places.
- Assess management tone from the transcript language, not just the numbers.
- Flag anything that contradicts prior guidance or prior quarter trends as a red flag.
- key_highlights should be 3-5 concise bullet points a PM would care about most.
- post_brief should be 2-4 sentences of flowing prose summarising the quarter.
- If a custom KPI is not mentioned in the transcript or financials, return null for that field."""

_POST_BRIEF_SCHEMA = {
    "beat_miss": "string: 'beat' | 'miss' | 'in_line'",
    "revenue_actual": "number",
    "revenue_est": "number",
    "revenue_surprise_pct": "number",
    "eps_actual": "number",
    "eps_est": "number",
    "eps_surprise_pct": "number",
    "mgmt_tone": "string: 'positive' | 'neutral' | 'cautious' | 'negative'",
    "guidance_tone": "string: 'raised' | 'maintained' | 'lowered' | 'withdrawn' | null",
    "key_highlights": ["string (3-5 bullet points)"],
    "red_flags": ["string (0 or more)"],
    "post_brief": "string (2-4 sentences of flowing prose)",
    "custom_kpis": {},
}

_PRE_BRIEF_SCHEMA = {
    "consensus_summary": "string: 1-2 sentence summary of consensus expectations",
    "key_watch_items": ["string (3-5 items a PM should watch)"],
    "prior_quarter_context": "string: brief context from last quarter",
    "guidance_context": "string: what management guided for this period",
    "bull_case": "string: 1 sentence bull case for the report",
    "bear_case": "string: 1 sentence bear case for the report",
    "revenue_est": "number",
    "eps_est": "number",
    "custom_kpis_est": {},
}


class ClaudeService:
    """Async Claude synthesis service with retry logic."""

    MAX_RETRIES = 3

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or _ANTHROPIC_API_KEY
        self._client = anthropic.AsyncAnthropic(api_key=self._api_key)

    async def _call_with_retry(self, prompt: str, max_tokens: int = 4096) -> Dict[str, Any]:
        """Call Claude with exponential backoff retry. Returns parsed JSON dict."""
        last_error: Optional[Exception] = None
        for attempt in range(self.MAX_RETRIES):
            try:
                message = await self._client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=max_tokens,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw_text = message.content[0].text.strip()
                # Strip markdown code fences if present
                if raw_text.startswith("```"):
                    lines = raw_text.split("\n")
                    raw_text = "\n".join(lines[1:-1]) if len(lines) > 2 else raw_text
                return json.loads(raw_text)
            except (anthropic.RateLimitError, anthropic.APIStatusError) as e:
                last_error = e
                wait = 2 ** attempt
                await asyncio.sleep(wait)
            except json.JSONDecodeError as e:
                last_error = e
                await asyncio.sleep(2 ** attempt)
            except Exception as e:
                last_error = e
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError(
            f"Claude API call failed after {self.MAX_RETRIES} attempts: {last_error}"
        )

    async def generate_post_brief(
        self,
        company: str,
        fiscal_period: str,
        revenue_actual: Optional[float],
        revenue_est: Optional[float],
        revenue_surprise_pct: Optional[float],
        eps_actual: Optional[float],
        eps_est: Optional[float],
        eps_surprise_pct: Optional[float],
        prior_quarters: List[Dict[str, Any]],
        transcript_chunks: Optional[str],
        custom_kpi_list: List[str],
    ) -> Dict[str, Any]:
        """
        Generate a post-earnings brief by synthesising actual results and transcript.
        """
        prior_quarters_text = json.dumps(prior_quarters, indent=2) if prior_quarters else "No prior quarter data available."
        transcript_text = transcript_chunks or "No transcript available for this period."
        kpis_text = ", ".join(custom_kpi_list) if custom_kpi_list else "None specified."

        custom_kpi_schema = {kpi: "number or null" for kpi in custom_kpi_list}
        schema = dict(_POST_BRIEF_SCHEMA)
        schema["custom_kpis"] = custom_kpi_schema

        prompt = f"""You are analysing the earnings results for {company} for fiscal period {fiscal_period}.

## Reported Financials
- Revenue Actual: {revenue_actual}
- Revenue Estimate: {revenue_est}
- Revenue Surprise %: {revenue_surprise_pct}
- EPS Actual: {eps_actual}
- EPS Estimate: {eps_est}
- EPS Surprise %: {eps_surprise_pct}

## Custom KPIs to Extract
{kpis_text}

## Prior Quarters (for trend analysis)
{prior_quarters_text}

## Earnings Call Transcript Excerpt
{transcript_text[:6000] if transcript_text else "Not available."}

## Required JSON Schema
{json.dumps(schema, indent=2)}

Respond with valid JSON only, no markdown, no preamble. Populate the custom_kpis object with the values extracted from the transcript or financials. Return null for any custom KPI not mentioned."""

        return await self._call_with_retry(prompt, max_tokens=4096)

    async def generate_pre_brief(
        self,
        company: str,
        report_date: Optional[str],
        fiscal_period: str,
        revenue_est: Optional[float],
        eps_est: Optional[float],
        prior_quarter: Optional[Dict[str, Any]],
        prior_guidance: Optional[str],
        custom_kpi_list: List[str],
    ) -> Dict[str, Any]:
        """
        Generate a pre-earnings brief with consensus expectations and key watch items.
        """
        prior_q_text = json.dumps(prior_quarter, indent=2) if prior_quarter else "No prior quarter data available."
        guidance_text = prior_guidance or "No explicit guidance on record."
        kpis_text = ", ".join(custom_kpi_list) if custom_kpi_list else "None specified."

        custom_kpi_schema = {kpi: "estimated number or null" for kpi in custom_kpi_list}
        schema = dict(_PRE_BRIEF_SCHEMA)
        schema["custom_kpis_est"] = custom_kpi_schema

        prompt = f"""You are preparing a pre-earnings brief for {company} ahead of their {fiscal_period} results, expected on {report_date or "date TBD"}.

## Consensus Estimates
- Revenue Estimate: {revenue_est}
- EPS Estimate: {eps_est}

## Custom KPIs to Monitor
{kpis_text}

## Prior Quarter Results (for context)
{prior_q_text}

## Prior Management Guidance
{guidance_text}

## Required JSON Schema
{json.dumps(schema, indent=2)}

Respond with valid JSON only, no markdown, no preamble. In custom_kpis_est, provide consensus or derived estimates where possible, null otherwise."""

        return await self._call_with_retry(prompt)

    async def extract_from_ir_page(
        self,
        company: str,
        fiscal_period: str,
        page_text: str,
        custom_kpi_list: List[str],
    ) -> Dict[str, Any]:
        """
        Extract structured earnings data from raw IR page / document text.
        Used as a fallback when FMP data is unavailable (typically European companies).
        """
        custom_kpi_schema = {kpi: "number or null" for kpi in custom_kpi_list}
        schema = dict(_POST_BRIEF_SCHEMA)
        schema["custom_kpis"] = custom_kpi_schema
        schema["revenue_actual"] = "number (in original reported currency and units, e.g. millions)"
        schema["gross_profit"] = "number or null"
        schema["ebit"] = "number or null"
        schema["ebit_margin_pct"] = "number or null"
        schema["net_income"] = "number or null"
        schema["eps_actual"] = "number"
        schema["revenue_est"] = "number or null (analyst consensus if mentioned)"
        schema["eps_est"] = "number or null (analyst consensus if mentioned)"
        schema["fiscal_period"] = "string e.g. Q1-2026 (derive from the document)"
        schema["segment_breakdown"] = {
            "__description": "Revenue and margin per business segment if reported",
            "__example": {"Automotive": {"revenue": 1830, "margin_pct": 18.1, "yoy_growth_pct": 5.2}, "Industrial": {"revenue": 900, "margin_pct": 12.0, "yoy_growth_pct": -3.1}}
        }
        schema["guidance_detail"] = "string: specific next-quarter and/or full-year guidance numbers and commentary (not just 'raised')"
        schema["yoy_revenue_growth_pct"] = "number or null"
        schema["qoq_revenue_growth_pct"] = "number or null"
        schema["operating_cash_flow"] = "number or null (from cash flow statement)"
        schema["free_cash_flow"] = "number or null (operating cash flow minus capex)"
        schema["capex"] = "number or null"
        schema["net_debt"] = "number or null (total debt minus cash)"
        schema["dividend_per_share"] = "number or null (if declared or paid this quarter)"
        schema["order_intake"] = "number or null (order intake / bookings if disclosed)"
        schema["book_to_bill"] = "number or null (book-to-bill ratio if disclosed)"

        kpis_text = ", ".join(custom_kpi_list) if custom_kpi_list else "None specified."

        prompt = f"""You are a senior equity analyst extracting detailed earnings data for a portfolio management team.

Company: {company}
Target Period: {fiscal_period}
Custom KPIs to extract: {kpis_text}

The text below is scraped from {company}'s official investor relations materials (press release and/or investor presentation). It may include multiple documents separated by === headers.

## SOURCE DOCUMENTS
{page_text}

## EXTRACTION INSTRUCTIONS
1. Scan ALL sections of ALL documents before answering — financial tables are often in the appendix.
2. Extract ALL P&L items: group revenue, gross profit (with margin %), EBIT/EBITA/EBITDA (with margin %), net income, EPS (basic and diluted).
3. Extract cash flow statement items if present: operating cash flow, capex, free cash flow.
4. Extract balance sheet highlights if present: net debt (= total financial debt − cash & equivalents).
5. For segment_breakdown: capture EVERY reported business segment with revenue, margin %, and YoY growth %. Do not skip any segments.
6. For guidance_detail: quote the exact numbers and language — e.g. "FY2026 revenue growth outlook raised to 8–10%; adjusted EBIT margin guidance 17–19%; capex guidance maintained at €2.7bn".
7. For order_intake and book_to_bill: look for order intake, new orders, bookings, or B2B ratio tables — common in industrials, semiconductors, and tech.
8. For mgmt_tone: infer from CEO/CFO quotes and outlook language (positive/cautious/neutral/negative).
9. For beat_miss: compare actual vs analyst consensus if mentioned; otherwise infer from beat/miss language in the document; otherwise null.
10. For key_highlights: 5–6 concise, number-rich bullets a PM would highlight. Each bullet must contain at least one specific figure.
11. For red_flags: any miss vs prior guidance, margin compression, revenue/order intake weakness, unusual items, cautionary management language.
12. post_brief: 4–5 sentences of flowing prose with specific numbers — revenue result with growth rate, margin evolution, key segment dynamics, cash generation, guidance update, and overall narrative.

## REQUIRED JSON SCHEMA
{json.dumps(schema, indent=2)}

Respond with valid JSON only. No markdown, no preamble. Be thorough and precise — shallow or number-free outputs are not acceptable."""

        return await self._call_with_retry(prompt, max_tokens=6000)


# Module-level singleton
claude_service = ClaudeService()
