# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Earnings Intelligence Platform for a European equity portfolio management team. Monitors ~120 companies, auto-generates pre-earnings briefs (T-1) and post-earnings breakdowns, stores structured data in PostgreSQL, and serves a React dashboard + email digests.

**Claude (Anthropic API) is the synthesis engine** — it receives FMP financial data + transcript excerpts and returns structured JSON briefs.

## Stack

| Component | Technology |
|-----------|------------|
| Database | PostgreSQL 16 |
| Backend | FastAPI (Python), asyncpg or SQLAlchemy 2.0 async |
| HTTP client | `httpx` (async, for FMP and Anthropic calls) |
| Claude | Official `anthropic` Python SDK |
| Frontend | React 18 + Vite + Tailwind CSS + Recharts |
| Scheduler | n8n (cron workflows, set up via UI after stack runs) |
| Deployment | Docker Compose on Unraid, Cloudflare Tunnel for external access |

## Build Order

Follow this sequence to avoid rework:
1. `docker-compose.yml` + `.env`
2. `db/schema.sql`
3. `seed/companies.json`
4. `backend/services/fmp.py`
5. `backend/services/claude.py`
6. `backend/routers/`
7. `backend/main.py`
8. `frontend/`
9. `nginx/nginx.conf`
10. n8n workflows (via UI)

## Running the Stack

```bash
# Start all services
docker compose up -d

# Start with rebuild
docker compose up -d --build

# View backend logs
docker compose logs -f backend

# Run DB migrations / seed
docker compose exec backend python seed/seed.py
```

## Docker Hub — Building & Publishing

Images are tagged `casperq852/earningintel-backend` and `casperq852/earningintel-frontend`. Build and push both whenever the code changes:

```bash
# Build and push backend
docker build -t casperq852/earningintel-backend:latest ./backend
docker push casperq852/earningintel-backend:latest

# Build and push frontend
docker build -t casperq852/earningintel-frontend:latest ./frontend
docker push casperq852/earningintel-frontend:latest
```

Or build both at once via Compose and push:
```bash
docker compose build
docker compose push
```

On Unraid, pull the latest images and restart:
```bash
docker compose pull
docker compose up -d
```

## Deployment — Cloudflare Tunnel (Unraid)

No nginx or SSL config needed. The Cloudflare Tunnel on Unraid handles external access and HTTPS termination. Expose services directly on their ports:
- Frontend: port **3000**
- Backend API: port **8000**
- n8n: port **5678**

Point your Cloudflare Tunnel hostnames at `localhost:<port>` on the Unraid host.

## Directory Structure

```
earnings-platform/
├── docker-compose.yml
├── .env                  # from .env.example
├── db/schema.sql
├── backend/
│   ├── main.py
│   ├── routers/          # companies.py, earnings.py, calendar.py, watchlist.py
│   ├── services/         # fmp.py, claude.py, email.py
│   └── models/schemas.py
├── frontend/src/
│   ├── pages/
│   ├── components/
│   └── api/
└── seed/companies.json
```

## Key Architecture Decisions

### Database
Two JSONB fields with different purposes:
- `companies.custom_kpis` — **list of KPI names** to extract (e.g. `["euv_shipments", "backlog_bn"]`)
- `earnings.custom_kpis` — **actual values** per report (e.g. `{"euv_shipments": 12, "backlog_bn": 36.4}`)

### FMP Integration (`services/fmp.py`)
- Base URL: `https://financialmodelingprep.com/api/v3`
- Auth: `?apikey={FMP_API_KEY}` query param on every request
- European tickers require exchange suffixes in `fmp_symbol` (e.g. ASML.AS, MC.PA, SAP.DE, NOVO-B.CO) — resolve via `GET /search?query={name}&exchange={exchange}` at seed time and store in `companies.fmp_symbol`
- Rate limit: 300 calls/minute on Starter plan — add delay between bulk operations
- Transcript endpoint: `GET /earning_call_transcript/{fmp_symbol}?quarter={1-4}&year={YYYY}` (requires Starter plan)
- Chunk transcripts before passing to Claude to stay within context limits

### Claude Integration (`services/claude.py`)
- Model: `claude-sonnet-4-20250514`
- Always use exponential backoff with max 3 retries
- Claude always returns **valid JSON only** — no preamble, no markdown (enforced by system prompt)
- Two prompt templates: post-earnings (returns `beat_miss`, `guidance_tone`, `mgmt_tone`, `custom_kpis`, `key_highlights`, `post_brief`, `red_flags`) and pre-earnings T-1 (returns `watch_items`, `consensus_vs_guidance`, `pre_brief`)
- Pass `prior_quarters_json` from DB for trend context

### n8n Workflows
Three workflows (configured via n8n UI, not code):
1. **Daily Calendar Check** — 07:00 CET: trigger pre-briefs for tomorrow's earnings, email watchlist subscribers
2. **Earnings Release Detector** — every 30 min during market hours: find newly released reports lacking `post_brief`, trigger synthesis
3. **Weekly Digest** — Friday 18:00 CET: compile past week, email all team members

## Environment Variables

```
POSTGRES_PASSWORD=
ANTHROPIC_API_KEY=
FMP_API_KEY=
N8N_USER=
N8N_PASSWORD=
N8N_WEBHOOK_URL=
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
```

## FastAPI Endpoints

```
GET/POST  /companies
GET/PUT   /companies/{ticker}
GET       /earnings/{ticker}
GET       /earnings/{ticker}/{period}    # e.g. /ASML/Q1-2026
GET       /earnings/recent               # last 30 days
POST      /synthesise/pre/{ticker}
POST      /synthesise/post/{ticker}
GET       /calendar                      # next 7/14/30 days
GET       /calendar/today
GET/POST/DELETE /watchlist/{email}/{ticker}
```

## Frontend Pages

| Route | Purpose |
|-------|---------|
| `/` | Dashboard: 14-day earnings calendar, recent reports, beat/miss stats |
| `/companies` | Searchable/filterable table of all 120 companies |
| `/companies/:ticker` | Earnings history, KPI trend charts (Recharts), latest brief |
| `/earnings/:ticker/:period` | Full pre/post brief, all KPIs, key highlights, red flags |
| `/watchlist` | Personal watchlist + notification preferences |
