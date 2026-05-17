# Earnings Intelligence Platform — Claude Code Project Brief

## Overview

Build a team-facing earnings intelligence platform for a European equity portfolio management team. The system monitors ~120 companies, automatically generates pre-earnings briefs (T-1) and post-earnings breakdowns (on release), stores structured historical data in a PostgreSQL database, and exposes everything via a web UI and email digests.

Claude (via Anthropic API) is the synthesis engine — it receives structured financial data and earnings transcript excerpts from Financial Modeling Prep (FMP) and returns structured JSON + a written brief for the team.

---

## Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Database | PostgreSQL 16 | Persistent earnings history |
| Scheduler | n8n | Cron-based workflow orchestration |
| Backend | FastAPI (Python) | API layer, Claude calls, FMP calls |
| Frontend | React + Tailwind CSS | Team-facing dashboard |
| Reverse proxy | Nginx | Single entry point, SSL termination |
| Containerisation | Docker Compose | Single-command deployment on Unraid |

---

## Deployment Target

Unraid home server with Docker Compose. Nginx reverse proxies all services behind a single domain (e.g. `earnings.internal.com`). The stack must be accessible to remote team members via the web.

---

## Database Schema

```sql
-- Master company registry
CREATE TABLE companies (
    ticker TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    sector TEXT,
    exchange TEXT,
    country TEXT,
    fmp_symbol TEXT,                -- FMP ticker symbol (e.g. ASML.AS, MC.PA, SAP.DE)
    custom_kpis JSONB,              -- e.g. ["euv_shipments", "backlog_bn", "gross_margin_pct"]
    added_by TEXT,
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- One row per earnings report per company
CREATE TABLE earnings (
    id SERIAL PRIMARY KEY,
    ticker TEXT REFERENCES companies(ticker),
    report_date DATE NOT NULL,
    fiscal_period TEXT NOT NULL,    -- e.g. 'Q1 2026'
    fiscal_year INTEGER,
    fiscal_quarter INTEGER,

    -- Universal fields (every company)
    revenue_actual REAL,
    revenue_est REAL,
    revenue_surprise_pct REAL,
    eps_actual REAL,
    eps_est REAL,
    eps_surprise_pct REAL,
    beat_miss TEXT,                 -- 'beat' | 'miss' | 'in-line'
    guidance_tone TEXT,             -- 'raised' | 'lowered' | 'maintained' | 'none'
    mgmt_tone TEXT,                 -- 'bullish' | 'cautious' | 'mixed'

    -- Company-specific KPIs (flexible per ticker)
    custom_kpis JSONB,              -- e.g. {"euv_shipments": 12, "backlog_bn": 36.4}

    -- Claude-generated content
    pre_brief TEXT,                 -- Generated T-1, what to watch
    post_brief TEXT,                -- Full written breakdown post-release
    key_highlights JSONB,           -- Array of 3-5 bullet strings
    red_flags JSONB,                -- Anything contradicting prior guidance

    -- Meta
    transcript_available BOOLEAN DEFAULT false,
    data_source TEXT DEFAULT 'fmp',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(ticker, fiscal_period)
);

-- Per-user watchlists and notification preferences
CREATE TABLE watchlists (
    id SERIAL PRIMARY KEY,
    user_email TEXT NOT NULL,
    user_name TEXT,
    ticker TEXT REFERENCES companies(ticker),
    notify_pre_brief BOOLEAN DEFAULT true,
    notify_post_brief BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(user_email, ticker)
);
```

---

## Example Company KPI Configs

Seed the `companies` table with these examples. The `custom_kpis` field defines which company-specific metrics Claude should extract from each earnings report.

```json
[
  {
    "ticker": "ASML",
    "name": "ASML Holding",
    "sector": "Technology",
    "exchange": "XAMS",
    "country": "NL",
    "custom_kpis": ["euv_shipments", "duvimmersion_shipments", "backlog_bn", "gross_margin_pct", "net_bookings_bn"]
  },
  {
    "ticker": "NOVO",
    "name": "Novo Nordisk",
    "sector": "Health Care",
    "exchange": "XCSE",
    "country": "DK",
    "custom_kpis": ["ozempic_sales_bn", "wegovy_sales_bn", "obesity_segment_growth_pct", "diabetes_segment_growth_pct", "rd_spend_bn"]
  },
  {
    "ticker": "MC",
    "name": "LVMH",
    "sector": "Consumer Goods",
    "exchange": "XPAR",
    "country": "FR",
    "custom_kpis": ["organic_growth_pct", "fashion_leather_revenue_bn", "asia_revenue_pct", "operating_margin_pct"]
  },
  {
    "ticker": "SAP",
    "name": "SAP SE",
    "sector": "Technology",
    "exchange": "XFRA",
    "country": "DE",
    "custom_kpis": ["cloud_revenue_bn", "cloud_backlog_bn", "cloud_growth_pct", "current_cloud_backlog_bn", "operating_profit_bn"]
  }
]
```

---

## API Integrations

### Financial Modeling Prep — FMP (data source)
- Base URL: `https://financialmodelingprep.com/api/v3`
- Plan required: **Starter** (~$25-30/month) — needed for transcript access
- API key: single query param `?apikey={FMP_API_KEY}` on all requests
- Documentation: https://site.financialmodelingprep.com/developer/docs

**Key endpoints used:**

| Purpose | Endpoint |
|---------|----------|
| Earnings calendar (upcoming) | `GET /earning_calendar?from={date}&to={date}` |
| Historical earnings calendar | `GET /historical/earning_calendar/{symbol}` |
| Earnings surprises (actuals vs est) | `GET /earnings-surprises/{symbol}` |
| Analyst estimates | `GET /analyst-estimates/{symbol}` |
| Income statement (quarterly) | `GET /income-statement/{symbol}?period=quarter` |
| Earnings call transcript | `GET /earning_call_transcript/{symbol}?quarter={Q}&year={YYYY}` |

**Important — European ticker symbols:**
FMP uses exchange-suffixed symbols for non-US stocks. Store these in the `fmp_symbol` column:

| Company | Ticker | FMP Symbol |
|---------|--------|------------|
| ASML | ASML | ASML.AS |
| LVMH | MC | MC.PA |
| SAP | SAP | SAP.DE |
| Novo Nordisk | NOVO B | NOVO-B.CO |
| Hermès | RMS | RMS.PA |

Resolve FMP symbols at seed time using `GET /search?query={name}&exchange={exchange}` and store in `companies.fmp_symbol`.

### Anthropic Claude API (synthesis engine)
- Model: `claude-sonnet-4-20250514`
- Used for: generating pre-briefs and post-earnings breakdowns
- Called from FastAPI backend after assembling context from FMP
- Returns structured JSON (see prompt schema below)

---

## Claude Prompt Design

### System Prompt
```
You are a senior equity analyst assistant specialising in European equities.
You receive raw earnings data and earnings call transcript excerpts for a company.
Your job is to synthesise these into a structured, concise brief for a portfolio management team.

Rules:
- Always respond in valid JSON exactly matching the schema provided. No preamble, no markdown.
- Be precise with numbers. Round to 2 decimal places.
- Assess management tone from the transcript language, not just the numbers.
- Flag anything that contradicts prior guidance or prior quarter trends as a red flag.
- key_highlights should be 3-5 concise bullet points a PM would care about most.
- post_brief should be 2-4 sentences of flowing prose summarising the quarter.
- If a custom KPI is not mentioned in the transcript or financials, return null for that field.
```

### User Prompt Template (post-earnings)
```
Company: {name} ({ticker})
Fiscal Period: {fiscal_period}
Sector: {sector}
Exchange: {exchange}

=== FINANCIAL DATA ===
Revenue: {revenue_actual} vs {revenue_est} est ({revenue_surprise_pct:+.1f}%)
EPS: {eps_actual} vs {eps_est} est ({eps_surprise_pct:+.1f}%)

Prior quarters (from database):
{prior_quarters_json}

=== TRANSCRIPT EXCERPTS ===
{transcript_chunks}

=== CUSTOM KPIs TO EXTRACT ===
Extract these company-specific metrics if mentioned: {custom_kpi_list}
Return null for any not found.

=== OUTPUT SCHEMA ===
{
  "beat_miss": "beat|miss|in-line",
  "guidance_tone": "raised|lowered|maintained|none",
  "mgmt_tone": "bullish|cautious|mixed",
  "custom_kpis": {},
  "key_highlights": ["...", "...", "..."],
  "post_brief": "Written paragraph summary...",
  "red_flags": ["..."]
}
```

### User Prompt Template (pre-earnings, T-1)
```
Company: {name} ({ticker})
Earnings Date: {report_date}
Fiscal Period: {fiscal_period}

=== ANALYST ESTIMATES ===
Revenue est: {revenue_est}
EPS est: {eps_est}

=== PRIOR QUARTER ACTUALS ===
{prior_quarter_json}

=== PRIOR GUIDANCE ===
{prior_guidance_from_last_brief}

=== CUSTOM KPIs TO WATCH ===
{custom_kpi_list}

Generate a pre-earnings brief. Return JSON:
{
  "watch_items": ["3-5 specific things to watch for"],
  "consensus_vs_guidance": "brief note on where consensus sits vs prior guidance",
  "pre_brief": "2-3 sentence written brief for the team"
}
```

---

## FastAPI Endpoints

```
GET  /companies                     # List all active companies
POST /companies                     # Add a new company
GET  /companies/{ticker}            # Company detail + KPI config
PUT  /companies/{ticker}            # Update KPI config

GET  /earnings/{ticker}             # All earnings history for a ticker
GET  /earnings/{ticker}/{period}    # Single earnings record (e.g. /ASML/Q1-2026)
GET  /earnings/recent               # Last 30 days of reports across all companies

POST /synthesise/pre/{ticker}       # Trigger pre-brief generation for a ticker
POST /synthesise/post/{ticker}      # Trigger post-earnings synthesis for a ticker

GET  /calendar                      # Upcoming earnings in next 7/14/30 days
GET  /calendar/today                # Earnings releasing today

GET  /watchlist/{email}             # User's watchlist
POST /watchlist/{email}/{ticker}    # Add to watchlist
DELETE /watchlist/{email}/{ticker}  # Remove from watchlist
```

---

## n8n Workflows

### Workflow 1: Daily Calendar Check (runs 07:00 CET)
1. HTTP Request → FastAPI `/calendar` for next 24h
2. For each company with earnings tomorrow:
   - HTTP Request → FastAPI `POST /synthesise/pre/{ticker}`
   - Send email to all users who have that ticker in their watchlist with `notify_pre_brief: true`

### Workflow 2: Earnings Release Detector (runs every 30 min during market hours)
1. HTTP Request → FMP `/earning_calendar` for today
2. Compare against `earnings` table — find any that now have actuals but no `post_brief`
3. For each newly released:
   - HTTP Request → FastAPI `POST /synthesise/post/{ticker}`
   - Send email digest to relevant watchlist subscribers

### Workflow 3: Weekly Digest (runs Friday 18:00 CET)
1. HTTP Request → FastAPI `/earnings/recent`
2. Compile all earnings from the past week
3. Send summary email to all team members

---

## React Frontend Pages

### 1. Dashboard (/)
- Earnings calendar for next 14 days (highlighted by watchlist)
- Recent reports feed (last 7 days)
- Quick stats: beats vs misses this week

### 2. Company List (/companies)
- Searchable, filterable table of all 120 companies
- Columns: ticker, name, sector, country, last report date, beat/miss
- Click → company detail page

### 3. Company Detail (/companies/:ticker)
- Header: name, sector, last price (if available)
- Earnings history table: fiscal period, revenue surprise, EPS surprise, beat/miss, guidance tone, mgmt tone
- KPI trend chart: plot custom KPIs over time
- Latest brief displayed prominently
- Historical briefs collapsible

### 4. Earnings Detail (/earnings/:ticker/:period)
- Full pre-brief (if available)
- Full post-brief
- All KPI actuals vs estimates
- Custom KPIs
- Key highlights bullets
- Red flags (if any)

### 5. Watchlist (/watchlist)
- User's personal watchlist management
- Toggle pre/post brief notifications per company

---

## Docker Compose Structure

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: earnings
      POSTGRES_USER: earnings_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./db/schema.sql:/docker-entrypoint-initdb.d/schema.sql
    ports:
      - "5432:5432"

  backend:
    build: ./backend
    environment:
      DATABASE_URL: postgresql://earnings_user:${POSTGRES_PASSWORD}@postgres:5432/earnings
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      FMP_API_KEY: ${FMP_API_KEY}
    depends_on:
      - postgres
    ports:
      - "8000:8000"

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    depends_on:
      - backend

  n8n:
    image: n8nio/n8n
    environment:
      N8N_BASIC_AUTH_ACTIVE: true
      N8N_BASIC_AUTH_USER: ${N8N_USER}
      N8N_BASIC_AUTH_PASSWORD: ${N8N_PASSWORD}
      WEBHOOK_URL: ${N8N_WEBHOOK_URL}
    volumes:
      - n8n_data:/home/node/.n8n
    ports:
      - "5678:5678"
    depends_on:
      - backend

  nginx:
    image: nginx:alpine
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf
      - ./nginx/certs:/etc/nginx/certs
    ports:
      - "80:80"
      - "443:443"
    depends_on:
      - frontend
      - backend

volumes:
  postgres_data:
  n8n_data:
```

---

## Directory Structure

```
earnings-platform/
├── docker-compose.yml
├── .env.example
├── db/
│   └── schema.sql
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   ├── routers/
│   │   ├── companies.py
│   │   ├── earnings.py
│   │   ├── calendar.py
│   │   └── watchlist.py
│   ├── services/
│   │   ├── fmp.py            # Financial Modeling Prep API client
│   │   ├── claude.py         # Claude API synthesis calls
│   │   └── email.py          # Email digest sender
│   └── models/
│       └── schemas.py        # Pydantic models
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   └── src/
│       ├── pages/
│       ├── components/
│       └── api/
├── nginx/
│   └── nginx.conf
└── seed/
    └── companies.json        # Initial 120 company list with KPI configs
```

---

## Environment Variables (.env)

```
POSTGRES_PASSWORD=your_secure_password
ANTHROPIC_API_KEY=sk-ant-...
FMP_API_KEY=your_fmp_api_key
N8N_USER=admin
N8N_PASSWORD=your_secure_password
N8N_WEBHOOK_URL=https://earnings.yourfirm.com/n8n
SMTP_HOST=smtp.yourprovider.com
SMTP_PORT=587
SMTP_USER=earnings@yourfirm.com
SMTP_PASSWORD=your_smtp_password
```

---

## Build Order

Start in this sequence to avoid rework:

1. `docker-compose.yml` + `.env` — get containers running and talking
2. `db/schema.sql` — create all tables
3. `seed/companies.json` — initial company list with KPI configs
4. `backend/services/fmp.py` — FMP API client (earnings calendar, surprises, transcripts)
5. `backend/services/claude.py` — Claude synthesis service with prompt templates
6. `backend/routers/` — all FastAPI endpoints
7. `backend/main.py` — wire everything together
8. `frontend/` — React dashboard
9. `nginx/nginx.conf` — reverse proxy config
10. `n8n workflows` — set up via n8n UI after stack is running

---

## Notes for Claude Code

- Use `asyncpg` or `SQLAlchemy 2.0 async` for PostgreSQL in FastAPI
- Use `httpx` for async HTTP calls to FMP and Anthropic
- Use the official `anthropic` Python SDK for Claude calls
- Frontend: React 18 + Vite + Tailwind CSS + Recharts for KPI trend charts
- All Claude API calls should have retry logic (exponential backoff, max 3 retries)
- FMP transcript endpoint: `GET /earning_call_transcript/{fmp_symbol}?quarter={1-4}&year={YYYY}` — requires Starter plan
- FMP earnings surprises: `GET /earnings-surprises/{fmp_symbol}` returns last 4 quarters of actuals vs estimates
- European tickers need exchange suffix in `fmp_symbol` (e.g. ASML.AS, MC.PA, SAP.DE) — resolve and store these at seed time
- FMP rate limits: 300 calls/minute on Starter plan — add a small delay between bulk operations
- The `custom_kpis` JSONB field in `companies` stores the *list* of KPI names to extract; the `custom_kpis` JSONB field in `earnings` stores the *actual values* per report
- Transcripts from FMP are plain text per quarter — chunk into segments before passing to Claude to stay within context limits
