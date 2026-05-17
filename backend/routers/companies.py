"""
Companies router.
"""
from __future__ import annotations

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models.schemas import Company, CompanyCreate, CompanyUpdate, MessageResponse

router = APIRouter(prefix="/companies", tags=["companies"])


def _row_to_company(row) -> Company:
    return Company(
        ticker=row["ticker"],
        name=row["name"],
        sector=row["sector"],
        exchange=row["exchange"],
        country=row["country"],
        fmp_symbol=row["fmp_symbol"],
        ir_url=row["ir_url"],
        custom_kpis=row["custom_kpis"] or [],
        overview=row["overview"],
        kpi_rationale=row["kpi_rationale"],
        added_by=row["added_by"],
        active=row["active"],
        created_at=row["created_at"],
    )


@router.get("", response_model=List[Company])
async def list_companies(db: AsyncSession = Depends(get_db)):
    """List all active companies."""
    result = await db.execute(
        text("SELECT * FROM companies WHERE active = true ORDER BY ticker ASC")
    )
    rows = result.mappings().all()
    return [_row_to_company(r) for r in rows]


@router.post("", response_model=Company, status_code=status.HTTP_201_CREATED)
async def create_company(payload: CompanyCreate, db: AsyncSession = Depends(get_db)):
    """Create a new company."""
    existing = await db.execute(
        text("SELECT ticker FROM companies WHERE ticker = :ticker"),
        {"ticker": payload.ticker.upper()},
    )
    if existing.scalar():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Company {payload.ticker} already exists.",
        )

    await db.execute(
        text(
            """
            INSERT INTO companies (ticker, name, sector, exchange, country, fmp_symbol,
                                   custom_kpis, added_by, active)
            VALUES (:ticker, :name, :sector, :exchange, :country, :fmp_symbol,
                    CAST(:custom_kpis AS jsonb), :added_by, :active)
            """
        ),
        {
            "ticker": payload.ticker.upper(),
            "name": payload.name,
            "sector": payload.sector,
            "exchange": payload.exchange,
            "country": payload.country,
            "fmp_symbol": payload.fmp_symbol,
            "custom_kpis": json.dumps(payload.custom_kpis or []),
            "added_by": payload.added_by,
            "active": payload.active,
        },
    )
    await db.commit()

    result = await db.execute(
        text("SELECT * FROM companies WHERE ticker = :ticker"),
        {"ticker": payload.ticker.upper()},
    )
    row = result.mappings().first()
    return _row_to_company(row)


@router.get("/{ticker}", response_model=Company)
async def get_company(ticker: str, db: AsyncSession = Depends(get_db)):
    """Get a single company by ticker."""
    result = await db.execute(
        text("SELECT * FROM companies WHERE ticker = :ticker"),
        {"ticker": ticker.upper()},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company {ticker} not found.",
        )
    return _row_to_company(row)


@router.put("/{ticker}", response_model=Company)
async def update_company(
    ticker: str,
    payload: CompanyUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a company record (KPI config, active status, etc.)."""
    result = await db.execute(
        text("SELECT * FROM companies WHERE ticker = :ticker"),
        {"ticker": ticker.upper()},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company {ticker} not found.",
        )

    updates = payload.model_dump(exclude_none=True)
    if not updates:
        return _row_to_company(row)

    set_clauses = []
    params: dict = {"ticker": ticker.upper()}
    for field, value in updates.items():
        if field == "custom_kpis":
            set_clauses.append(f"{field} = CAST(:{field} AS jsonb)")
            params[field] = json.dumps(value)
        else:
            set_clauses.append(f"{field} = :{field}")
            params[field] = value

    await db.execute(
        text(f"UPDATE companies SET {', '.join(set_clauses)} WHERE ticker = :ticker"),
        params,
    )
    await db.commit()

    result = await db.execute(
        text("SELECT * FROM companies WHERE ticker = :ticker"),
        {"ticker": ticker.upper()},
    )
    row = result.mappings().first()
    return _row_to_company(row)


# ---------------------------------------------------------------------------
# Alphie RAG integration
# ---------------------------------------------------------------------------

from services import alphie as alphie_svc

@router.get("/{ticker}/research")
async def company_research(ticker: str, db: AsyncSession = Depends(get_db)):
    """Query Alphie RAG for analyst research on this company."""
    result = await db.execute(
        text("SELECT name, sector FROM companies WHERE ticker = :t"),
        {"t": ticker.upper()},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Company not found")

    if not alphie_svc.is_configured():
        raise HTTPException(status_code=503, detail="Alphie RAG not configured")

    company_name = row["name"]
    sector = row["sector"] or ""

    try:
        data = await alphie_svc.query(
            question=f"What is the investment thesis, key risks, and recent performance for {company_name}?",
            focus_notes=f"Sector: {sector}. Focus on financials, competitive positioning, and analyst views.",
            k_chunks=12,
            max_tokens=800,
        )
        return {
            "ticker": ticker.upper(),
            "company": company_name,
            "answer": data.get("answer", ""),
            "sources": data.get("sources", []),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Alphie query failed: {e}")


@router.post("/{ticker}/ingest-to-rag")
async def ingest_company_docs(ticker: str, db: AsyncSession = Depends(get_db)):
    """Push all saved IR documents for this company into the Alphie RAG."""
    if not alphie_svc.is_configured():
        raise HTTPException(status_code=503, detail="Alphie RAG not configured")

    docs_result = await db.execute(
        text("SELECT source_url, title, fiscal_period FROM documents WHERE ticker = :t AND source_url IS NOT NULL"),
        {"t": ticker.upper()},
    )
    docs = docs_result.mappings().all()

    results = []
    for doc in docs:
        try:
            r = await alphie_svc.ingest_article(
                url=doc["source_url"],
                title=doc["title"],
                ticker_hint=ticker.upper(),
                tags=["earnings", doc["fiscal_period"] or ""],
            )
            results.append({"url": doc["source_url"], "status": "ok", **r})
        except Exception as e:
            results.append({"url": doc["source_url"], "status": "error", "error": str(e)})

    return {"ticker": ticker.upper(), "ingested": len([r for r in results if r["status"] == "ok"]), "results": results}
