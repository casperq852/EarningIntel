"""
Synthesis router — generate pre/post briefs from data already in the DB.

All quantitative data comes from the Bloomberg model upload.
All qualitative context comes from the onboarding agent.
Claude's job here is to synthesise and write analyst-grade prose.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from decimal import Decimal

from db import get_db
from models.schemas import PostBriefResponse, PreBriefResponse
from services.claude import claude_service


def _to_float(v: Any) -> Any:
    """Convert Decimal to float, leave everything else unchanged."""
    if isinstance(v, Decimal):
        return float(v)
    return v

router = APIRouter(prefix="/synthesise", tags=["synthesise"])


async def _get_company_or_404(ticker: str, db: AsyncSession) -> Dict[str, Any]:
    result = await db.execute(
        text("SELECT * FROM companies WHERE ticker = :ticker"),
        {"ticker": ticker.upper()},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Company {ticker} not found.")
    return dict(row)


async def _get_earnings_history(ticker: str, db: AsyncSession, limit: int = 8) -> List[Dict[str, Any]]:
    result = await db.execute(
        text("""
            SELECT * FROM earnings WHERE ticker = :t
            ORDER BY fiscal_year DESC NULLS LAST, fiscal_quarter DESC NULLS LAST
            LIMIT :lim
        """),
        {"t": ticker.upper(), "lim": limit},
    )
    rows = []
    for r in result.mappings().all():
        row = {k: _to_float(v) for k, v in r.items()}
        rows.append(row)
    return rows


def _fmt(v: Optional[float], suffix: str = "m") -> str:
    if v is None:
        return "n/a"
    if suffix == "m":
        return f"{v:,.0f}m"
    return f"{v:.2f}"


async def _upsert_earnings(db: AsyncSession, ticker: str, fiscal_period: str, data: Dict[str, Any]) -> None:
    result = await db.execute(
        text("SELECT id FROM earnings WHERE ticker = :t AND fiscal_period = :fp"),
        {"t": ticker, "fp": fiscal_period},
    )
    existing = result.scalar()
    jsonb_fields = {"pre_brief", "post_brief", "custom_kpis", "key_highlights", "red_flags"}
    params = {"t": ticker, "fp": fiscal_period, **data}
    if existing:
        clauses = [
            f"{k} = CAST(:{k} AS jsonb)" if k in jsonb_fields else f"{k} = :{k}"
            for k in data
        ]
        await db.execute(
            text(f"UPDATE earnings SET {', '.join(clauses)} WHERE ticker = :t AND fiscal_period = :fp"),
            params,
        )
    else:
        cols = ["ticker", "fiscal_period"] + list(data.keys())
        vals = [":t", ":fp"] + [
            f"CAST(:{k} AS jsonb)" if k in jsonb_fields else f":{k}" for k in data.keys()
        ]
        await db.execute(
            text(f"INSERT INTO earnings ({', '.join(cols)}) VALUES ({', '.join(vals)})"),
            params,
        )
    await db.commit()


# ---------------------------------------------------------------------------
# POST /synthesise/post/{ticker}
# ---------------------------------------------------------------------------

@router.post("/post/{ticker}", response_model=PostBriefResponse)
async def synthesise_post_brief(ticker: str, db: AsyncSession = Depends(get_db)):
    """
    Generate a post-earnings brief using data already in the DB:
    - Quantitative: revenue_actual, eps_actual, ebit/ebitda from post_brief JSONB (Bloomberg upload)
    - Qualitative: beat_miss, mgmt_tone, guidance_tone, key_highlights (onboarding agent)
    Claude synthesises a polished analyst brief from these inputs.
    """
    company = await _get_company_or_404(ticker, db)
    custom_kpis: List[str] = company.get("custom_kpis") or []
    history = await _get_earnings_history(ticker, db, limit=8)

    if not history:
        raise HTTPException(
            status_code=404,
            detail="No earnings data found. Upload a Bloomberg model or run the onboarding agent first.",
        )

    today = date.today()

    # Find the most recently reported period (has actuals or qualitative data)
    target = None
    for e in history:
        has_actuals = e.get("revenue_actual") is not None or e.get("eps_actual") is not None
        pb = e.get("post_brief") or {}
        has_qualitative = bool(pb.get("mgmt_tone") or pb.get("beat_miss") or pb.get("key_highlights"))
        rd = e.get("report_date")
        is_past = rd is None or (isinstance(rd, date) and rd <= today)
        if (has_actuals or has_qualitative) and is_past:
            target = e
            break

    if not target:
        raise HTTPException(
            status_code=404,
            detail="No reported earnings found. Upload a Bloomberg model to populate actuals.",
        )

    fiscal_period = target["fiscal_period"]
    pb = target.get("post_brief") or {}
    revenue_actual = target.get("revenue_actual")
    eps_actual = target.get("eps_actual")
    revenue_est = target.get("revenue_est")
    eps_est = target.get("eps_est")

    # Compute surprise %
    revenue_surprise_pct: Optional[float] = None
    if revenue_actual and revenue_est and revenue_est != 0:
        revenue_surprise_pct = round(((revenue_actual - revenue_est) / abs(revenue_est)) * 100, 2)
    eps_surprise_pct: Optional[float] = None
    if eps_actual is not None and eps_est is not None and eps_est != 0:
        eps_surprise_pct = round(((eps_actual - eps_est) / abs(eps_est)) * 100, 2)

    # Prior quarters context (skip target)
    prior_quarters = []
    for e in history[1:5]:
        prior_quarters.append({
            "period": e.get("fiscal_period"),
            "revenue": e.get("revenue_actual"),
            "eps": e.get("eps_actual"),
            "ebit": (e.get("post_brief") or {}).get("ebit"),
            "ebit_margin_pct": (e.get("post_brief") or {}).get("ebit_margin_pct"),
        })

    # Build a context block for Claude from what we already know
    existing_context = {
        "beat_miss": pb.get("beat_miss") or target.get("beat_miss"),
        "mgmt_tone": pb.get("mgmt_tone") or target.get("mgmt_tone"),
        "guidance_tone": pb.get("guidance_tone") or target.get("guidance_tone"),
        "guidance_detail": pb.get("guidance_detail"),
        "ebit": pb.get("ebit"),
        "ebitda": pb.get("ebitda"),
        "ebit_margin_pct": pb.get("ebit_margin_pct"),
        "ebitda_margin_pct": pb.get("ebitda_margin_pct"),
        "net_income": pb.get("net_income"),
        "free_cash_flow": pb.get("free_cash_flow"),
        "existing_highlights": target.get("key_highlights") or [],
        "existing_red_flags": target.get("red_flags") or [],
        "existing_summary": pb.get("post_brief") or pb.get("latest_earnings_summary"),
        "segment_breakdown": pb.get("segment_breakdown"),
    }

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
            transcript_chunks=None,
            custom_kpi_list=custom_kpis,
            existing_context=existing_context,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Claude synthesis error: {e}")

    beat_miss = brief_data.get("beat_miss") or existing_context["beat_miss"]
    mgmt_tone = brief_data.get("mgmt_tone") or existing_context["mgmt_tone"]
    guidance_tone = brief_data.get("guidance_tone") or existing_context["guidance_tone"]
    key_highlights = brief_data.get("key_highlights") or existing_context["existing_highlights"] or []
    red_flags = brief_data.get("red_flags") or existing_context["existing_red_flags"] or []

    # Merge new brief into existing post_brief JSONB
    merged_pb = dict(pb)
    merged_pb.update({k: v for k, v in {
        "beat_miss": beat_miss,
        "mgmt_tone": mgmt_tone,
        "guidance_tone": guidance_tone,
        "post_brief": brief_data.get("post_brief"),
    }.items() if v is not None})

    db_data: Dict[str, Any] = {
        "beat_miss": beat_miss,
        "guidance_tone": guidance_tone,
        "mgmt_tone": mgmt_tone,
        "post_brief": json.dumps(merged_pb),
        "key_highlights": json.dumps(key_highlights),
        "red_flags": json.dumps(red_flags),
        "data_source": "claude_synthesis",
    }
    await _upsert_earnings(db, ticker.upper(), fiscal_period, db_data)

    report_date = target.get("report_date")

    return PostBriefResponse(
        ticker=ticker.upper(),
        company_name=company["name"],
        fiscal_period=fiscal_period,
        report_date=report_date if isinstance(report_date, date) else None,
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
        custom_kpis=brief_data.get("custom_kpis", {}),
        generated_at=datetime.utcnow(),
        raw_brief=brief_data,
    )


# ---------------------------------------------------------------------------
# POST /synthesise/pre/{ticker}
# ---------------------------------------------------------------------------

@router.post("/pre/{ticker}", response_model=PreBriefResponse)
async def synthesise_pre_brief(ticker: str, db: AsyncSession = Depends(get_db)):
    """
    Generate a pre-earnings brief from DB data:
    - Estimates: revenue_est, eps_est, ebit_est from Bloomberg upload
    - Prior quarter actuals from DB history
    Claude writes the watch items, bull/bear case, and consensus narrative.
    """
    company = await _get_company_or_404(ticker, db)
    custom_kpis: List[str] = company.get("custom_kpis") or []
    history = await _get_earnings_history(ticker, db, limit=8)

    today = date.today()

    # Find the next (most upcoming) earnings period: has estimates or a future report_date
    target = None
    for e in history:
        rd = e.get("report_date")
        has_est = e.get("revenue_est") is not None or e.get("eps_est") is not None
        is_future = rd is not None and isinstance(rd, date) and rd > today
        if has_est or is_future:
            target = e
            break

    # Fallback: use most recent period even if past (still useful to brief on)
    if not target and history:
        target = history[0]

    if not target:
        raise HTTPException(
            status_code=404,
            detail="No earnings data found. Upload a Bloomberg model or run the onboarding agent first.",
        )

    fiscal_period = target["fiscal_period"]
    revenue_est = target.get("revenue_est")
    eps_est = target.get("eps_est")
    ebit_est = target.get("ebit_est")
    report_date = target.get("report_date")

    # Prior actuals for context
    prior_quarters = []
    for e in history:
        if e.get("fiscal_period") == fiscal_period:
            continue
        if e.get("revenue_actual") is None and e.get("eps_actual") is None:
            continue
        pb = e.get("post_brief") or {}
        prior_quarters.append({
            "period": e.get("fiscal_period"),
            "revenue": e.get("revenue_actual"),
            "eps": e.get("eps_actual"),
            "ebit": pb.get("ebit"),
            "ebit_margin_pct": pb.get("ebit_margin_pct"),
            "beat_miss": e.get("beat_miss"),
            "guidance_tone": e.get("guidance_tone"),
        })
        if len(prior_quarters) >= 4:
            break

    # Last quarter guidance detail for context
    prior_guidance: Optional[str] = None
    if prior_quarters:
        pq = prior_quarters[0]
        pb0 = (history[1].get("post_brief") or {}) if len(history) > 1 else {}
        prior_guidance = pb0.get("guidance_detail") or pb0.get("post_brief")

    try:
        brief_data = await claude_service.generate_pre_brief(
            company=company["name"],
            report_date=report_date.isoformat() if isinstance(report_date, date) else None,
            fiscal_period=fiscal_period,
            revenue_est=revenue_est,
            eps_est=eps_est,
            prior_quarter=prior_quarters[0] if prior_quarters else None,
            prior_guidance=prior_guidance,
            custom_kpi_list=custom_kpis,
            ebit_est=ebit_est,
            company_overview=company.get("overview"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Claude synthesis error: {e}")

    db_data: Dict[str, Any] = {
        "revenue_est": revenue_est,
        "eps_est": eps_est,
        "pre_brief": json.dumps(brief_data),
        "data_source": "claude_synthesis",
    }
    if isinstance(report_date, date):
        db_data["report_date"] = report_date
    await _upsert_earnings(db, ticker.upper(), fiscal_period, db_data)

    return PreBriefResponse(
        ticker=ticker.upper(),
        company_name=company["name"],
        fiscal_period=fiscal_period,
        report_date=report_date if isinstance(report_date, date) else None,
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
# POST /synthesise/from-docs/{ticker}/{period}
# Re-run Claude synthesis using already-saved IR documents
# ---------------------------------------------------------------------------

@router.post("/from-docs/{ticker}/{period}")
async def synthesise_from_saved_docs(
    ticker: str,
    period: str,
    db: AsyncSession = Depends(get_db),
):
    """Re-synthesize a period using documents already stored in the DB."""
    from services.document_store import save_document
    from services.scraper import combine_doc_texts, EarningsDoc

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
        "beat_miss": brief_data.get("beat_miss"),
        "guidance_tone": brief_data.get("guidance_tone"),
        "mgmt_tone": brief_data.get("mgmt_tone"),
        "custom_kpis": json.dumps(brief_data.get("custom_kpis", {})),
        "post_brief": json.dumps(brief_data),
        "key_highlights": json.dumps(brief_data.get("key_highlights", [])),
        "red_flags": json.dumps(brief_data.get("red_flags", [])),
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
