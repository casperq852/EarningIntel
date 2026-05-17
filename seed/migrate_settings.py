"""
One-time migration: add app_settings table.
Run from repo root: python seed/migrate_settings.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv()

DATABASE_URL = (
    os.getenv("DATABASE_URL")
    or f"postgresql+asyncpg://{os.getenv('POSTGRES_USER','postgres')}:"
       f"{os.getenv('POSTGRES_PASSWORD','')}@"
       f"{os.getenv('POSTGRES_HOST','localhost')}:"
       f"{os.getenv('POSTGRES_PORT','5432')}/"
       f"{os.getenv('POSTGRES_DB','earningintel')}"
)

DDL = """
CREATE TABLE IF NOT EXISTS app_settings (
    id          INTEGER PRIMARY KEY DEFAULT 1,
    config      JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT app_settings_single_row CHECK (id = 1)
);
"""


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text(DDL))
    await engine.dispose()
    print("Migration complete: app_settings table created (if not already present).")


if __name__ == "__main__":
    asyncio.run(main())
