from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field


# ---------------------------------------------------------------------------
# Company schemas
# ---------------------------------------------------------------------------

class CompanyBase(BaseModel):
    name: str
    sector: Optional[str] = None
    exchange: Optional[str] = None
    country: Optional[str] = None
    fmp_symbol: Optional[str] = None
    ir_url: Optional[str] = None
    custom_kpis: Optional[List[str]] = Field(default_factory=list)
    overview: Optional[str] = None
    kpi_rationale: Optional[str] = None
    added_by: Optional[str] = None
    active: bool = True


class CompanyCreate(CompanyBase):
    ticker: str


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    sector: Optional[str] = None
    exchange: Optional[str] = None
    country: Optional[str] = None
    fmp_symbol: Optional[str] = None
    ir_url: Optional[str] = None
    custom_kpis: Optional[List[str]] = None
    added_by: Optional[str] = None
    active: Optional[bool] = None


class Company(CompanyBase):
    ticker: str
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Earnings schemas
# ---------------------------------------------------------------------------

class EarningsBase(BaseModel):
    report_date: Optional[date] = None
    fiscal_period: str  # e.g. Q1-2026
    fiscal_year: Optional[int] = None
    fiscal_quarter: Optional[int] = None
    revenue_actual: Optional[float] = None
    revenue_est: Optional[float] = None
    revenue_surprise_pct: Optional[float] = None
    eps_actual: Optional[float] = None
    eps_est: Optional[float] = None
    eps_surprise_pct: Optional[float] = None
    ebit_est: Optional[float] = None
    net_income_est: Optional[float] = None
    analyst_estimates: Optional[Dict[str, Any]] = None
    beat_miss: Optional[str] = None  # 'beat', 'miss', 'in_line'
    guidance_tone: Optional[str] = None
    mgmt_tone: Optional[str] = None
    custom_kpis: Optional[Dict[str, Any]] = Field(default_factory=dict)
    pre_brief: Optional[Dict[str, Any]] = None
    post_brief: Optional[Dict[str, Any]] = None
    key_highlights: Optional[List[str]] = Field(default_factory=list)
    red_flags: Optional[List[str]] = Field(default_factory=list)
    transcript_available: bool = False
    data_source: str = "fmp"


class EarningsCreate(EarningsBase):
    ticker: str


class Earnings(EarningsBase):
    id: str
    ticker: str
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Watchlist schemas
# ---------------------------------------------------------------------------

class WatchlistBase(BaseModel):
    notify_pre_brief: bool = True
    notify_post_brief: bool = True
    alert_conditions: Optional[Dict[str, Any]] = None
    user_name: Optional[str] = None


class WatchlistCreate(WatchlistBase):
    user_email: str
    ticker: str


class WatchlistEntry(WatchlistBase):
    id: str
    user_email: str
    ticker: str
    created_at: Optional[datetime] = None
    company: Optional[Company] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Brief response schemas
# ---------------------------------------------------------------------------

class PreBriefResponse(BaseModel):
    ticker: str
    company_name: str
    fiscal_period: str
    report_date: Optional[date] = None
    revenue_est: Optional[float] = None
    eps_est: Optional[float] = None
    consensus_summary: Optional[str] = None
    key_watch_items: Optional[List[str]] = None
    prior_quarter_context: Optional[str] = None
    guidance_context: Optional[str] = None
    bull_case: Optional[str] = None
    bear_case: Optional[str] = None
    custom_kpis_est: Optional[Dict[str, Any]] = None
    generated_at: Optional[datetime] = None
    raw_brief: Optional[Dict[str, Any]] = None


class PostBriefResponse(BaseModel):
    ticker: str
    company_name: str
    fiscal_period: str
    report_date: Optional[date] = None
    revenue_actual: Optional[float] = None
    revenue_est: Optional[float] = None
    revenue_surprise_pct: Optional[float] = None
    eps_actual: Optional[float] = None
    eps_est: Optional[float] = None
    eps_surprise_pct: Optional[float] = None
    beat_miss: Optional[str] = None
    mgmt_tone: Optional[str] = None
    guidance_tone: Optional[str] = None
    key_highlights: Optional[List[str]] = None
    red_flags: Optional[List[str]] = None
    post_brief_prose: Optional[str] = None
    custom_kpis: Optional[Dict[str, Any]] = None
    generated_at: Optional[datetime] = None
    raw_brief: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Calendar schema
# ---------------------------------------------------------------------------

class CalendarEntry(BaseModel):
    ticker: str
    company_name: Optional[str] = None
    report_date: date
    fiscal_period: Optional[str] = None
    fiscal_year: Optional[int] = None
    fiscal_quarter: Optional[int] = None
    eps_est: Optional[float] = None
    revenue_est: Optional[float] = None
    time_of_day: Optional[str] = None  # 'BMO', 'AMC', 'TNS' (time not specified)
    is_watchlist: bool = False
    on_platform: bool = False


# ---------------------------------------------------------------------------
# Generic response
# ---------------------------------------------------------------------------

class MessageResponse(BaseModel):
    message: str
    detail: Optional[Any] = None
