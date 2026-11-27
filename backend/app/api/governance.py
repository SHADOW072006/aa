"""
Governance, chain-of-custody verification, retention purge,
operational monitoring, and audit-log endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db, get_session
from app.db.models import AuditLog, Channel, EvidenceMessage, Message, ReclassificationJob
from app.services.evidence_hashing import backfill_provenance_hashes, verify_record_hashes
from app.services.reclassification_service import (
    ActiveReclassificationJobError,
    _job_summary,
    recover_stale_reclassification_job,
    run_reclassification,
)
from app.services.retention_service import (
    get_operational_monitoring,
    require_api_token,
    run_retention_purge,
)

router = APIRouter(prefix="/governance", tags=["governance"])


@router.get("/verify/message/{message_id}")
async def verify_message_custody(
    message_id: int,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Recompute original_text_hash, media_hash, and evidence_hash for a Message."""
    row = (
        await db.execute(
            select(Message, Channel)
            .join(Channel, Channel.id == Message.channel_id)
            .where(Message.id == message_id)
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Message not found")
    msg, ch = row
    report = verify_record_hashes(
        raw_text=msg.text,
        stored_original_text_hash=msg.original_text_hash,
        media_path=msg.media_path,
        stored_media_hash=msg.media_hash,
        source_platform=msg.source or "telegram",
        channel_identifier=ch.username,
        source_message_id=msg.telegram_msg_id,
        post_timestamp=msg.created_at,
        stored_evidence_hash=msg.evidence_hash,
        has_media=bool(msg.has_media),
        stored_provenance_status=msg.provenance_status,
    )
    return {"target_type": "message", "target_id": msg.id, **report}


@router.get("/verify/evidence/{evidence_id}")
async def verify_evidence_custody(
    evidence_id: int,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Recompute hashes for an EvidenceMessage record."""
    em = (
        await db.execute(select(EvidenceMessage).where(EvidenceMessage.id == evidence_id))
    ).scalar_one_or_none()
    if not em:
        raise HTTPException(status_code=404, detail="EvidenceMessage not found")
    report = verify_record_hashes(
        raw_text=em.raw_text,
        stored_original_text_hash=em.original_text_hash,
        media_path=em.media_path,
        stored_media_hash=em.media_hash,
        source_platform="telegram",
        channel_identifier=em.channel_username,
        source_message_id=em.telegram_message_id,
        post_timestamp=em.message_timestamp,
        stored_evidence_hash=em.evidence_hash,
        has_media=bool(em.media_path or em.media_hash),
        stored_provenance_status=em.provenance_status,
    )
    return {"target_type": "evidence_message", "target_id": em.id, **report}


@router.post("/retention/purge")
async def trigger_retention_purge(
    actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Run retention purge for expired raw text, OCR text, media, and exports."""
    res = await run_retention_purge(db, actor=actor)
    await db.commit()
    return res


@router.get("/monitoring")
async def operational_monitoring(db: AsyncSession = Depends(get_db)):
    """Return operational monitoring counts (collector health, imports, OCR rates, daily alerts)."""
    return await get_operational_monitoring(db)


@router.get("/audit-logs")
async def list_audit_logs(
    action: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Return append-only audit log entries (IDs and hashes only, no raw text)."""
    q = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)
    if action:
        q = q.where(AuditLog.action == action)
    rows = (await db.execute(q)).scalars().all()
    return {
        "count": len(rows),
        "results": [
            {
                "id": r.id,
                "actor": r.actor,
                "action": r.action,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "record_hash": r.record_hash,
                "details": r.details,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


class ReclassifyRequest(BaseModel):
    dry_run: bool = True
    batch_size: int = 500
    resume_job_id: int | None = None


@router.post("/reclassify")
async def trigger_reclassification(
    body: ReclassifyRequest,
    actor: str = Depends(require_api_token),
):
    """Explicit, authenticated, auditable historical reclassification (aggregate counts only)."""
    try:
        return await run_reclassification(
            get_session,
            actor=actor,
            dry_run=body.dry_run,
            batch_size=max(1, min(body.batch_size, 2000)),
            resume_job_id=body.resume_job_id,
        )
    except ActiveReclassificationJobError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "active_job": exc.active_job,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


class RecoverJobRequest(BaseModel):
    confirm: bool = False
    target_status: str = "superseded"
    reason: str | None = None


@router.post("/reclassify/{job_id}/recover")
async def recover_reclassification_job_endpoint(
    job_id: int,
    body: RecoverJobRequest,
    actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Explicit, operator-confirmed recovery for a stale/interrupted ReclassificationJob."""
    try:
        res = await recover_stale_reclassification_job(
            db,
            job_id=job_id,
            actor=actor,
            confirm=body.confirm,
            target_status=body.target_status,
            reason=body.reason,
        )
        await db.commit()
        return res
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/reclassify/{job_id}")
async def get_reclassification_job(
    job_id: int,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    job = (
        await db.execute(select(ReclassificationJob).where(ReclassificationJob.id == job_id))
    ).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="ReclassificationJob not found")
    return _job_summary(job)


@router.post("/backfill-hashes")
async def trigger_hash_backfill(
    dry_run: bool = Query(True),
    actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Safely backfill provenance hashes for retained records (dry-run by default)."""
    res = await backfill_provenance_hashes(db, actor=actor, dry_run=dry_run)
    await db.commit()
    return res

