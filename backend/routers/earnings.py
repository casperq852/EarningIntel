"""
Earnings router.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models.schemas import Earnings

router = APIRouter(prefix="/earnings", tags=["earnings"])


def _row_to_earnings(row) -> Earnings:
    return Earnings(
        id=str(row["id"]),
        ticker=row["ticker"],
        report_date=row["report_date"],
        fiscal_period=row["fiscal_period"],
        fiscal_year=row["fiscal_year"],
        fiscal_quarter=row["fiscal_quarter"],
        revenue_actual=float(row["revenue_actual"]) if row["revenue_actual"] is not None else None,
        revenue_est=float(row["revenue_est"]) if row["revenue_est"] is not None else None,
        revenue_surprise_pct=float(row["revenue_surprise_pct"]) if row["revenue_surprise_pct"] is not None else None,
        eps_actual=float(row["eps_actual"]) if row["eps_actual"] is not None else None,
        eps_est=float(row["eps_est"]) if row["eps_est"] is not None else None,
        eps_surprise_pct=float(row["eps_surprise_pct"]) if row["eps_surprise_pct"] is not None else None,
        beat_miss=row["beat_miss"],
        guidance_tone=row["guidance_tone"],
        mgmt_tone=row["mgmt_tone"],
        custom_kpis=row["custom_kpis"] or {},
        pre_brief=row["pre_brief"],
        post_brief=row["post_brief"],
        key_highlights=row["key_highlights"] or [],
        red_flags=row["red_flags"] or [],
        transcript_available=row["transcript_available"],
        data_source=row["data_source"],
        created_at=row["created_at"],
    )


@router.get("/trends")
async def get_earnings_trends(
    tickers: str,
    quarters: int = Query(default=5, ge=2, le=12),
    db: AsyncSession = Depends(get_db),
):
    """
    Return last N quarters of revenue + ebit_margin_pct per ticker.
    tickers: comma-separated list, e.g. "ASML,SIE,SAP"
    Returns: {TICKER: [{fiscal_period, revenue, ebit_margin_pct, beat_miss}, ...]}
    """
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        return {}

    result = await db.execute(
        text(
            """
            SELECT ticker, fiscal_period, revenue_actual, post_brief, beat_miss,
                   fiscal_year, fiscal_quarter
            FROM earnings
            WHERE ticker = ANY(:tickers)
              AND (revenue_actual IS NOT NULL OR post_brief IS NOT NULL)
            ORDER BY ticker, fiscal_year DESC NULLS LAST, fiscal_quarter DESC NULLS LAST
            """
        ),
        {"tickers": ticker_list},
    )
    rows = result.mappings().all()

    import json as _json
    out: Dict[str, List[Dict[str, Any]]] = {t: [] for t in ticker_list}
    counts: Dict[str, int] = {t: 0 for t in ticker_list}

    for row in rows:
        t = row["ticker"]
        if counts[t] >= quarters:
            continue
        # Try to get ebit_margin from post_brief JSONB
        ebit_margin = None
        if row["post_brief"]:
            try:
                pb = row["post_brief"] if isinstance(row["post_brief"], dict) else _json.loads(row["post_brief"])
                ebit_margin = pb.get("ebit_margin_pct")
            except Exception:
                pass
        out[t].append({
            "fiscal_period": row["fiscal_period"],
            "revenue": float(row["revenue_actual"]) if row["revenue_actual"] is not None else None,
            "ebit_margin_pct": ebit_margin,
            "beat_miss": row["beat_miss"],
        })
        counts[t] += 1

    # Reverse each list so oldest → newest (left to right for charts)
    return {t: list(reversed(v)) for t, v in out.items()}


@router.get("/recent", response_model=List[Earnings])
async def get_recent_earnings(db: AsyncSession = Depends(get_db)):
    """Get earnings from the last 30 days across all companies."""
    since = date.today() - timedelta(days=30)
    result = await db.execute(
        text(
            """
            SELECT e.* FROM earnings e
            JOIN companies c ON c.ticker = e.ticker
            WHERE e.report_date >= :since AND c.active = true
            ORDER BY e.report_date DESC
            """
        ),
        {"since": since},
    )
    rows = result.mappings().all()
    return [_row_to_earnings(r) for r in rows]


@router.get("/{ticker}", response_model=List[Earnings])
async def get_earnings_for_ticker(ticker: str, db: AsyncSession = Depends(get_db)):
    """Get all historical earnings for a ticker."""
    result = await db.execute(
        text(
            """
            SELECT * FROM earnings
            WHERE ticker = :ticker
            ORDER BY report_date DESC NULLS LAST, fiscal_period DESC
            """
        ),
        {"ticker": ticker.upper()},
    )
    rows = result.mappings().all()
    if not rows:
        # Verify company exists
        check = await db.execute(
            text("SELECT ticker FROM companies WHERE ticker = :ticker"),
            {"ticker": ticker.upper()},
        )
        if not check.scalar():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Company {ticker} not found.",
            )
    return [_row_to_earnings(r) for r in rows]


@router.get("/{ticker}/{period}", response_model=Earnings)
async def get_single_earnings(
    ticker: str,
    period: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get a single earnings record.
    Period format: Q1-2026
    """
    result = await db.execute(
        text(
            """
            SELECT * FROM earnings
            WHERE ticker = :ticker AND fiscal_period = :period
            """
        ),
        {"ticker": ticker.upper(), "period": period},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No earnings record found for {ticker} {period}.",
        )
    return _row_to_earnings(row)
