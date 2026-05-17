"""
Synthesis router — trigger pre/post brief generation via Claude.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models.schemas import PostBriefResponse, PreBriefResponse
from services.claude import claude_service
from services.document_store import save_document
from services.fmp import fmp_client
from services.scraper import combine_doc_texts, gather_earnings_docs

router = APIRouter(prefix="/synthesise", tags=["synthesise"])


async def _get_company_or_404(ticker: str, db: AsyncSession) -> Dict[str, Any]:
    """Fetch company row or raise 404."""
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
    return dict(row)


def _derive_fiscal_period(item: Dict[str, Any]) -> str:
    """Derive Q1-2026 style fiscal period from FMP data."""
    # FMP surprises have 'date' field like '2025-01-30'
    # FMP income statements have 'period' like 'Q1' and 'calendarYear' or 'date'
    period_field = item.get("period") or ""
    year_field = item.get("calendarYear") or item.get("fiscalYear") or ""
    if period_field and year_field:
        return f"{period_field}-{year_field}"
    # Fall back to parsing date
    date_str = item.get("date", "")
    if date_str:
        try:
            d = date.fromisoformat(date_str[:10])
            q = (d.month - 1) // 3 + 1
            return f"Q{q}-{d.year}"
        except ValueError:
            pass
    return "Q?-????"


def _compute_beat_miss(eps_surp: Optional[float], rev_surp: Optional[float]) -> Optional[str]:
    if eps_surp is None:
        return None
    if eps_surp > 1.0:
        return "beat"
    elif eps_surp < -1.0:
        return "miss"
    return "in_line"


async def _upsert_earnings(
    db: AsyncSession,
    ticker: str,
    fiscal_period: str,
    data: Dict[str, Any],
) -> None:
    """Insert or update an earnings record."""
    # Check existing
    result = await db.execute(
        text("SELECT id FROM earnings WHERE ticker = :ticker AND fiscal_period = :fp"),
        {"ticker": ticker, "fp": fiscal_period},
    )
    existing_id = result.scalar()

    params: Dict[str, Any] = {"ticker": ticker, "fp": fiscal_period}
    for k, v in data.items():
        params[k] = v

    jsonb_fields = {"pre_brief", "post_brief", "custom_kpis", "key_highlights", "red_flags"}

    if existing_id:
        set_clauses = []
        for k in data:
            if k in jsonb_fields:
                set_clauses.append(f"{k} = CAST(:{k} AS jsonb)")
            else:
                set_clauses.append(f"{k} = :{k}")
        await db.execute(
            text(
                f"UPDATE earnings SET {', '.join(set_clauses)} WHERE ticker = :ticker AND fiscal_period = :fp"
            ),
            params,
        )
    else:
        cols = ["ticker", "fiscal_period"] + list(data.keys())
        vals = [":ticker", ":fp"] + [
            f"CAST(:{k} AS jsonb)" if k in jsonb_fields else f":{k}"
            for k in data.keys()
        ]
        await db.execute(
            text(f"INSERT INTO earnings ({', '.join(cols)}) VALUES ({', '.join(vals)})"),
            params,
        )
    await db.commit()


# ---------------------------------------------------------------------------
# POST /synthesise/pre/{ticker}
# ---------------------------------------------------------------------------

@router.post("/pre/{ticker}", response_model=PreBriefResponse)
async def synthesise_pre_brief(ticker: str, db: AsyncSession = Depends(get_db)):
    """
    Fetch FMP analyst estimates + historical data for the ticker,
    generate a pre-brief with Claude, store in DB, return result.
    """
    company = await _get_company_or_404(ticker, db)
    fmp_symbol = company.get("fmp_symbol") or ticker
    custom_kpis: List[str] = company.get("custom_kpis") or []

    # Fetch data from FMP
    try:
        bundle = await fmp_client.get_latest_earnings_data(fmp_symbol)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"FMP API error: {e}",
        )

    estimates = bundle.get("analyst_estimates", [])
    income = bundle.get("income_statements", [])

    # Latest estimate
    latest_est = estimates[0] if estimates else {}
    revenue_est = latest_est.get("estimatedRevenueAvg") or latest_est.get("estimatedRevenueLow")
    eps_est = latest_est.get("estimatedEpsAvg") or latest_est.get("estimatedEpsLow")

    # Report date from historical calendar
    report_date: Optional[str] = None
    try:
        hist_cal = await fmp_client.get_historical_calendar(fmp_symbol)
        for h in hist_cal:
            d_str = h.get("date")
            if d_str:
                try:
                    d = date.fromisoformat(d_str)
                    if d >= date.today():
                        report_date = d_str
                        break
                except ValueError:
                    pass
    except Exception:
        pass

    # Prior quarter data
    prior_quarter = income[1] if len(income) > 1 else (income[0] if income else None)
    prior_guidance_text: Optional[str] = None
    if income:
        latest_income = income[0]
        rev_str = latest_income.get("revenue")
        prior_guidance_text = (
            f"Last quarter revenue: {rev_str}, EPS: {latest_income.get('eps')}"
        )

    # Fiscal period for the upcoming report
    if latest_est:
        fiscal_period = _derive_fiscal_period(latest_est)
    elif income:
        # Derive next quarter
        fp = _derive_fiscal_period(income[0])
        try:
            parts = fp.split("-")
            q = int(parts[0][1])
            y = int(parts[1])
            q += 1
            if q > 4:
                q = 1
                y += 1
            fiscal_period = f"Q{q}-{y}"
        except Exception:
            fiscal_period = "Q?-????"
    else:
        fiscal_period = "Q?-????"

    # Generate pre-brief with Claude
    try:
        brief_data = await claude_service.generate_pre_brief(
            company=company["name"],
            report_date=report_date,
            fiscal_period=fiscal_period,
            revenue_est=revenue_est,
            eps_est=eps_est,
            prior_quarter=dict(prior_quarter) if prior_quarter else None,
            prior_guidance=prior_guidance_text,
            custom_kpi_list=custom_kpis,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Claude synthesis error: {e}",
        )

    # Persist
    db_data: Dict[str, Any] = {
        "report_date": report_date,
        "fiscal_year": int(fiscal_period.split("-")[1]) if "-" in fiscal_period else None,
        "fiscal_quarter": int(fiscal_period[1]) if fiscal_period.startswith("Q") else None,
        "revenue_est": revenue_est,
        "eps_est": eps_est,
        "pre_brief": json.dumps(brief_data),
        "data_source": "fmp",
    }
    await _upsert_earnings(db, ticker.upper(), fiscal_period, db_data)

    return PreBriefResponse(
        ticker=ticker.upper(),
        company_name=company["name"],
        fiscal_period=fiscal_period,
        report_date=date.fromisoformat(report_date) if report_date else None,
        revenue_est=revenue_est,
        eps_est=eps_est,
        consensus_summary=brief_data.get("consensus_summary"),
        key_watch_items=brief_data.get("key_watch_items"),
        prior_quarter_context=brief_data.get("prior_quarter_context"),
        guidance_context=brief_data.get("guidance_context"),
        bull_case=brief_data.get("bull_case"),
        bear_case=brief_data.get("bear_case"),
        custom_kpis_est=brief_data.get("custom_kpis_est"),
        generated_at=datetime.utcnow(),
        raw_brief=brief_data,
    )


# ---------------------------------------------------------------------------
# POST /synthesise/post/{ticker}
# ---------------------------------------------------------------------------

@router.post("/post/{ticker}", response_model=PostBriefResponse)
async def synthesise_post_brief(ticker: str, db: AsyncSession = Depends(get_db)):
    """
    Fetch FMP actuals + transcript for the ticker,
    generate a post-brief with Claude, store in DB, return result.
    """
    company = await _get_company_or_404(ticker, db)
    fmp_symbol = company.get("fmp_symbol") or ticker
    custom_kpis: List[str] = company.get("custom_kpis") or []

    # Fetch data from FMP
    try:
        bundle = await fmp_client.get_latest_earnings_data(fmp_symbol)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"FMP API error: {e}",
        )

    income = bundle.get("income_statements", [])
    surprises = bundle.get("earnings_surprises", [])
    estimates = bundle.get("analyst_estimates", [])

    latest_income = income[0] if income else {}
    latest_surprise = surprises[0] if surprises else {}
    latest_estimate = estimates[0] if estimates else {}

    # Actuals from income statement
    revenue_actual = latest_income.get("revenue")
    eps_actual = latest_surprise.get("actualEarningResult") or latest_income.get("eps")

    # Estimates
    revenue_est = latest_estimate.get("estimatedRevenueAvg") or latest_surprise.get("estimatedEarning")
    eps_est = latest_estimate.get("estimatedEpsAvg") or latest_surprise.get("estimatedEarning")

    # Surprises
    revenue_surprise_pct: Optional[float] = None
    if revenue_actual and revenue_est and revenue_est != 0:
        revenue_surprise_pct = round(((revenue_actual - revenue_est) / abs(revenue_est)) * 100, 2)

    eps_surprise_pct: Optional[float] = None
    if latest_surprise.get("actualEarningResult") is not None and latest_surprise.get("estimatedEarning") is not None:
        est = latest_surprise["estimatedEarning"]
        act = latest_surprise["actualEarningResult"]
        if est != 0:
            eps_surprise_pct = round(((act - est) / abs(est)) * 100, 2)

    # Fiscal period
    fiscal_period = _derive_fiscal_period(latest_income) if latest_income else _derive_fiscal_period(latest_surprise)

    # Prior quarters (exclude latest)
    prior_quarters = []
    for item in income[1:5]:
        prior_quarters.append({
            "period": _derive_fiscal_period(item),
            "revenue": item.get("revenue"),
            "eps": item.get("eps"),
            "grossProfitRatio": item.get("grossProfitRatio"),
            "netIncomeRatio": item.get("netIncomeRatio"),
        })

    # Transcript
    transcript_text: Optional[str] = None
    transcript_available = False
    try:
        transcript_text = await fmp_client.get_latest_transcript(fmp_symbol)
        transcript_available = bool(transcript_text)
    except Exception:
        pass

    # Generate post-brief with Claude
    try:
        brief_data = await claude_service.generate_post_brief(
            company=company["name"],
            fiscal_period=fiscal_period,
            revenue_actual=revenue_actual,
            revenue_est=revenue_est,
            revenue_surprise_pct=revenue_surprise_pct,
            eps_actual=eps_actual,
            eps_est=eps_est,
            eps_surprise_pct=eps_surprise_pct,
            prior_quarters=prior_quarters,
            transcript_chunks=transcript_text,
            custom_kpi_list=custom_kpis,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Claude synthesis error: {e}",
        )

    # Determine beat/miss
    beat_miss = brief_data.get("beat_miss") or _compute_beat_miss(eps_surprise_pct, revenue_surprise_pct)
    mgmt_tone = brief_data.get("mgmt_tone")
    guidance_tone = brief_data.get("guidance_tone")
    key_highlights = brief_data.get("key_highlights", [])
    red_flags = brief_data.get("red_flags", [])
    custom_kpi_values = brief_data.get("custom_kpis", {})

    # Report date
    report_date_str = latest_income.get("date") or latest_surprise.get("date")
    report_date: Optional[date] = None
    if report_date_str:
        try:
            report_date = date.fromisoformat(report_date_str[:10])
        except ValueError:
            pass

    # Persist
    db_data: Dict[str, Any] = {
        "report_date": report_date,
        "fiscal_year": int(fiscal_period.split("-")[1]) if "-" in fiscal_period and fiscal_period.split("-")[1].isdigit() else None,
        "fiscal_quarter": int(fiscal_period[1]) if fiscal_period.startswith("Q") and fiscal_period[1].isdigit() else None,
        "revenue_actual": revenue_actual,
        "revenue_est": revenue_est,
        "revenue_surprise_pct": revenue_surprise_pct,
        "eps_actual": eps_actual,
        "eps_est": eps_est,
        "eps_surprise_pct": eps_surprise_pct,
        "beat_miss": beat_miss,
        "guidance_tone": guidance_tone,
        "mgmt_tone": mgmt_tone,
        "custom_kpis": json.dumps(custom_kpi_values),
        "post_brief": json.dumps(brief_data),
        "key_highlights": json.dumps(key_highlights),
        "red_flags": json.dumps(red_flags),
        "transcript_available": transcript_available,
        "data_source": "fmp",
    }
    await _upsert_earnings(db, ticker.upper(), fiscal_period, db_data)

    return PostBriefResponse(
        ticker=ticker.upper(),
        company_name=company["name"],
        fiscal_period=fiscal_period,
        report_date=report_date,
        revenue_actual=revenue_actual,
        revenue_est=revenue_est,
        revenue_surprise_pct=revenue_surprise_pct,
        eps_actual=eps_actual,
        eps_est=eps_est,
        eps_surprise_pct=eps_surprise_pct,
        beat_miss=beat_miss,
        mgmt_tone=mgmt_tone,
        guidance_tone=guidance_tone,
        key_highlights=key_highlights,
        red_flags=red_flags,
        post_brief_prose=brief_data.get("post_brief"),
        custom_kpis=custom_kpi_values,
        generated_at=datetime.utcnow(),
        raw_brief=brief_data,
    )


# ---------------------------------------------------------------------------
# POST /synthesise/backfill/{ticker}?periods=4
# ---------------------------------------------------------------------------

@router.post("/backfill/{ticker}")
async def backfill_earnings(
    ticker: str,
    periods: int = 4,
    db: AsyncSession = Depends(get_db),
):
    """
    Fetch the last N quarters of income statements from FMP, run Claude
    post-brief synthesis on each, and store all results in the DB.
    Returns a summary of what was processed.
    """
    if periods < 1 or periods > 8:
        raise HTTPException(status_code=400, detail="periods must be between 1 and 8")

    company = await _get_company_or_404(ticker, db)
    fmp_symbol = company.get("fmp_symbol") or ticker
    custom_kpis: List[str] = company.get("custom_kpis") or []

    # --- Try FMP first ---
    fmp_ok = False
    income_statements: List[Dict[str, Any]] = []
    surprises: List[Dict[str, Any]] = []

    try:
        bundle = await fmp_client.get_latest_earnings_data(fmp_symbol)
        income_statements = bundle.get("income_statements", [])
        surprises = bundle.get("earnings_surprises", [])
        if income_statements:
            fmp_ok = True
    except Exception:
        pass

    # --- Scraper fallback: no FMP data → gather docs and scrape ---
    ir_url: Optional[str] = company.get("ir_url")  # optional manual override
    if not fmp_ok:
        from datetime import date as _date
        today = _date.today()
        # Use the most recently *completed* quarter (companies report 4-8 weeks after quarter end).
        # In months 1-4 → most recent complete quarter is Q4 of prior year.
        # In months 5-7 → Q1 of this year. 8-10 → Q2. 11+ → Q3.
        _q_map = {1: (4, -1), 2: (4, -1), 3: (4, -1), 4: (4, -1),
                  5: (1, 0), 6: (1, 0), 7: (1, 0),
                  8: (2, 0), 9: (2, 0), 10: (2, 0),
                  11: (3, 0), 12: (3, 0)}
        _q, _yr_offset = _q_map[today.month]
        search_period = f"Q{_q} {today.year + _yr_offset}"

        docs = await gather_earnings_docs(
            company=company["name"],
            fiscal_period=search_period,
            ir_url_override=ir_url,
            max_docs=4,
        )
        if not docs:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"No documents found for {company['name']}. "
                    "Set ir_url via PUT /companies/{ticker} or add BRAVE_SEARCH_API_KEY."
                ),
            )

        # Save each document to disk + DB
        for doc in docs:
            try:
                await save_document(db, ticker.upper(), None, doc)
            except Exception:
                pass

        # Combine all extracted texts for Claude
        combined_text = combine_doc_texts(docs)
        fiscal_period = f"Q?-{today.year}"

        try:
            brief_data = await claude_service.extract_from_ir_page(
                company=company["name"],
                fiscal_period=fiscal_period,
                page_text=combined_text,
                custom_kpi_list=custom_kpis,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Claude IR extraction error: {e}")

        beat_miss = brief_data.get("beat_miss")
        fiscal_period = brief_data.get("fiscal_period") or fiscal_period or "UNKNOWN"
        revenue_actual = brief_data.get("revenue_actual")
        eps_actual = brief_data.get("eps_actual")

        # Back-fill fiscal_period on the saved documents
        for doc in docs:
            try:
                await db.execute(
                    text(
                        "UPDATE documents SET fiscal_period = :fp "
                        "WHERE ticker = :ticker AND source_url = :url AND fiscal_period IS NULL"
                    ),
                    {"fp": fiscal_period, "ticker": ticker.upper(), "url": doc.url},
                )
            except Exception:
                pass
        await db.commit()

        db_data: Dict[str, Any] = {
            "report_date": today,
            "fiscal_year": int(fiscal_period.split("-")[1]) if fiscal_period and "-" in fiscal_period and fiscal_period.split("-")[1].isdigit() else None,
            "fiscal_quarter": int(fiscal_period[1]) if fiscal_period and fiscal_period.startswith("Q") and fiscal_period[1].isdigit() else None,
            "revenue_actual": revenue_actual,
            "revenue_est": brief_data.get("revenue_est"),
            "revenue_surprise_pct": brief_data.get("revenue_surprise_pct"),
            "eps_actual": eps_actual,
            "eps_est": brief_data.get("eps_est"),
            "eps_surprise_pct": brief_data.get("eps_surprise_pct"),
            "beat_miss": beat_miss,
            "guidance_tone": brief_data.get("guidance_tone"),
            "mgmt_tone": brief_data.get("mgmt_tone"),
            "custom_kpis": json.dumps(brief_data.get("custom_kpis", {})),
            "post_brief": json.dumps(brief_data),
            "key_highlights": json.dumps(brief_data.get("key_highlights", [])),
            "red_flags": json.dumps(brief_data.get("red_flags", [])),
            "transcript_available": False,
            "data_source": "ir_scrape",
        }
        await _upsert_earnings(db, ticker.upper(), fiscal_period, db_data)

        return {
            "ticker": ticker.upper(),
            "company": company["name"],
            "data_source": "ir_scrape",
            "source_urls": [d.url for d in docs],
            "docs_gathered": len(docs),
            "periods_requested": periods,
            "periods_processed": 1,
            "results": [{
                "fiscal_period": fiscal_period,
                "report_date": str(today),
                "status": "ok",
                "beat_miss": beat_miss,
                "mgmt_tone": brief_data.get("mgmt_tone"),
                "guidance_tone": brief_data.get("guidance_tone"),
                "transcript_available": False,
                "key_highlights": brief_data.get("key_highlights", []),
                "post_brief": brief_data.get("post_brief"),
            }],
        }

    if not income_statements:
        raise HTTPException(status_code=404, detail=f"No income statement data found for {ticker} ({fmp_symbol})")

    # Build a quick lookup: date string → surprise row
    surprise_by_date: Dict[str, Dict] = {s.get("date", ""): s for s in surprises}

    results = []
    quarters_to_process = income_statements[:periods]

    for i, income in enumerate(quarters_to_process):
        fiscal_period = _derive_fiscal_period(income)

        # Match surprise data by date
        inc_date = income.get("date", "")
        surprise = surprise_by_date.get(inc_date, {})

        revenue_actual = income.get("revenue")
        eps_actual = surprise.get("actualEarningResult") or income.get("eps")
        eps_est = surprise.get("estimatedEarning")
        revenue_est = None  # FMP doesn't give historical revenue estimates in surprises endpoint

        eps_surprise_pct: Optional[float] = None
        if eps_actual is not None and eps_est is not None and eps_est != 0:
            eps_surprise_pct = round(((eps_actual - eps_est) / abs(eps_est)) * 100, 2)

        revenue_surprise_pct: Optional[float] = None

        # Prior quarters = the ones after this index in the list
        prior_quarters = []
        for pq in income_statements[i + 1: i + 5]:
            prior_quarters.append({
                "period": _derive_fiscal_period(pq),
                "revenue": pq.get("revenue"),
                "eps": pq.get("eps"),
                "grossProfitRatio": pq.get("grossProfitRatio"),
                "netIncomeRatio": pq.get("netIncomeRatio"),
            })

        # Fetch transcript for this specific quarter/year
        transcript_text: Optional[str] = None
        transcript_available = False
        try:
            fp_parts = fiscal_period.split("-")
            if len(fp_parts) == 2 and fp_parts[0].startswith("Q"):
                q_num = int(fp_parts[0][1])
                y_num = int(fp_parts[1])
                transcript_list = await fmp_client.get_transcript(fmp_symbol, q_num, y_num)
                if transcript_list and transcript_list[0].get("content"):
                    transcript_text = transcript_list[0]["content"]
                    transcript_available = True
        except Exception:
            pass

        # Run Claude synthesis
        try:
            brief_data = await claude_service.generate_post_brief(
                company=company["name"],
                fiscal_period=fiscal_period,
                revenue_actual=revenue_actual,
                revenue_est=revenue_est,
                revenue_surprise_pct=revenue_surprise_pct,
                eps_actual=eps_actual,
                eps_est=eps_est,
                eps_surprise_pct=eps_surprise_pct,
                prior_quarters=prior_quarters,
                transcript_chunks=transcript_text,
                custom_kpi_list=custom_kpis,
            )
        except Exception as e:
            results.append({
                "fiscal_period": fiscal_period,
                "status": "error",
                "error": str(e),
            })
            continue

        beat_miss = brief_data.get("beat_miss") or _compute_beat_miss(eps_surprise_pct, revenue_surprise_pct)

        report_date: Optional[date] = None
        if inc_date:
            try:
                report_date = date.fromisoformat(inc_date[:10])
            except ValueError:
                pass

        db_data: Dict[str, Any] = {
            "report_date": report_date,
            "fiscal_year": int(fp_parts[1]) if len(fp_parts) == 2 and fp_parts[1].isdigit() else None,
            "fiscal_quarter": int(fp_parts[0][1]) if fp_parts[0].startswith("Q") and fp_parts[0][1].isdigit() else None,
            "revenue_actual": revenue_actual,
            "revenue_est": revenue_est,
            "revenue_surprise_pct": revenue_surprise_pct,
            "eps_actual": eps_actual,
            "eps_est": eps_est,
            "eps_surprise_pct": eps_surprise_pct,
            "beat_miss": beat_miss,
            "guidance_tone": brief_data.get("guidance_tone"),
            "mgmt_tone": brief_data.get("mgmt_tone"),
            "custom_kpis": json.dumps(brief_data.get("custom_kpis", {})),
            "post_brief": json.dumps(brief_data),
            "key_highlights": json.dumps(brief_data.get("key_highlights", [])),
            "red_flags": json.dumps(brief_data.get("red_flags", [])),
            "transcript_available": transcript_available,
            "data_source": "fmp",
        }
        await _upsert_earnings(db, ticker.upper(), fiscal_period, db_data)

        results.append({
            "fiscal_period": fiscal_period,
            "report_date": str(report_date) if report_date else None,
            "status": "ok",
            "beat_miss": beat_miss,
            "mgmt_tone": brief_data.get("mgmt_tone"),
            "guidance_tone": brief_data.get("guidance_tone"),
            "transcript_available": transcript_available,
            "key_highlights": brief_data.get("key_highlights", []),
            "post_brief": brief_data.get("post_brief"),
        })

    return {
        "ticker": ticker.upper(),
        "company": company["name"],
        "periods_requested": periods,
        "periods_processed": len([r for r in results if r["status"] == "ok"]),
        "results": results,
    }


# ---------------------------------------------------------------------------
# POST /synthesise/from-docs/{ticker}/{period}
# Re-run Claude synthesis using already-saved documents (no re-download)
# ---------------------------------------------------------------------------

@router.post("/from-docs/{ticker}/{period}")
async def synthesise_from_saved_docs(
    ticker: str,
    period: str,
    db: AsyncSession = Depends(get_db),
):
    """Re-synthesize a period using documents already stored in the DB."""
    company = await _get_company_or_404(ticker, db)
    custom_kpis: List[str] = company.get("custom_kpis") or []

    result = await db.execute(
        text(
            "SELECT doc_type, title, source_url, extracted_text FROM documents "
            "WHERE ticker = :ticker AND fiscal_period = :fp AND extracted_text IS NOT NULL "
            "ORDER BY created_at ASC"
        ),
        {"ticker": ticker.upper(), "fp": period},
    )
    rows = result.mappings().all()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No saved documents for {ticker} {period}")

    from services.scraper import EarningsDoc
    fake_docs = [
        EarningsDoc(
            url=r["source_url"],
            doc_type=r["doc_type"],
            title=r["title"] or "",
            mime_type="text/plain",
            content_bytes=b"",
            extracted_text=r["extracted_text"],
        )
        for r in rows
    ]
    combined_text = combine_doc_texts(fake_docs)

    try:
        brief_data = await claude_service.extract_from_ir_page(
            company=company["name"],
            fiscal_period=period,
            page_text=combined_text,
            custom_kpi_list=custom_kpis,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Claude synthesis error: {e}")

    fiscal_period = brief_data.get("fiscal_period") or period

    db_data: Dict[str, Any] = {
        "report_date": date.today(),
        "fiscal_year": int(fiscal_period.split("-")[1]) if fiscal_period and "-" in fiscal_period and fiscal_period.split("-")[1].isdigit() else None,
        "fiscal_quarter": int(fiscal_period[1]) if fiscal_period and fiscal_period.startswith("Q") and fiscal_period[1].isdigit() else None,
        "revenue_actual": brief_data.get("revenue_actual"),
        "revenue_est": brief_data.get("revenue_est"),
        "revenue_surprise_pct": brief_data.get("revenue_surprise_pct"),
        "eps_actual": brief_data.get("eps_actual"),
        "eps_est": brief_data.get("eps_est"),
        "eps_surprise_pct": brief_data.get("eps_surprise_pct"),
        "beat_miss": brief_data.get("beat_miss"),
        "guidance_tone": brief_data.get("guidance_tone"),
        "mgmt_tone": brief_data.get("mgmt_tone"),
        "custom_kpis": json.dumps(brief_data.get("custom_kpis", {})),
        "post_brief": json.dumps(brief_data),
        "key_highlights": json.dumps(brief_data.get("key_highlights", [])),
        "red_flags": json.dumps(brief_data.get("red_flags", [])),
        "transcript_available": False,
        "data_source": "ir_scrape",
    }
    await _upsert_earnings(db, ticker.upper(), fiscal_period, db_data)

    return {
        "ticker": ticker.upper(),
        "fiscal_period": fiscal_period,
        "docs_used": len(rows),
        "chars_sent_to_claude": len(combined_text),
        "brief_data": brief_data,
    }
