"""
Watchlist router.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models.schemas import WatchlistEntry, WatchlistCreate, Company, MessageResponse

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


def _row_to_entry(row, company_row=None) -> WatchlistEntry:
    company = None
    if company_row:
        company = Company(
            ticker=company_row["ticker"],
            name=company_row["name"],
            sector=company_row["sector"],
            exchange=company_row["exchange"],
            country=company_row["country"],
            fmp_symbol=company_row["fmp_symbol"],
            custom_kpis=company_row["custom_kpis"] or [],
            added_by=company_row["added_by"],
            active=company_row["active"],
            created_at=company_row["created_at"],
        )
    conditions = row.get("alert_conditions")
    if conditions and isinstance(conditions, str):
        try:
            conditions = json.loads(conditions)
        except Exception:
            conditions = {}

    return WatchlistEntry(
        id=str(row["id"]),
        user_email=row["user_email"],
        user_name=row["user_name"],
        ticker=row["ticker"],
        notify_pre_brief=row["notify_pre_brief"],
        notify_post_brief=row["notify_post_brief"],
        alert_conditions=conditions or {},
        created_at=row["created_at"],
        company=company,
    )


@router.get("/{email}", response_model=List[WatchlistEntry])
async def get_watchlist(email: str, db: AsyncSession = Depends(get_db)):
    """Get all watchlist entries for a user email."""
    result = await db.execute(
        text(
            """
            SELECT w.*, c.ticker as c_ticker, c.name, c.sector, c.exchange, c.country,
                   c.fmp_symbol, c.custom_kpis, c.added_by, c.active, c.created_at as c_created
            FROM watchlists w
            JOIN companies c ON c.ticker = w.ticker
            WHERE w.user_email = :email
            ORDER BY w.created_at DESC
            """
        ),
        {"email": email.lower()},
    )
    rows = result.mappings().all()

    entries = []
    for row in rows:
        # Reconstruct row-like objects
        w_row = {
            "id": row["id"],
            "user_email": row["user_email"],
            "user_name": row["user_name"],
            "ticker": row["ticker"],
            "notify_pre_brief": row["notify_pre_brief"],
            "notify_post_brief": row["notify_post_brief"],
            "created_at": row["created_at"],
        }
        c_row = {
            "ticker": row["c_ticker"],
            "name": row["name"],
            "sector": row["sector"],
            "exchange": row["exchange"],
            "country": row["country"],
            "fmp_symbol": row["fmp_symbol"],
            "custom_kpis": row["custom_kpis"],
            "added_by": row["added_by"],
            "active": row["active"],
            "created_at": row["c_created"],
        }
        entries.append(_row_to_entry(w_row, c_row))
    return entries


@router.post("/{email}/{ticker}", response_model=WatchlistEntry, status_code=status.HTTP_201_CREATED)
async def add_to_watchlist(
    email: str,
    ticker: str,
    db: AsyncSession = Depends(get_db),
):
    """Add a company to a user's watchlist."""
    # Check company exists
    c_result = await db.execute(
        text("SELECT * FROM companies WHERE ticker = :ticker"),
        {"ticker": ticker.upper()},
    )
    company_row = c_result.mappings().first()
    if not company_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company {ticker} not found.",
        )

    # Check duplicate
    dup = await db.execute(
        text(
            "SELECT id FROM watchlists WHERE user_email = :email AND ticker = :ticker"
        ),
        {"email": email.lower(), "ticker": ticker.upper()},
    )
    if dup.scalar():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{ticker} is already on your watchlist.",
        )

    await db.execute(
        text(
            """
            INSERT INTO watchlists (user_email, ticker, notify_pre_brief, notify_post_brief)
            VALUES (:email, :ticker, true, true)
            """
        ),
        {"email": email.lower(), "ticker": ticker.upper()},
    )
    await db.commit()

    # Fetch created entry
    result = await db.execute(
        text(
            "SELECT * FROM watchlists WHERE user_email = :email AND ticker = :ticker"
        ),
        {"email": email.lower(), "ticker": ticker.upper()},
    )
    row = result.mappings().first()
    return _row_to_entry(dict(row), dict(company_row))


@router.delete("/{email}/{ticker}", response_model=MessageResponse)
async def remove_from_watchlist(
    email: str,
    ticker: str,
    db: AsyncSession = Depends(get_db),
):
    """Remove a company from a user's watchlist."""
    result = await db.execute(
        text(
            "DELETE FROM watchlists WHERE user_email = :email AND ticker = :ticker RETURNING id"
        ),
        {"email": email.lower(), "ticker": ticker.upper()},
    )
    deleted = result.scalar()
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{ticker} not found in watchlist for {email}.",
        )
    await db.commit()
    return MessageResponse(message=f"{ticker} removed from watchlist.")


@router.patch("/{email}/{ticker}", response_model=WatchlistEntry)
async def update_watchlist_preferences(
    email: str,
    ticker: str,
    notify_pre_brief: Optional[bool] = None,
    notify_post_brief: Optional[bool] = None,
    alert_conditions: Optional[str] = None,  # JSON string, e.g. '{"notify_on":["miss"]}'
    db: AsyncSession = Depends(get_db),
):
    """Update notification preferences and alert conditions for a watchlist entry."""
    updates: Dict[str, Any] = {}
    if notify_pre_brief is not None:
        updates["notify_pre_brief"] = notify_pre_brief
    if notify_post_brief is not None:
        updates["notify_post_brief"] = notify_post_brief
    if alert_conditions is not None:
        updates["alert_conditions"] = alert_conditions  # stored as raw JSON string → cast below

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No preferences to update.",
        )

    set_clauses = []
    for k in updates:
        if k == "alert_conditions":
            set_clauses.append(f"{k} = CAST(:{k} AS jsonb)")
        else:
            set_clauses.append(f"{k} = :{k}")
    params = {"email": email.lower(), "ticker": ticker.upper(), **updates}
    await db.execute(
        text(
            f"UPDATE watchlists SET {', '.join(set_clauses)} WHERE user_email = :email AND ticker = :ticker"
        ),
        params,
    )
    await db.commit()

    result = await db.execute(
        text(
            """
            SELECT w.*, c.ticker as c_ticker, c.name, c.sector, c.exchange, c.country,
                   c.fmp_symbol, c.custom_kpis, c.added_by, c.active, c.created_at as c_created
            FROM watchlists w
            JOIN companies c ON c.ticker = w.ticker
            WHERE w.user_email = :email AND w.ticker = :ticker
            """
        ),
        {"email": email.lower(), "ticker": ticker.upper()},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Entry not found.")

    w_row = {
        "id": row["id"],
        "user_email": row["user_email"],
        "user_name": row["user_name"],
        "ticker": row["ticker"],
        "notify_pre_brief": row["notify_pre_brief"],
        "notify_post_brief": row["notify_post_brief"],
        "alert_conditions": row.get("alert_conditions") or {},
        "created_at": row["created_at"],
    }
    c_row = {
        "ticker": row["c_ticker"],
        "name": row["name"],
        "sector": row["sector"],
        "exchange": row["exchange"],
        "country": row["country"],
        "fmp_symbol": row["fmp_symbol"],
        "custom_kpis": row["custom_kpis"],
        "added_by": row["added_by"],
        "active": row["active"],
        "created_at": row["c_created"],
    }
    return _row_to_entry(w_row, c_row)
