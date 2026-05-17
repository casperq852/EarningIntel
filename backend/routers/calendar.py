"""
Calendar router — upcoming earnings.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional, Set

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models.schemas import CalendarEntry
from services.fmp import fmp_client

router = APIRouter(prefix="/calendar", tags=["calendar"])


async def _get_watchlist_tickers(db: AsyncSession) -> Set[str]:
    """Return all tickers that appear in any watchlist."""
    result = await db.execute(text("SELECT DISTINCT ticker FROM watchlists"))
    return {row[0] for row in result.fetchall()}


async def _get_platform_tickers(db: AsyncSession) -> Set[str]:
    """Return all active tickers on the platform."""
    result = await db.execute(
        text("SELECT ticker FROM companies WHERE active = true")
    )
    return {row[0] for row in result.fetchall()}


async def _get_company_names(db: AsyncSession) -> dict:
    """Return mapping of ticker → name for active companies."""
    result = await db.execute(
        text("SELECT ticker, name, fmp_symbol FROM companies WHERE active = true")
    )
    return {r["ticker"]: {"name": r["name"], "fmp_symbol": r["fmp_symbol"]} for r in result.mappings().all()}


def _parse_fmp_calendar(raw: list, company_map: dict, watchlist: Set[str], platform: Set[str]) -> List[CalendarEntry]:
    """Convert FMP calendar response to CalendarEntry list."""
    entries = []
    for item in raw:
        symbol = item.get("symbol", "")
        if not symbol:
            continue
        # Match to platform ticker (fmp_symbol may differ)
        ticker = symbol
        for t, info in company_map.items():
            if info.get("fmp_symbol") == symbol or t == symbol:
                ticker = t
                break

        report_date_str = item.get("date") or item.get("reportDate")
        if not report_date_str:
            continue
        try:
            report_date = date.fromisoformat(report_date_str)
        except ValueError:
            continue

        entries.append(
            CalendarEntry(
                ticker=ticker,
                company_name=company_map.get(ticker, {}).get("name") or item.get("name"),
                report_date=report_date,
                eps_est=item.get("estimatedEPS") or item.get("epsEstimated"),
                revenue_est=item.get("estimatedRevenue") or item.get("revenueEstimated"),
                time_of_day=item.get("time"),
                is_watchlist=ticker in watchlist,
                on_platform=ticker in platform,
            )
        )
    return entries


async def _get_db_scheduled_dates(
    db: AsyncSession,
    from_date: date,
    to_date: date,
) -> Dict[str, date]:
    """
    Return {ticker: report_date} for earnings rows that have a report_date
    already scheduled in the given window.
    """
    result = await db.execute(
        text(
            "SELECT ticker, report_date FROM earnings "
            "WHERE report_date BETWEEN :from_date AND :to_date"
        ),
        {"from_date": from_date, "to_date": to_date},
    )
    return {r["ticker"]: r["report_date"] for r in result.mappings().all()}


async def _estimate_next_report_dates(
    db: AsyncSession,
    missing_tickers: Set[str],
    company_map: dict,
    from_date: date,
    to_date: date,
) -> Dict[str, date]:
    """
    For platform companies with no FMP or DB-scheduled date, estimate the next
    report date by adding ~91 days to the most recent known report_date.
    """
    if not missing_tickers:
        return {}
    result = await db.execute(
        text(
            "SELECT DISTINCT ON (ticker) ticker, report_date "
            "FROM earnings WHERE report_date IS NOT NULL "
            "ORDER BY ticker, report_date DESC"
        )
    )
    estimated: Dict[str, date] = {}
    for r in result.mappings().all():
        ticker = r["ticker"]
        if ticker not in missing_tickers:
            continue
        last_rd = r["report_date"]
        # Estimate the next quarterly report: add 91 days
        next_rd = last_rd + timedelta(days=91)
        while next_rd < from_date:
            next_rd += timedelta(days=91)
        if from_date <= next_rd <= to_date:
            estimated[ticker] = next_rd
    return estimated


@router.get("", response_model=List[CalendarEntry])
async def get_upcoming_calendar(
    days: int = Query(default=14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    """
    Get upcoming earnings for the next N days.
    Sources (in priority): FMP calendar API → DB scheduled dates → estimated from history.
    """
    today = date.today()
    from_date = today
    to_date = today + timedelta(days=days)

    company_map = await _get_company_names(db)
    watchlist_tickers = await _get_watchlist_tickers(db)
    platform_tickers = await _get_platform_tickers(db)

    # 1. FMP calendar API
    raw = await fmp_client.get_earnings_calendar(from_date.isoformat(), to_date.isoformat())
    entries = _parse_fmp_calendar(raw, company_map, watchlist_tickers, platform_tickers)
    covered = {e.ticker for e in entries}

    # 2. DB-scheduled dates for platform companies not yet covered
    db_dates = await _get_db_scheduled_dates(db, from_date, to_date)
    for ticker, rd in db_dates.items():
        if ticker not in covered and ticker in company_map:
            entries.append(
                CalendarEntry(
                    ticker=ticker,
                    company_name=company_map[ticker]["name"],
                    report_date=rd,
                    is_watchlist=ticker in watchlist_tickers,
                    on_platform=True,
                )
            )
            covered.add(ticker)

    # 3. Estimate next report date from historical pattern for remaining platform companies
    missing = platform_tickers - covered
    if missing:
        estimated = await _estimate_next_report_dates(db, missing, company_map, from_date, to_date)
        for ticker, rd in estimated.items():
            if ticker in company_map:
                entries.append(
                    CalendarEntry(
                        ticker=ticker,
                        company_name=company_map[ticker]["name"],
                        report_date=rd,
                        is_watchlist=ticker in watchlist_tickers,
                        on_platform=True,
                    )
                )

    entries.sort(key=lambda e: e.report_date)
    return entries


@router.get("/today", response_model=List[CalendarEntry])
async def get_todays_earnings(db: AsyncSession = Depends(get_db)):
    """Get earnings releasing today."""
    today_str = date.today().isoformat()
    company_map = await _get_company_names(db)
    watchlist_tickers = await _get_watchlist_tickers(db)
    platform_tickers = await _get_platform_tickers(db)

    try:
        raw = await fmp_client.get_earnings_calendar(today_str, today_str)
    except Exception:
        raw = []

    entries = _parse_fmp_calendar(raw, company_map, watchlist_tickers, platform_tickers)
    return entries
