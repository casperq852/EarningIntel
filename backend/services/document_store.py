"""
Document persistence — saves EarningsDoc files to disk and records to Postgres.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.scraper import EarningsDoc

DOCS_BASE = Path("/app/documents")


def _safe_name(s: str, max_len: int = 40) -> str:
    return re.sub(r"[^a-z0-9_-]", "_", s.lower())[:max_len].strip("_")


def _ext(mime_type: str) -> str:
    return ".pdf" if "pdf" in mime_type else ".html"


def _doc_path(ticker: str, doc_id: str, title: str, mime_type: str) -> Path:
    folder = DOCS_BASE / ticker.upper()
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{doc_id[:8]}_{_safe_name(title)}{_ext(mime_type)}"
    return folder / name


async def save_document(
    db: AsyncSession,
    ticker: str,
    fiscal_period: Optional[str],
    doc: EarningsDoc,
) -> str:
    """Persist file to disk and insert a documents row. Returns the new doc UUID."""
    doc_id = str(uuid.uuid4())
    path = _doc_path(ticker, doc_id, doc.title, doc.mime_type)

    path.write_bytes(doc.content_bytes)

    await db.execute(
        text(
            """
            INSERT INTO documents
                (id, ticker, fiscal_period, doc_type, title, source_url,
                 file_name, mime_type, extracted_text)
            VALUES
                (:id, :ticker, :fp, :doc_type, :title, :source_url,
                 :file_name, :mime_type, :extracted_text)
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "id": doc_id,
            "ticker": ticker.upper(),
            "fp": fiscal_period,
            "doc_type": doc.doc_type,
            "title": doc.title,
            "source_url": doc.url,
            "file_name": path.name,
            "mime_type": doc.mime_type,
            "extracted_text": doc.extracted_text,
        },
    )
    await db.commit()
    return doc_id


async def list_documents(
    db: AsyncSession,
    ticker: str,
    fiscal_period: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if fiscal_period:
        result = await db.execute(
            text(
                "SELECT id, ticker, fiscal_period, doc_type, title, source_url, "
                "file_name, mime_type, created_at "
                "FROM documents WHERE ticker = :ticker AND fiscal_period = :fp "
                "ORDER BY created_at DESC"
            ),
            {"ticker": ticker.upper(), "fp": fiscal_period},
        )
    else:
        result = await db.execute(
            text(
                "SELECT id, ticker, fiscal_period, doc_type, title, source_url, "
                "file_name, mime_type, created_at "
                "FROM documents WHERE ticker = :ticker "
                "ORDER BY created_at DESC"
            ),
            {"ticker": ticker.upper()},
        )
    return [dict(row) for row in result.mappings()]


async def get_document_by_id(
    db: AsyncSession,
    doc_id: str,
) -> Optional[Dict[str, Any]]:
    result = await db.execute(
        text("SELECT * FROM documents WHERE id = :id"),
        {"id": doc_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


def get_file_path(ticker: str, file_name: str) -> Path:
    return DOCS_BASE / ticker.upper() / file_name
