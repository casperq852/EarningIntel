"""
Companies router.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models.schemas import Company, CompanyCreate, CompanyUpdate, MessageResponse
from routers.settings import get_settings_from_db

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


# ---------------------------------------------------------------------------
# Bloomberg model upload
# ---------------------------------------------------------------------------

@router.post("/{ticker}/upload-model")
async def upload_analyst_model(
    ticker: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a Bloomberg aggregate analyst model (.xlsx).
    Historical actuals → saved to revenue_actual, eps_actual, post_brief (EBIT/net income).
    Forward consensus estimates → saved to revenue_est, eps_est, ebit_est, net_income_est.
    Both populate analyst_estimates JSONB for the chat panel.
    """
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Please upload an .xlsx file exported from Bloomberg.")

    result = await db.execute(
        text("SELECT name FROM companies WHERE ticker = :t"),
        {"t": ticker.upper()},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Company {ticker} not found")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 10 MB)")

    cfg = await get_settings_from_db(db)
    from services.model_parser import parse_bloomberg_model

    try:
        parsed = await parse_bloomberg_model(
            content,
            file.filename,
            model=cfg["parser_model"],
            provider=cfg["parser_provider"],
            openrouter_api_key=cfg.get("openrouter_api_key"),
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not parse file: {e}")

    quarters = parsed.get("quarters") or []
    currency = parsed.get("currency", "")
    saved: List[Dict[str, Any]] = []
    skipped: List[str] = []

    for q in quarters:
        fp = q.get("fiscal_period")
        if not fp:
            continue

        is_estimate = q.get("is_estimate", True)
        segment_breakdown = q.get("segment_breakdown") or {}

        # Derive fiscal year/quarter
        fiscal_year: Optional[int] = None
        fiscal_quarter: Optional[int] = None
        try:
            parts = fp.split("-")
            fiscal_year = int(parts[1])
            fiscal_quarter = int(parts[0][1])
        except Exception:
            pass

        # Fetch existing row so we can merge safely
        existing_result = await db.execute(
            text("SELECT id, post_brief, revenue_actual FROM earnings WHERE ticker = :t AND fiscal_period = :fp"),
            {"t": ticker.upper(), "fp": fp},
        )
        existing = existing_result.mappings().first()

        # Build merged post_brief — preserve existing qualitative fields
        existing_pb: Dict[str, Any] = {}
        if existing and existing["post_brief"]:
            try:
                existing_pb = existing["post_brief"] if isinstance(existing["post_brief"], dict) else json.loads(existing["post_brief"])
            except Exception:
                pass

        # Full analyst_estimates blob for chat context
        analyst_estimates_blob = {
            "source": "bloomberg",
            "currency": currency,
            "is_estimate": is_estimate,
            "analyst_count": q.get("analyst_count"),
            "ebit_margin_pct": q.get("ebit_margin_pct"),
            "ebitda_margin_pct": q.get("ebitda_margin_pct"),
            **(q.get("extra") or {}),
        }

        if not is_estimate:
            # Historical actual — populate revenue_actual, eps_actual, and financials in post_brief
            existing_pb.update({k: v for k, v in {
                "ebit": q.get("ebit"),
                "ebitda": q.get("ebitda"),
                "ebit_margin_pct": q.get("ebit_margin_pct"),
                "ebitda_margin_pct": q.get("ebitda_margin_pct"),
                "net_income": q.get("net_income"),
                "segment_breakdown": segment_breakdown if segment_breakdown else existing_pb.get("segment_breakdown"),
            }.items() if v is not None})

            upsert_params: Dict[str, Any] = {
                "t": ticker.upper(),
                "fp": fp,
                "revenue_actual": q.get("revenue"),
                "eps_actual": q.get("eps"),
                "post_brief": json.dumps(existing_pb),
                "analyst_estimates": json.dumps(analyst_estimates_blob),
                "data_source": "bloomberg_model",
                "fy": fiscal_year,
                "fq": fiscal_quarter,
            }
            await db.execute(
                text("""
                    INSERT INTO earnings
                      (ticker, fiscal_period, revenue_actual, eps_actual, post_brief,
                       analyst_estimates, data_source, fiscal_year, fiscal_quarter,
                       key_highlights, red_flags, custom_kpis)
                    VALUES
                      (:t, :fp, :revenue_actual, :eps_actual, CAST(:post_brief AS jsonb),
                       CAST(:analyst_estimates AS jsonb), :data_source, :fy, :fq,
                       '[]'::jsonb, '[]'::jsonb, '{}'::jsonb)
                    ON CONFLICT (ticker, fiscal_period) DO UPDATE SET
                      revenue_actual = COALESCE(EXCLUDED.revenue_actual, earnings.revenue_actual),
                      eps_actual     = COALESCE(EXCLUDED.eps_actual, earnings.eps_actual),
                      post_brief     = CAST(:post_brief AS jsonb),
                      analyst_estimates = CAST(:analyst_estimates AS jsonb),
                      data_source    = EXCLUDED.data_source,
                      fiscal_year    = COALESCE(EXCLUDED.fiscal_year, earnings.fiscal_year),
                      fiscal_quarter = COALESCE(EXCLUDED.fiscal_quarter, earnings.fiscal_quarter)
                """),
                upsert_params,
            )

        else:
            # Forward estimate — populate *_est fields
            upsert_params = {
                "t": ticker.upper(),
                "fp": fp,
                "revenue_est": q.get("revenue"),
                "eps_est": q.get("eps"),
                "ebit_est": q.get("ebit"),
                "net_income_est": q.get("net_income"),
                "analyst_estimates": json.dumps(analyst_estimates_blob),
                "data_source": "bloomberg_model",
                "fy": fiscal_year,
                "fq": fiscal_quarter,
            }
            await db.execute(
                text("""
                    INSERT INTO earnings
                      (ticker, fiscal_period, revenue_est, eps_est, ebit_est, net_income_est,
                       analyst_estimates, data_source, fiscal_year, fiscal_quarter,
                       key_highlights, red_flags, custom_kpis)
                    VALUES
                      (:t, :fp, :revenue_est, :eps_est, :ebit_est, :net_income_est,
                       CAST(:analyst_estimates AS jsonb), :data_source, :fy, :fq,
                       '[]'::jsonb, '[]'::jsonb, '{}'::jsonb)
                    ON CONFLICT (ticker, fiscal_period) DO UPDATE SET
                      revenue_est    = COALESCE(EXCLUDED.revenue_est, earnings.revenue_est),
                      eps_est        = COALESCE(EXCLUDED.eps_est, earnings.eps_est),
                      ebit_est       = COALESCE(EXCLUDED.ebit_est, earnings.ebit_est),
                      net_income_est = COALESCE(EXCLUDED.net_income_est, earnings.net_income_est),
                      analyst_estimates = CAST(:analyst_estimates AS jsonb),
                      data_source    = EXCLUDED.data_source,
                      fiscal_year    = COALESCE(EXCLUDED.fiscal_year, earnings.fiscal_year),
                      fiscal_quarter = COALESCE(EXCLUDED.fiscal_quarter, earnings.fiscal_quarter)
                """),
                upsert_params,
            )

        saved.append({
            "fiscal_period": fp,
            "is_estimate": is_estimate,
            "revenue": q.get("revenue"),
            "ebit": q.get("ebit"),
            "eps": q.get("eps"),
            "has_segments": bool(segment_breakdown),
        })

    await db.commit()

    actuals_saved = [s for s in saved if not s["is_estimate"]]
    estimates_saved = [s for s in saved if s["is_estimate"]]

    return {
        "ticker": ticker.upper(),
        "company": row["name"],
        "currency": currency,
        "parsed_periods": len(quarters),
        "actuals_saved": len(actuals_saved),
        "estimates_saved": len(estimates_saved),
        "saved": saved,
        "skipped": skipped,
    }
