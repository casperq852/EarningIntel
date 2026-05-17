"""
Alphie RAG API client.
Endpoints: /v1/query, /v1/investment-case, /v1/articles, /v1/documents
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

BASE_URL = os.getenv("ALPHIE_BASE_URL", "https://alphie-api.megenol.com")
TIMEOUT = 30.0


def _headers() -> Dict[str, str]:
    key = os.getenv("ALPHIE_API_KEY", "")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


async def query(
    question: str,
    focus_notes: str = "",
    use_web: bool = False,
    k_chunks: int = 12,
    max_tokens: int = 600,
    min_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Query the RAG knowledge base. Returns {answer, sources, web_sources}."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            f"{BASE_URL}/v1/query",
            headers=_headers(),
            json={
                "question": question,
                "focus_notes": focus_notes,
                "use_web": use_web,
                "k_chunks": k_chunks,
                "max_tokens": max_tokens,
                "min_date": min_date,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def investment_case(
    company: str,
    guidance: str = "",
    web_allowed: bool = False,
) -> Dict[str, Any]:
    """Generate an investment case for a company. Returns {content, sources}."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{BASE_URL}/v1/investment-case",
            headers=_headers(),
            json={
                "company_or_query": company,
                "guidance": guidance,
                "web_allowed": web_allowed,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def ingest_article(
    url: str,
    title: Optional[str] = None,
    ticker_hint: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Push a URL into the RAG. Returns {article_id, ingested_chunks, deduped}."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{BASE_URL}/v1/articles",
            headers=_headers(),
            json={
                "url": url,
                "title": title,
                "ticker_hint": ticker_hint,
                "tags": tags or [],
            },
        )
        resp.raise_for_status()
        return resp.json()


async def list_documents() -> List[Dict[str, Any]]:
    """List all documents in the RAG."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(f"{BASE_URL}/v1/documents", headers=_headers())
        resp.raise_for_status()
        return resp.json()


def is_configured() -> bool:
    return bool(os.getenv("ALPHIE_API_KEY"))
