"""
Calendar router — upcoming earnings from DB only.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional, Set

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models.schemas import CalendarEntry

router = APIRouter(prefix="/calendar", tags=["calendar"])


async def _get_watchlist_tickers(db: AsyncSession) -> Set[str]:
    result = await db.execute(text("SELECT DISTINCT ticker FROM watchlists"))
    return {row[0] for row in result.fetchall()}


async def _get_company_map(db: AsyncSession) -> Dict[str, str]:
    result = await db.execute(
        text("SELECT ticker, name FROM companies WHERE active = true")
    )
    return {r["ticker"]: r["name"] for r in result.mappings().all()}


@router.get("", response_model=List[CalendarEntry])
async def get_upcoming_calendar(
    days: int = Query(default=14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    """
    Get upcoming earnings for the next N days from DB-scheduled dates.
    Falls back to estimating next report date (+91 days from last known).
    """
    today = date.today()
    from_date = today
    to_date = today + timedelta(days=days)

    company_map = await _get_company_map(db)
    watchlist_tickers = await _get_watchlist_tickers(db)
    platform_tickers = set(company_map.keys())

    # 1. DB-scheduled dates in window
    result = await db.execute(
        text("""
            SELECT DISTINCT ON (ticker) ticker, report_date, revenue_est, eps_est
            FROM earnings
            WHERE report_date BETWEEN :from_date AND :to_date
            ORDER BY ticker, report_date ASC
        """),
        {"from_date": from_date, "to_date": to_date},
    )
    entries: List[CalendarEntry] = []
    covered: Set[str] = set()
    for r in result.mappings().all():
        t = r["ticker"]
        if t not in company_map:
            continue
        entries.append(CalendarEntry(
            ticker=t,
            company_name=company_map[t],
            report_date=r["report_date"],
            revenue_est=r["revenue_est"],
            eps_est=r["eps_est"],
            is_watchlist=t in watchlist_tickers,
            on_platform=True,
        ))
        covered.add(t)

    # 2. Estimate for platform companies with no scheduled date in window
    missing = platform_tickers - covered
    if missing:
        result2 = await db.execute(
            text("""
                SELECT DISTINCT ON (ticker) ticker, report_date
                FROM earnings
                WHERE report_date IS NOT NULL
                ORDER BY ticker, report_date DESC
            """)
        )
        for r in result2.mappings().all():
            t = r["ticker"]
            if t not in missing:
                continue
            next_rd = r["report_date"] + timedelta(days=91)
            while next_rd < from_date:
                next_rd += timedelta(days=91)
            if from_date <= next_rd <= to_date:
                entries.append(CalendarEntry(
                    ticker=t,
                    company_name=company_map[t],
                    report_date=next_rd,
                    is_watchlist=t in watchlist_tickers,
                    on_platform=True,
                ))

    entries.sort(key=lambda e: e.report_date)
    return entries


@router.get("/today", response_model=List[CalendarEntry])
async def get_todays_earnings(db: AsyncSession = Depends(get_db)):
    """Get earnings releasing today."""
    today = date.today()
    company_map = await _get_company_map(db)
    watchlist_tickers = await _get_watchlist_tickers(db)

    result = await db.execute(
        text("SELECT ticker, report_date, revenue_est, eps_est FROM earnings WHERE report_date = :today"),
        {"today": today},
    )
    return [
        CalendarEntry(
            ticker=r["ticker"],
            company_name=company_map.get(r["ticker"], r["ticker"]),
            report_date=r["report_date"],
            revenue_est=r["revenue_est"],
            eps_est=r["eps_est"],
            is_watchlist=r["ticker"] in watchlist_tickers,
            on_platform=r["ticker"] in company_map,
        )
        for r in result.mappings().all()
        if r["ticker"] in company_map
    ]
