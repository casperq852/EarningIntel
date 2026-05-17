"""
Earnings document gatherer — searches for press releases, investor presentations,
and announcements; downloads them; extracts clean text for Claude synthesis.

Search priority per document slot:
  1. ir_url override stored on the company record (always used as press_release slot)
  2. Brave Search API (BRAVE_SEARCH_API_KEY required for auto-search)
"""
from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass, field
from typing import Optional

import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_STRIP_TAGS = ["script", "style", "nav", "footer", "header", "aside", "noscript", "iframe"]
MAX_CHARS_PER_DOC = 35_000
MAX_CHARS_COMBINED = 80_000

_SKIP_DOMAINS = {
    # Financial news / paywall
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com", "cnbc.com",
    "marketwatch.com", "businessinsider.com", "thestreet.com",
    # Stock data aggregators
    "seekingalpha.com", "yahoo.com", "google.com", "investing.com",
    "stockanalysis.com", "macrotrends.net", "finviz.com", "tikr.com",
    "koyfin.com", "alphaspread.com", "simplywall.st", "tradingeconomics.com",
    "marketscreener.com", "4-traders.com", "zonebourse.com", "wisesheets.io",
    "wallstreetmojo.com", "macroaxis.com", "stocktitan.net", "quartr.com",
    # Crypto/misc aggregators
    "coincodex.com", "wisesheets.io", "stockevents.app", "thestreet.com",
    # Earnings calendars / estimates
    "marketbeat.com", "earningswhispers.com", "wallstreethorizon.com",
    "estimize.com", "zacks.com", "thefly.com", "briefing.com",
    # Wire services (plain HTML, not official IR)
    "businesswire.com", "prnewswire.com", "globenewswire.com",
    # Content farms / unofficial analysis / secondary sources
    "fool.com", "meyka.com", "nasdaq.com", "investegate.co.uk",
    "marketchameleon.com", "barchart.com", "gurufocus.com", "simply-wall-st.com",
    "stockanalysis.com", "chartmill.com", "tipranks.com", "benzinga.com",
    "theglobeandmail.com", "tickerreport.com", "statista.com", "annualreports.com",
    "comparably.com", "craft.co", "cboe.com", "sec.gov",
}

_IR_KEYWORDS = [
    "investor", "ir.", "press-release", "press_release",
    "media-release", "newsroom", "results", "earnings", "hugin",
]


@dataclass
class EarningsDoc:
    url: str
    doc_type: str          # press_release | presentation | transcript | announcement
    title: str
    mime_type: str         # text/html | application/pdf
    content_bytes: bytes
    extracted_text: str


def _infer_doc_type(url: str, mime_type: str, query_hint: str) -> str:
    u = url.lower()
    if "transcript" in u:
        return "transcript"
    if any(kw in u for kw in ("presentation", "slides", "slide-deck", "investor-day", "investor_day")):
        return "presentation"
    if any(kw in u for kw in ("announcement", "adhoc", "ad-hoc", "regulatory", "notification")):
        return "announcement"
    if any(kw in u for kw in ("press", "press-release", "press_release", "media-release", "newsroom")):
        return "press_release"
    if "pdf" in mime_type.lower() or u.endswith(".pdf"):
        return "presentation"
    return query_hint or "press_release"


def _title_from_url(url: str) -> str:
    path = url.rstrip("/").split("/")[-1]
    path = re.sub(r"\.(html?|pdf|aspx|php)$", "", path, flags=re.I)
    return re.sub(r"[-_]", " ", path).strip() or url


def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(_STRIP_TAGS):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return cleaned[:MAX_CHARS_PER_DOC]


def _extract_pdf_text(content_bytes: bytes) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(content_bytes)) as pdf:
            pages_text = []
            for page in pdf.pages[:40]:
                text = page.extract_text()
                if text:
                    pages_text.append(text)
            return "\n\n".join(pages_text)[:MAX_CHARS_PER_DOC]
    except Exception as e:
        return f"[PDF text extraction failed: {e}]"


async def _fetch_document(url: str, timeout: float = 30.0) -> tuple[bytes, str, str]:
    """Fetch a URL and return (content_bytes, extracted_text, mime_type)."""
    async with httpx.AsyncClient(headers=HEADERS, timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        content_bytes = response.content

        if "pdf" in content_type or url.lower().endswith(".pdf"):
            return content_bytes, _extract_pdf_text(content_bytes), "application/pdf"
        else:
            return content_bytes, _clean_html(response.text), "text/html"


def _is_skipped(url: str) -> bool:
    if not url:
        return True
    return any(d in url for d in _SKIP_DOMAINS)


async def _brave_search(query: str, count: int = 6) -> list[str]:
    """Run one Brave search query and return candidate URLs."""
    brave_key = os.getenv("BRAVE_SEARCH_API_KEY", "")
    if not brave_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"X-Subscription-Token": brave_key, "Accept": "application/json"},
                params={"q": query, "count": count, "search_lang": "en"},
            )
            resp.raise_for_status()
            results = resp.json().get("web", {}).get("results", [])
    except Exception:
        return []

    # IR-keyword URLs first, then fallback
    ir_urls = [
        r["url"] for r in results
        if r.get("url") and not _is_skipped(r["url"]) and not r["url"].lower().endswith(".pdf")
        and any(kw in r["url"].lower() for kw in _IR_KEYWORDS)
    ]
    pdf_urls = [
        r["url"] for r in results
        if r.get("url") and not _is_skipped(r["url"]) and r["url"].lower().endswith(".pdf")
    ]
    other_urls = [
        r["url"] for r in results
        if r.get("url") and not _is_skipped(r["url"]) and not r["url"].lower().endswith(".pdf")
        and r["url"] not in ir_urls
    ]
    return ir_urls + pdf_urls + other_urls


def _extract_domain(url: str) -> Optional[str]:
    """Extract bare hostname from a URL, e.g. 'www.siemens.com' → 'siemens.com'."""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
        # Strip 'www.' prefix so site: query works for all subdomains
        return host.removeprefix("www.")
    except Exception:
        return None


async def gather_earnings_docs(
    company: str,
    fiscal_period: str,
    ir_url_override: Optional[str] = None,
    max_docs: int = 4,
) -> list[EarningsDoc]:
    """
    Gather earnings documents for a company/period.
    Tries up to max_docs unique URLs from ir_url_override + Brave Search.
    Returns EarningsDoc list (may be empty if nothing works).
    """
    from datetime import date as _date
    year = _date.today().year

    # Base search slots — generic queries
    search_slots = [
        (f'"{company}" {fiscal_period} results press release',         "press_release"),
        (f'"{company}" {fiscal_period} investor presentation',          "presentation"),
        (f'"{company}" {fiscal_period} quarterly results announcement', "announcement"),
        (f'"{company}" {year} earnings results investor relations',     "press_release"),
    ]

    # If we know the company's IR domain, prepend a domain-restricted query — much
    # more reliable than hoping the generic query surfaces the official site.
    if ir_url_override:
        ir_domain = _extract_domain(ir_url_override)
        if ir_domain:
            # Two domain-restricted queries: one for HTML press release, one for PDF
            search_slots.insert(0, (
                f'site:{ir_domain} {fiscal_period} results filetype:pdf',
                "presentation",
            ))
            search_slots.insert(0, (
                f'site:{ir_domain} {fiscal_period} earnings results press release',
                "press_release",
            ))

    candidate_pairs: list[tuple[str, str]] = []  # (url, hint)

    if ir_url_override:
        candidate_pairs.append((ir_url_override, "press_release"))

    seen = {ir_url_override} if ir_url_override else set()

    for query, hint in search_slots:
        if len(candidate_pairs) >= max_docs:
            break
        urls = await _brave_search(query)
        for url in urls:
            if url not in seen:
                seen.add(url)
                candidate_pairs.append((url, hint))
                break  # one new URL per search slot

    docs: list[EarningsDoc] = []
    for url, hint in candidate_pairs[:max_docs]:
        try:
            content_bytes, extracted_text, mime_type = await _fetch_document(url)
            doc_type = _infer_doc_type(url, mime_type, hint)
            docs.append(EarningsDoc(
                url=url,
                doc_type=doc_type,
                title=_title_from_url(url),
                mime_type=mime_type,
                content_bytes=content_bytes,
                extracted_text=extracted_text,
            ))
        except Exception:
            continue

    return docs


def combine_doc_texts(docs: list[EarningsDoc]) -> str:
    """Concatenate extracted texts from multiple docs with section headers."""
    parts = []
    for doc in docs:
        header = f"=== {doc.doc_type.upper().replace('_', ' ')}: {doc.title} ===\nSource: {doc.url}\n"
        parts.append(header + doc.extracted_text)
    combined = "\n\n".join(parts)
    return combined[:MAX_CHARS_COMBINED]


# ---------------------------------------------------------------------------
# Legacy shim — kept for backwards compatibility
# ---------------------------------------------------------------------------

async def find_and_fetch(
    company: str,
    fiscal_period: str,
    ir_url_override: Optional[str] = None,
) -> tuple[str, str]:
    """
    Find and fetch the primary earnings page. Returns (page_text, source_url).
    Wraps gather_earnings_docs for single-doc backwards compatibility.
    """
    docs = await gather_earnings_docs(company, fiscal_period, ir_url_override, max_docs=1)
    if not docs:
        brave_key = os.getenv("BRAVE_SEARCH_API_KEY", "")
        if not brave_key:
            raise RuntimeError(
                f"No ir_url set for {company} and BRAVE_SEARCH_API_KEY is not configured. "
                "Either set ir_url on the company record via PUT /companies/{ticker}, "
                "or add BRAVE_SEARCH_API_KEY to .env."
            )
        raise RuntimeError(
            f"Brave Search returned no usable results for {company} {fiscal_period}. "
            "Set ir_url manually via PUT /companies/{ticker}."
        )
    return docs[0].extracted_text, docs[0].url
