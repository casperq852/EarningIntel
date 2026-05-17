"""
EarningIntel FastAPI application entry point.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import engine
from routers import calendar, chat, companies, documents, earnings, onboard, settings, synthesise, watchlist


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage DB connection pool lifecycle."""
    # Startup: pool is created lazily by SQLAlchemy; nothing extra needed.
    yield
    # Shutdown: dispose connection pool cleanly.
    await engine.dispose()


app = FastAPI(
    title="EarningIntel API",
    description="Earnings Intelligence Platform — FastAPI backend",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow all origins for internal / development use
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(companies.router)
app.include_router(earnings.router)
app.include_router(calendar.router)
app.include_router(synthesise.router)
app.include_router(watchlist.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(onboard.router)
app.include_router(settings.router)


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok", "service": "earningintel-api"}
