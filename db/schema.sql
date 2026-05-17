-- Earnings Intelligence Platform Schema
-- PostgreSQL 16

-- Create n8n database if it doesn't exist (handled by init script separately)
-- The main database is earningintel

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Companies table
CREATE TABLE IF NOT EXISTS companies (
    ticker          VARCHAR(20) PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    sector          VARCHAR(100),
    exchange        VARCHAR(20),
    country         VARCHAR(10),
    fmp_symbol      VARCHAR(30),
    ir_url          TEXT,
    custom_kpis     JSONB DEFAULT '[]'::jsonb,
    overview        TEXT,
    kpi_rationale   TEXT,
    added_by        VARCHAR(255),
    active          BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_companies_sector ON companies(sector);
CREATE INDEX IF NOT EXISTS idx_companies_country ON companies(country);
CREATE INDEX IF NOT EXISTS idx_companies_active ON companies(active);

-- Earnings table
CREATE TABLE IF NOT EXISTS earnings (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticker                  VARCHAR(20) NOT NULL REFERENCES companies(ticker) ON DELETE CASCADE,
    report_date             DATE,
    fiscal_period           VARCHAR(20) NOT NULL,   -- e.g. Q1-2026
    fiscal_year             INTEGER,
    fiscal_quarter          INTEGER,
    revenue_actual          NUMERIC(20, 4),
    revenue_est             NUMERIC(20, 4),
    revenue_surprise_pct    NUMERIC(10, 4),
    eps_actual              NUMERIC(10, 4),
    eps_est                 NUMERIC(10, 4),
    eps_surprise_pct        NUMERIC(10, 4),
    beat_miss               VARCHAR(20),            -- 'beat', 'miss', 'in_line', null
    guidance_tone           VARCHAR(20),            -- 'raised', 'maintained', 'lowered', 'withdrawn', null
    mgmt_tone               VARCHAR(20),            -- 'positive', 'neutral', 'cautious', 'negative', null
    custom_kpis             JSONB DEFAULT '{}'::jsonb,
    pre_brief               JSONB,
    post_brief              JSONB,
    key_highlights          JSONB DEFAULT '[]'::jsonb,
    red_flags               JSONB DEFAULT '[]'::jsonb,
    transcript_available    BOOLEAN DEFAULT FALSE,
    data_source             VARCHAR(50) DEFAULT 'fmp',
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(ticker, fiscal_period)
);

CREATE INDEX IF NOT EXISTS idx_earnings_ticker ON earnings(ticker);
CREATE INDEX IF NOT EXISTS idx_earnings_report_date ON earnings(report_date);
CREATE INDEX IF NOT EXISTS idx_earnings_fiscal_period ON earnings(fiscal_period);
CREATE INDEX IF NOT EXISTS idx_earnings_beat_miss ON earnings(beat_miss);

-- Watchlists table
CREATE TABLE IF NOT EXISTS watchlists (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_email          VARCHAR(255) NOT NULL,
    user_name           VARCHAR(255),
    ticker              VARCHAR(20) NOT NULL REFERENCES companies(ticker) ON DELETE CASCADE,
    notify_pre_brief    BOOLEAN DEFAULT TRUE,
    notify_post_brief   BOOLEAN DEFAULT TRUE,
    alert_conditions    JSONB DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_email, ticker)
);

CREATE INDEX IF NOT EXISTS idx_watchlists_user_email ON watchlists(user_email);
CREATE INDEX IF NOT EXISTS idx_watchlists_ticker ON watchlists(ticker);

-- Documents table: stores raw files + extracted text per earnings event
CREATE TABLE IF NOT EXISTS documents (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticker          VARCHAR(20) NOT NULL REFERENCES companies(ticker) ON DELETE CASCADE,
    fiscal_period   VARCHAR(20),
    doc_type        VARCHAR(50) NOT NULL DEFAULT 'unknown',  -- press_release, presentation, transcript, announcement
    title           TEXT,
    source_url      TEXT NOT NULL,
    file_name       TEXT,       -- filename on disk under /app/documents/{ticker}/
    mime_type       VARCHAR(100),
    extracted_text  TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (ticker, fiscal_period, source_url)
);

CREATE INDEX IF NOT EXISTS idx_documents_ticker ON documents(ticker);
CREATE INDEX IF NOT EXISTS idx_documents_ticker_period ON documents(ticker, fiscal_period);
