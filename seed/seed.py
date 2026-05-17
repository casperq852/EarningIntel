"""
Seed script — loads companies from seed/companies.json into the database.
Run from repo root: python seed/seed.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Allow import of backend modules
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://earningintel:password@localhost:5432/earningintel",
)

COMPANIES_FILE = Path(__file__).parent / "companies.json"


async def seed():
    engine = create_async_engine(DATABASE_URL, echo=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    with open(COMPANIES_FILE) as f:
        companies = json.load(f)

    async with session_factory() as session:
        for company in companies:
            # Check if exists
            result = await session.execute(
                text("SELECT ticker FROM companies WHERE ticker = :ticker"),
                {"ticker": company["ticker"]},
            )
            existing = result.scalar()

            if existing:
                print(f"  SKIP (exists): {company['ticker']}")
                continue

            await session.execute(
                text(
                    """
                    INSERT INTO companies (ticker, name, sector, exchange, country, fmp_symbol, custom_kpis, active)
                    VALUES (:ticker, :name, :sector, :exchange, :country, :fmp_symbol, :custom_kpis::jsonb, true)
                    """
                ),
                {
                    "ticker": company["ticker"],
                    "name": company["name"],
                    "sector": company.get("sector"),
                    "exchange": company.get("exchange"),
                    "country": company.get("country"),
                    "fmp_symbol": company.get("fmp_symbol", company["ticker"]),
                    "custom_kpis": json.dumps(company.get("custom_kpis", [])),
                },
            )
            print(f"  INSERTED: {company['ticker']} — {company['name']}")

        await session.commit()

    await engine.dispose()
    print("\nSeed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
