"""
Seed script — loads companies from seed/companies.json into the database.
Run from repo root: python seed/seed.py
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

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
            await session.execute(
                text(
                    """
                    INSERT INTO companies (ticker, name, sector, exchange, country, fmp_symbol, ir_url, custom_kpis, active)
                    VALUES (:ticker, :name, :sector, :exchange, :country, :fmp_symbol, :ir_url, CAST(:custom_kpis AS jsonb), true)
                    ON CONFLICT (ticker) DO UPDATE SET
                        ir_url = EXCLUDED.ir_url,
                        fmp_symbol = EXCLUDED.fmp_symbol,
                        custom_kpis = EXCLUDED.custom_kpis
                    """
                ),
                {
                    "ticker": company["ticker"],
                    "name": company["name"],
                    "sector": company.get("sector"),
                    "exchange": company.get("exchange"),
                    "country": company.get("country"),
                    "fmp_symbol": company.get("fmp_symbol", company["ticker"]),
                    "ir_url": company.get("ir_url"),
                    "custom_kpis": json.dumps(company.get("custom_kpis", [])),
                },
            )
            print(f"  UPSERTED: {company['ticker']} — {company['name']}")

        await session.commit()

    await engine.dispose()
    print("\nSeed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
