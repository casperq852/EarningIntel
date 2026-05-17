"""
Onboarding router — research a company via Claude agent, stream progress via SSE,
then persist IR URL, custom KPIs, and historical earnings records.
"""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Any, Dict, List, Optional

import anthropic
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from services.onboard import run_onboard_agent

load_dotenv()

router = APIRouter(prefix="/onboard", tags=["onboard"])

_JSONB_FIELDS = {"pre_brief", "post_brief", "custom_kpis", "key_highlights", "red_flags"}


async def _upsert_earnings(db: AsyncSession, ticker: str, fiscal_period: str, data: Dict[str, Any]) -> None:
    result = await db.execute(
        text("SELECT id FROM earnings WHERE ticker = :t AND fiscal_period = :fp"),
        {"t": ticker, "fp": fiscal_period},
    )
    existing = result.scalar()
    params = {"t": ticker, "fp": fiscal_period, **data}

    if existing:
        clauses = [
            f"{k} = CAST(:{k} AS jsonb)" if k in _JSONB_FIELDS else f"{k} = :{k}"
            for k in data
        ]
        await db.execute(
            text(f"UPDATE earnings SET {', '.join(clauses)} WHERE ticker = :t AND fiscal_period = :fp"),
            params,
        )
    else:
        cols = ["ticker", "fiscal_period"] + list(data.keys())
        vals = [":t", ":fp"] + [
            f"CAST(:{k} AS jsonb)" if k in _JSONB_FIELDS else f":{k}" for k in data.keys()
        ]
        await db.execute(
            text(f"INSERT INTO earnings ({', '.join(cols)}) VALUES ({', '.join(vals)})"),
            params,
        )


async def _persist_onboard_result(
    db: AsyncSession,
    ticker: str,
    result: Dict[str, Any],
) -> Dict[str, str]:
    """Save onboarding data to DB. Returns a summary of what was saved."""
    saved: Dict[str, str] = {}

    # 1. Update company: ir_url, custom_kpis, overview, kpi_rationale
    updates: Dict[str, Any] = {}
    if result.get("ir_url"):
        updates["ir_url"] = result["ir_url"]
    if result.get("custom_kpis"):
        updates["custom_kpis"] = json.dumps(result["custom_kpis"])
    if result.get("company_overview"):
        updates["overview"] = result["company_overview"]
    if result.get("kpi_rationale"):
        updates["kpi_rationale"] = result["kpi_rationale"]

    if updates:
        clauses = [
            f"{k} = CAST(:{k} AS jsonb)" if k == "custom_kpis" else f"{k} = :{k}"
            for k in updates
        ]
        params = {"ticker": ticker, **updates}
        await db.execute(
            text(f"UPDATE companies SET {', '.join(clauses)} WHERE ticker = :ticker"),
            params,
        )
        saved["company_fields"] = ", ".join(updates.keys())

    # 2. Persist recent quarters — only insert if no existing post_brief
    quarters: List[Dict[str, Any]] = result.get("recent_quarters", [])

    # Sort quarters descending so we know which is the most recent
    def _sort_key(q: Dict) -> str:
        fp = q.get("fiscal_period", "Q0-0000")
        try:
            parts = fp.split("-")
            return f"{parts[1]}{parts[0]}"  # e.g. "2026Q2"
        except Exception:
            return fp

    quarters_sorted = sorted(quarters, key=_sort_key, reverse=True)
    most_recent_fp = quarters_sorted[0].get("fiscal_period") if quarters_sorted else None

    saved_quarters = []
    for q in quarters:
        fp = q.get("fiscal_period")
        if not fp or fp == "Q?-????":
            continue

        # Skip if a full brief already exists for this period
        existing = await db.execute(
            text("SELECT post_brief FROM earnings WHERE ticker = :t AND fiscal_period = :fp"),
            {"t": ticker, "fp": fp},
        )
        existing_row = existing.mappings().first()
        if existing_row and existing_row["post_brief"]:
            continue

        seg = q.get("segment_breakdown") or {}
        is_latest = (fp == most_recent_fp)

        # Build a rich post_brief with all financial data the agent extracted
        ebit = q.get("ebit")
        net_income = q.get("net_income")
        revenue = q.get("revenue")
        eps = q.get("eps")

        ebit_margin = q.get("ebit_margin_pct")
        if ebit_margin is None and ebit is not None and revenue and revenue > 0:
            ebit_margin = round(ebit / revenue * 100, 1)

        post_brief_data: Dict[str, Any] = {
            "segment_breakdown": seg,
            "mgmt_tone": q.get("mgmt_tone"),
            "guidance_tone": q.get("guidance_tone"),
            "guidance_detail": q.get("guidance_detail"),
            "revenue_actual": revenue,
            "eps_actual": eps,
            "ebit": ebit,
            "ebit_margin_pct": ebit_margin,
            "net_income": net_income,
            "free_cash_flow": q.get("free_cash_flow"),
            "operating_cash_flow": q.get("operating_cash_flow"),
            "capex": q.get("capex"),
            "net_debt": q.get("net_debt"),
            "order_intake": q.get("order_intake"),
            "book_to_bill": q.get("book_to_bill"),
            "yoy_revenue_growth_pct": q.get("yoy_revenue_growth_pct"),
            "beat_miss": q.get("beat_miss"),
            "post_brief": result.get("latest_earnings_summary") if is_latest else None,
        }

        # Per-quarter highlights/red_flags from the new schema
        q_highlights = q.get("key_highlights") or []
        q_red_flags = q.get("red_flags") or []

        post_brief_json = json.dumps(post_brief_data)
        earnings_data: Dict[str, Any] = {
            "revenue_actual": revenue,
            "eps_actual": eps,
            "beat_miss": q.get("beat_miss"),
            "guidance_tone": q.get("guidance_tone"),
            "mgmt_tone": q.get("mgmt_tone"),
            "post_brief": post_brief_json,
            "key_highlights": json.dumps(q_highlights),
            "red_flags": json.dumps(q_red_flags),
            "custom_kpis": json.dumps({}),
            "data_source": "onboard_agent",
        }
        try:
            parts = fp.split("-")
            earnings_data["fiscal_year"] = int(parts[1])
            earnings_data["fiscal_quarter"] = int(parts[0][1])
        except Exception:
            pass

        try:
            await _upsert_earnings(db, ticker, fp, earnings_data)
            saved_quarters.append(fp)
        except Exception:
            pass

    if saved_quarters:
        saved["earnings_periods"] = ", ".join(saved_quarters)

    # 3. Create a stub for the next earnings date (so it shows in calendar)
    next_date_str = result.get("next_earnings_date")
    if next_date_str:
        try:
            next_date = date.fromisoformat(next_date_str)
            # Estimate fiscal period from date
            q_num = (next_date.month - 1) // 3 + 1
            fp = f"Q{q_num}-{next_date.year}"
            await _upsert_earnings(db, ticker, fp, {
                "report_date": next_date,
                "data_source": "onboard_agent",
                "key_highlights": json.dumps([]),
                "red_flags": json.dumps([]),
                "custom_kpis": json.dumps({}),
            })
            saved["next_earnings"] = f"{next_date_str} ({fp})"
        except Exception:
            pass

    await db.commit()
    return saved


@router.post("/{ticker}")
async def onboard_company(
    ticker: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Stream the onboarding research agent for a company.
    Yields SSE events with progress, then saves results to DB.
    """
    result = await db.execute(
        text("SELECT name, exchange, sector FROM companies WHERE ticker = :t"),
        {"t": ticker.upper()},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Company {ticker} not found")

    company_name = row["name"]
    exchange = row["exchange"] or ""
    sector = row["sector"] or ""

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")

    client = anthropic.AsyncAnthropic(api_key=api_key)

    async def event_stream():
        try:
            async for event in run_onboard_agent(client, company_name, ticker.upper(), exchange, sector):
                if event["type"] == "done":
                    # Persist to DB
                    try:
                        saved = await _persist_onboard_result(db, ticker.upper(), event["data"])
                        event["saved"] = saved
                    except Exception as e:
                        event["save_error"] = str(e)
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/{ticker}/status")
async def onboard_status(ticker: str, db: AsyncSession = Depends(get_db)):
    """Quick check: has this company been onboarded (has ir_url or earnings records)?"""
    result = await db.execute(
        text("SELECT ir_url, custom_kpis FROM companies WHERE ticker = :t"),
        {"t": ticker.upper()},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Company not found")

    earnings_result = await db.execute(
        text("SELECT COUNT(*) FROM earnings WHERE ticker = :t AND post_brief IS NOT NULL"),
        {"t": ticker.upper()},
    )
    brief_count = earnings_result.scalar() or 0

    return {
        "ticker": ticker.upper(),
        "has_ir_url": bool(row["ir_url"]),
        "has_custom_kpis": bool(row["custom_kpis"] and row["custom_kpis"] != "[]"),
        "briefs_count": brief_count,
        "onboarded": bool(row["ir_url"]) or brief_count > 0,
    }
