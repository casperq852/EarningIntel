"""
Settings router — GET/PUT /settings for LLM model configuration.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db

router = APIRouter(prefix="/settings", tags=["settings"])

_DEFAULTS: Dict[str, Any] = {
    "synthesis_provider": "anthropic",
    "synthesis_model": "claude-sonnet-4-20250514",
    "parser_provider": "anthropic",
    "parser_model": "claude-sonnet-4-20250514",
    "openrouter_api_key": None,
}


async def get_settings_from_db(db: AsyncSession) -> Dict[str, Any]:
    """Load settings from DB, merging with defaults."""
    result = await db.execute(text("SELECT config FROM app_settings WHERE id = 1"))
    row = result.mappings().first()
    if not row:
        return dict(_DEFAULTS)
    return {**_DEFAULTS, **(row["config"] or {})}


@router.get("")
async def get_settings(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    return await get_settings_from_db(db)


@router.put("")
async def update_settings(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    current = await get_settings_from_db(db)
    merged = {**current, **payload}

    await db.execute(
        text("""
            INSERT INTO app_settings (id, config) VALUES (1, CAST(:config AS jsonb))
            ON CONFLICT (id) DO UPDATE SET config = CAST(:config AS jsonb), updated_at = NOW()
        """),
        {"config": json.dumps(merged)},
    )
    await db.commit()
    return merged
