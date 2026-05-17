"""
Documents router — list and download source documents attached to earnings events.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from services.document_store import get_document_by_id, get_file_path, list_documents

router = APIRouter(prefix="/documents", tags=["documents"])

_MIME_TO_EXT = {
    "application/pdf": "application/pdf",
    "text/html": "text/html",
}


@router.get("/{ticker}")
async def list_company_documents(ticker: str, db: AsyncSession = Depends(get_db)):
    return await list_documents(db, ticker)


@router.get("/{ticker}/{fiscal_period}")
async def list_period_documents(
    ticker: str, fiscal_period: str, db: AsyncSession = Depends(get_db)
):
    return await list_documents(db, ticker, fiscal_period)


@router.get("/{doc_id}/download", response_class=FileResponse)
async def download_document(doc_id: str, db: AsyncSession = Depends(get_db)):
    doc = await get_document_by_id(db, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.get("file_name"):
        raise HTTPException(status_code=404, detail="No file stored for this document")

    path = get_file_path(doc["ticker"], doc["file_name"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing from disk")

    media_type = doc.get("mime_type") or "application/octet-stream"
    return FileResponse(
        path=str(path),
        media_type=media_type,
        filename=doc["file_name"],
    )
