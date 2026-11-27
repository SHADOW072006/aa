"""
Identifier search endpoints.

GET /search/identifier?value=<phone|upi|handle|wallet>
GET /search/identifier/export/pdf?value=<phone|upi|handle|wallet>
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.crud import get_identifiers_by_value
from app.db.database import get_db
from app.reports.pdf_generator import generate_identifier_search_pdf
from app.services.retention_service import require_api_token, write_audit_log

router = APIRouter(prefix="/search", tags=["search"])


async def _run_identifier_search(db: AsyncSession, value: str) -> dict:
    normalised = value.lower().strip()
    identifiers = await get_identifiers_by_value(db, normalised)

    results = []
    for ident in identifiers:
        msg = ident.message
        linked = [
            {"type": other.type, "value": other.value, "normalised": other.normalised}
            for other in (getattr(msg, "identifiers", None) or [])
            if other.id != ident.id
        ]
        cats = (
            [c.strip() for c in (msg.alert.categories or "").split(",") if c.strip()]
            if msg.alert
            else []
        )
        results.append({
            "identifier": {
                "type": ident.type,
                "value": ident.value,
                "normalised": ident.normalised,
            },
            "linked_identifiers": linked,
            "message": {
                "id": msg.id,
                "text": (msg.text or "").strip() or (f"[OCR] {msg.ocr_text}" if getattr(msg, "ocr_text", None) else None),
                "created_at": msg.created_at.isoformat(),
                "channel": msg.channel.username if msg.channel else None,
                "channel_title": msg.channel.title if msg.channel else None,
                "source": msg.source,
                "provenance_status": getattr(msg, "provenance_status", None),
                "evidence_hash": getattr(msg, "evidence_hash", None),
            },
            "alert": {
                "risk_level": msg.alert.risk_level if msg.alert else None,
                "score": round(msg.alert.score, 4) if msg.alert else None,
                "categories": cats,
            } if msg.alert else None,
        })

    return {
        "query": value,
        "count": len(results),
        "results": results,
    }


@router.get("/identifier")
async def search_identifier(
    value: str = Query(..., min_length=3, description="Phone, UPI, handle or wallet address"),
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    return await _run_identifier_search(db, value)


@router.get("/identifier/export/pdf")
async def export_identifier_search_pdf(
    value: str = Query(..., min_length=3, description="Phone, UPI, handle or wallet address"),
    actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Export a PDF intelligence dossier showing where the queried identifier is used."""
    data = await _run_identifier_search(db, value)
    pdf_bytes = generate_identifier_search_pdf(data)
    await write_audit_log(
        db,
        actor=actor,
        action="pdf_export",
        target_type="identifier_search",
        details={"query_length": len(value), "matches": data["count"]},
    )
    await db.commit()

    safe_slug = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value.strip())[:40] or "identifier"
    filename = f"telemonitor_identifier_{safe_slug}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )
