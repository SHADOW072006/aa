"""
Stage 4 Retention, Audit Logging, Operational Monitoring & Access Control.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Header, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    Alert,
    AuditLog,
    Channel,
    ChannelHealthEvent,
    EvidenceMessage,
    ImportBatch,
    Message,
)


async def is_caller_authorized(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> bool:
    """Non-raising variant of require_api_token for conditional redaction on summary endpoints."""
    expected = settings.API_ACCESS_TOKEN
    if expected:
        token = None
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        elif x_api_key:
            token = x_api_key.strip()
        return token == expected
    client_host = request.client.host if request.client else "unknown"
    return client_host in ("127.0.0.1", "::1", "localhost", "testclient")


async def require_api_token(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> str:
    """
    Minimal protection for sensitive full-evidence & export endpoints:
    - If API_ACCESS_TOKEN is configured, requires matching Bearer token or X-API-Key.
    - If API_ACCESS_TOKEN is unset, allows loopback/local-only clients (127.0.0.1 / ::1 / testclient)
      and rejects non-local requests.
    """
    expected = settings.API_ACCESS_TOKEN
    if expected:
        token = None
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        elif x_api_key:
            token = x_api_key.strip()
        if token != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Valid API token required for full-evidence or export access.",
            )
        return "token_authenticated"

    client_host = request.client.host if request.client else "unknown"
    if client_host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Full-evidence and export endpoints are restricted to local access when API_ACCESS_TOKEN is unset.",
        )
    return f"local:{client_host}"


async def write_audit_log(
    db: AsyncSession,
    *,
    actor: str,
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    record_hash: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> AuditLog:
    """Append an immutable audit log entry (never stores raw message text)."""
    entry = AuditLog(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        record_hash=record_hash,
        details=json.dumps(details, sort_keys=True) if details else None,
    )
    db.add(entry)
    await db.flush()
    return entry


async def run_retention_purge(
    db: AsyncSession,
    *,
    actor: str = "retention_scheduler",
    exports_dir: str = "exports",
) -> Dict[str, int]:
    """
    Purge expired raw text, OCR text, media files, and export files according
    to configured retention periods. Preserves labels, hashes, and audit entries.
    Every purge action is logged to audit_logs (record ID + hash only).
    """
    now = datetime.utcnow()
    raw_cutoff = now - timedelta(days=settings.RETENTION_DAYS_RAW_TEXT)
    ocr_cutoff = now - timedelta(days=settings.RETENTION_DAYS_OCR_TEXT)
    media_cutoff = now - timedelta(days=settings.RETENTION_DAYS_MEDIA)
    export_cutoff = now - timedelta(days=settings.RETENTION_DAYS_EXPORTS)

    purged_raw = 0
    purged_ocr = 0
    purged_media = 0
    purged_exports = 0

    # 1. Purge expired raw text on Messages (keep hashes & alerts/reviews)
    msgs_raw = (
        await db.execute(
            select(Message).where(Message.collected_at < raw_cutoff, Message.text.is_not(None))
        )
    ).scalars().all()
    for m in msgs_raw:
        m.text = None
        purged_raw += 1
        await write_audit_log(
            db,
            actor=actor,
            action="retention_purge_raw_text",
            target_type="message",
            target_id=m.id,
            record_hash=m.evidence_hash or m.original_text_hash or m.text_hash,
        )

    # 2. Purge expired OCR text
    msgs_ocr = (
        await db.execute(
            select(Message).where(Message.collected_at < ocr_cutoff, Message.ocr_text.is_not(None))
        )
    ).scalars().all()
    for m in msgs_ocr:
        m.ocr_text = None
        purged_ocr += 1
        await write_audit_log(
            db,
            actor=actor,
            action="retention_purge_ocr_text",
            target_type="message",
            target_id=m.id,
            record_hash=m.evidence_hash or m.media_hash,
        )

    # 3. Purge expired media files (keep media_hash)
    msgs_media = (
        await db.execute(
            select(Message).where(Message.collected_at < media_cutoff, Message.media_path.is_not(None))
        )
    ).scalars().all()
    for m in msgs_media:
        if m.media_path:
            try:
                Path(m.media_path).unlink(missing_ok=True)
            except Exception:
                pass
        m.media_path = None
        purged_media += 1
        await write_audit_log(
            db,
            actor=actor,
            action="retention_purge_media",
            target_type="message",
            target_id=m.id,
            record_hash=m.media_hash or m.evidence_hash,
        )

    # 4. Purge expired local export files
    exp_path = Path(exports_dir)
    if exp_path.exists():
        for f in exp_path.iterdir():
            if f.is_file() and datetime.utcfromtimestamp(f.stat().st_mtime) < export_cutoff:
                f.unlink(missing_ok=True)
                purged_exports += 1
                await write_audit_log(
                    db,
                    actor=actor,
                    action="retention_purge_export",
                    target_type="export",
                    target_id=None,
                    details={"filename": f.name},
                )

    await db.flush()
    return {
        "purged_raw_text": purged_raw,
        "purged_ocr_text": purged_ocr,
        "purged_media": purged_media,
        "purged_exports": purged_exports,
    }


async def get_operational_monitoring(db: AsyncSession) -> Dict[str, Any]:
    """
    Operational monitoring (counts only — no raw text or identifiers):
    - collector health (last successful poll per channel, error/flood-wait counts)
    - import batch results (imported / duplicate / failed)
    - OCR success/skip/failure rates
    - alert volume by category per day
    """
    channels = (await db.execute(select(Channel).where(Channel.is_active == True))).scalars().all()  # noqa: E712
    collector_channels = [
        {
            "channel_id": c.id,
            "channel_username": c.username,
            "status": c.channel_status or "active",
            "last_fetched_at": c.last_fetched_at.isoformat() if c.last_fetched_at else None,
            "consecutive_error_count": c.consecutive_error_count,
        }
        for c in channels[:100]
    ]

    health_q = await db.execute(
        select(ChannelHealthEvent.event_type, func.count(ChannelHealthEvent.id))
        .group_by(ChannelHealthEvent.event_type)
    )
    health_counts = dict(health_q.all())

    batches = (
        await db.execute(select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(25))
    ).scalars().all()
    import_summary = {
        "total_batches": len(batches),
        "imported_total": sum(b.imported_count for b in batches),
        "duplicate_total": sum(b.duplicate_count for b in batches),
        "failed_total": sum(b.failed_count for b in batches),
    }

    ocr_q = await db.execute(
        select(EvidenceMessage.ocr_outcome, func.count(EvidenceMessage.id))
        .group_by(EvidenceMessage.ocr_outcome)
    )
    ocr_counts = {k or "unknown": v for k, v in ocr_q.all()}
    ocr_total = sum(ocr_counts.values())
    ocr_rates = {
        "counts": ocr_counts,
        "total": ocr_total,
        "success_rate": round(ocr_counts.get("success", 0) / ocr_total, 3) if ocr_total > 0 else 0.0,
        "skip_rate": round(ocr_counts.get("skipped", 0) / ocr_total, 3) if ocr_total > 0 else 0.0,
        "failure_rate": round(ocr_counts.get("failed", 0) / ocr_total, 3) if ocr_total > 0 else 0.0,
    }

    alerts = (await db.execute(select(Alert.created_at, Alert.categories))).all()
    daily_cat: Dict[str, Dict[str, int]] = {}
    for created_at, cats in alerts:
        day = created_at.strftime("%Y-%m-%d") if created_at else "unknown"
        if day not in daily_cat:
            daily_cat[day] = {}
        for c in (cats or "uncategorised").split(","):
            ck = c.strip() or "uncategorised"
            daily_cat[day][ck] = daily_cat[day].get(ck, 0) + 1

    return {
        "collector_health": {
            "active_channels": len(channels),
            "health_event_counts": health_counts,
            "channels": collector_channels,
        },
        "import_batches": import_summary,
        "ocr": ocr_rates,
        "alert_volume_by_category_per_day": daily_cat,
    }

