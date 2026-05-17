"""
Earnings chat router — RAG-style Q&A over stored IR documents.
Uses OpenRouter (OpenAI-compatible) with streaming via SSE.
Falls back to Anthropic API if OPENROUTER_API_KEY is not set.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import anthropic
import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from services import alphie as alphie_svc

router = APIRouter(prefix="/chat", tags=["chat"])

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "deepseek/deepseek-chat"   # DeepSeek-V3 — cheap and capable
FALLBACK_MODEL = "claude-haiku-4-5-20251001"  # Anthropic fallback

_SYSTEM_PROMPT = """You are an earnings analyst assistant for a portfolio management team. \
You have been given the official investor relations documents and a structured earnings brief \
for a specific company and reporting period.

Answer the PM's questions concisely and precisely. Always cite specific numbers when they exist \
in the source material. If the documents do not contain enough information to answer a question, \
say so clearly — do not hallucinate figures. Use bullet points for multi-part answers. \
Keep responses under 300 words unless the question explicitly requires more detail."""


class ChatMessage(BaseModel):
    role: str   # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    question: str
    history: List[ChatMessage] = []


async def _load_context(ticker: str, period: str, db: AsyncSession) -> str:
    """Build a context string from stored documents + structured brief."""
    # 1. Structured brief from earnings table
    result = await db.execute(
        text(
            "SELECT e.post_brief, e.pre_brief, e.revenue_actual, e.eps_actual, "
            "e.beat_miss, e.guidance_tone, e.mgmt_tone, "
            "e.key_highlights, e.red_flags, c.name "
            "FROM earnings e JOIN companies c ON e.ticker = c.ticker "
            "WHERE e.ticker = :ticker AND e.fiscal_period = :fp"
        ),
        {"ticker": ticker.upper(), "fp": period},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"No earnings data for {ticker} {period}")

    company_name = row["name"]
    parts: List[str] = [
        f"COMPANY: {company_name}  |  PERIOD: {period}\n",
    ]

    # Structured numbers
    structured: Dict[str, Any] = {}
    if row["post_brief"]:
        try:
            pb = row["post_brief"] if isinstance(row["post_brief"], dict) else json.loads(row["post_brief"])
            structured.update(pb)
        except Exception:
            pass
    if row["pre_brief"]:
        try:
            prb = row["pre_brief"] if isinstance(row["pre_brief"], dict) else json.loads(row["pre_brief"])
            structured.update(prb)
        except Exception:
            pass

    if structured:
        parts.append("=== STRUCTURED BRIEF ===")
        parts.append(json.dumps(structured, indent=2))
        parts.append("")

    # 2. Source document texts
    docs_result = await db.execute(
        text(
            "SELECT doc_type, title, source_url, extracted_text "
            "FROM documents "
            "WHERE ticker = :ticker AND fiscal_period = :fp "
            "AND extracted_text IS NOT NULL "
            "ORDER BY created_at ASC"
        ),
        {"ticker": ticker.upper(), "fp": period},
    )
    docs = docs_result.mappings().all()
    for doc in docs:
        parts.append(f"=== {doc['doc_type'].upper()}: {doc['title'] or doc['source_url']} ===")
        # Limit each doc to 20k chars to stay within model context
        parts.append((doc["extracted_text"] or "")[:20_000])
        parts.append("")

    return "\n".join(parts)


async def _fetch_alphie_context(company_name: str, question: str) -> str:
    """Query Alphie RAG for analyst research relevant to the question."""
    if not alphie_svc.is_configured():
        return ""
    try:
        result = await alphie_svc.query(
            question=question,
            focus_notes=f"Company: {company_name}",
            k_chunks=8,
            max_tokens=400,
        )
        answer = result.get("answer", "").strip()
        sources = result.get("sources", [])
        if not answer:
            return ""
        source_names = [s.get("filename", "") for s in sources[:3] if s.get("filename")]
        sources_text = "\n".join(f"  - {n}" for n in source_names) if source_names else ""
        return f"=== ANALYST RESEARCH (via Alphie RAG) ===\n{answer}\n{sources_text}"
    except Exception:
        return ""


def _build_messages(context: str, alphie_context: str, question: str, history: List[ChatMessage]) -> List[Dict[str, Any]]:
    full_context = context
    if alphie_context:
        full_context += f"\n\n{alphie_context}"
    messages: List[Dict[str, Any]] = [
        {
            "role": "user",
            "content": f"Here are the earnings materials for this session:\n\n{full_context[:65_000]}\n\n---\nConfirm you have the context.",
        },
        {
            "role": "assistant",
            "content": "I have the earnings materials and analyst research. Ready to answer your questions.",
        },
    ]
    for msg in history[-10:]:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": question})
    return messages


async def _stream_openrouter(context: str, alphie_context: str, question: str, history: List[ChatMessage]) -> Any:
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    messages = _build_messages(context, alphie_context, question, history)

    async def event_generator():
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                f"{OPENROUTER_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://earningintel.app",
                    "X-Title": "EarningIntel",
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "stream": True,
                    "max_tokens": 600,
                    "messages": [{"role": "system", "content": _SYSTEM_PROMPT}] + messages,
                },
            ) as response:
                if response.status_code != 200:
                    err = await response.aread()
                    yield f"data: {json.dumps({'error': err.decode()})}\n\n"
                    return
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        payload = line[6:]
                        if payload.strip() == "[DONE]":
                            yield "data: [DONE]\n\n"
                            return
                        yield f"data: {payload}\n\n"

    return event_generator()


async def _stream_anthropic(context: str, alphie_context: str, question: str, history: List[ChatMessage]) -> Any:
    client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    messages = _build_messages(context, alphie_context, question, history)

    async def event_generator():
        try:
            async with client.messages.stream(
                model=FALLBACK_MODEL,
                system=_SYSTEM_PROMPT,
                max_tokens=600,
                messages=messages,
            ) as stream:
                async for delta in stream.text_stream:
                    chunk = {"choices": [{"delta": {"content": delta}}]}
                    yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return event_generator()


@router.post("/{ticker}/{period}")
async def earnings_chat(
    ticker: str,
    period: str,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """Stream an answer to a question about a company's earnings period."""
    import asyncio
    # Load local context + Alphie RAG in parallel
    company_result = await db.execute(
        text("SELECT name FROM companies WHERE ticker = :t"),
        {"t": ticker.upper()},
    )
    company_row = company_result.mappings().first()
    company_name = company_row["name"] if company_row else ticker.upper()

    context, alphie_context = await asyncio.gather(
        _load_context(ticker, period, db),
        _fetch_alphie_context(company_name, body.question),
    )

    if os.getenv("OPENROUTER_API_KEY"):
        generator = await _stream_openrouter(context, alphie_context, body.question, body.history)
    else:
        generator = await _stream_anthropic(context, alphie_context, body.question, body.history)
    return StreamingResponse(generator, media_type="text/event-stream")


@router.get("/{ticker}/{period}/suggestions")
async def chat_suggestions(
    ticker: str,
    period: str,
    db: AsyncSession = Depends(get_db),
):
    """Return context-aware suggested questions for this earnings period."""
    result = await db.execute(
        text(
            "SELECT e.beat_miss, e.guidance_tone, e.mgmt_tone, "
            "e.post_brief, c.name, c.sector "
            "FROM earnings e JOIN companies c ON e.ticker = c.ticker "
            "WHERE e.ticker = :ticker AND e.fiscal_period = :fp"
        ),
        {"ticker": ticker.upper(), "fp": period},
    )
    row = result.mappings().first()

    base = [
        "What drove the revenue result this quarter?",
        "What is management guiding for next quarter?",
        "What are the main risks or red flags?",
        "How did each business segment perform?",
        "How does this quarter compare to the prior quarter?",
    ]

    if not row:
        return {"suggestions": base}

    extra: List[str] = []
    pb = {}
    if row["post_brief"]:
        try:
            pb = row["post_brief"] if isinstance(row["post_brief"], dict) else json.loads(row["post_brief"])
        except Exception:
            pass

    if row["beat_miss"] == "miss":
        extra.append("What caused the earnings miss and how is management responding?")
    elif row["beat_miss"] == "beat":
        extra.append("What were the key drivers of the earnings beat?")

    if row["guidance_tone"] in ("raised", "lowered"):
        extra.append(f"Why did management {row['guidance_tone']} guidance?")

    if pb.get("free_cash_flow") is not None:
        extra.append("What is the free cash flow outlook and how is capital being allocated?")

    if pb.get("segment_breakdown"):
        extra.append("Which segment had the best and worst performance, and why?")

    if pb.get("order_intake") is not None:
        extra.append("What does the order book suggest about near-term demand?")

    sector = (row["sector"] or "").lower()
    if "tech" in sector or "semiconductor" in sector:
        extra.append("What did management say about AI demand and the competitive landscape?")
    elif "pharma" in sector or "health" in sector:
        extra.append("What pipeline or regulatory updates did management highlight?")
    elif "financ" in sector or "bank" in sector:
        extra.append("What is management saying about credit quality and net interest margin?")

    return {"suggestions": (extra + base)[:6]}
