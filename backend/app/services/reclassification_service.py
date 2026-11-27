"""
Stage 2: Historical Reclassification Service (no evidence loss).

- Explicit, authenticated, auditable (never runs automatically at startup).
- Batch-processed, transaction-safe, and resumable via ReclassificationJob.
- Preserves all prior EvidenceObservations, Alert dispositions, and raw evidence.
- Idempotent per scoring_version: skips messages already observed under the
  target scoring_version.
- Outputs aggregate counts only (never raw text or identifiers).
"""
from __future__ import annotations

import json
import logging
import os
import socket
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional, Set

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.classifiers.classifier import classify
from app.core.config import settings
from app.db.crud import insert_evidence_observation, upsert_evidence_message
from app.db.models import (
    Alert,
    Channel,
    EvidenceMessage,
    EvidenceObservation,
    Message,
    ReclassificationJob,
)
from app.services.evidence_hashing import (
    compute_evidence_hash,
    compute_observation_hash,
    compute_original_text_hash,
)
from app.services.retention_service import write_audit_log

logger = logging.getLogger(__name__)

# In-process active worker tracking (paired with DB-backed lock & heartbeat)
_active_reclass_workers: Set[int] = set()


class ActiveReclassificationJobError(RuntimeError):
    """Raised when a live non-dry-run reclassification job is already active."""

    def __init__(self, active_job: Dict[str, Any]) -> None:
        self.active_job = active_job
        super().__init__(
            f"ReclassificationJob #{active_job['job_id']} is already running "
            f"(processed={active_job['processed']}/{active_job['total_messages']})."
        )


def _worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _job_summary(job: ReclassificationJob) -> Dict[str, Any]:
    return {
        "job_id": job.id,
        "scoring_version": job.scoring_version,
        "status": job.status,
        "dry_run": job.dry_run,
        "last_processed_message_id": job.last_processed_message_id,
        "total_messages": job.total_messages,
        "processed": job.processed_count,
        "changed_risk_level": job.changed_risk_count,
        "changed_category": job.changed_category_count,
        "newly_flagged": job.newly_flagged_count,
        "no_longer_flagged": job.no_longer_flagged_count,
        "skipped": job.skipped_count,
        "failed": job.failed_count,
        "started_by": job.started_by,
        "worker_id": getattr(job, "worker_id", None),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "heartbeat_at": job.heartbeat_at.isoformat() if getattr(job, "heartbeat_at", None) else None,
        "updated_at": job.updated_at.isoformat() if getattr(job, "updated_at", None) else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


async def run_reclassification(
    session_factory: Callable[[], Any],
    *,
    actor: str,
    dry_run: bool = False,
    batch_size: int = 500,
    resume_job_id: Optional[int] = None,
    max_batches: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Reclassify historical Messages in batches using the current intent-aware scorer.
    """
    scoring_ver = settings.SCORING_VERSION
    now = datetime.utcnow()
    worker = _worker_identity()

    async with session_factory() as db:
        if not dry_run:
            active = (
                await db.execute(
                    select(ReclassificationJob)
                    .where(
                        ReclassificationJob.status == "running",
                        ReclassificationJob.dry_run == False,  # noqa: E712
                    )
                    .order_by(ReclassificationJob.id.desc())
                )
            ).scalars().first()
            if active is not None and active.id != resume_job_id:
                raise ActiveReclassificationJobError(_job_summary(active))

        if resume_job_id is not None:
            job = (
                await db.execute(
                    select(ReclassificationJob).where(ReclassificationJob.id == resume_job_id)
                )
            ).scalar_one_or_none()
            if job is None:
                raise ValueError(f"ReclassificationJob {resume_job_id} not found")
            if job.status == "running" and not dry_run and job.id in _active_reclass_workers:
                raise ActiveReclassificationJobError(_job_summary(job))
            job.status = "running"
            job.dry_run = dry_run
            job.worker_id = worker
            job.heartbeat_at = now
            job.updated_at = now
        else:
            total_msgs = (await db.execute(select(func.count(Message.id)))).scalar_one() or 0
            job = ReclassificationJob(
                scoring_version=scoring_ver,
                status="running",
                dry_run=dry_run,
                last_processed_message_id=0,
                total_messages=total_msgs,
                started_by=actor,
                worker_id=worker,
                heartbeat_at=now,
                updated_at=now,
            )
            db.add(job)
        try:
            await db.flush()
        except IntegrityError:
            active = (
                await db.execute(
                    select(ReclassificationJob).where(
                        ReclassificationJob.status == "running",
                        ReclassificationJob.dry_run == False,  # noqa: E712
                    )
                )
            ).scalars().first()
            if active is not None:
                raise ActiveReclassificationJobError(_job_summary(active))
            raise
        job_id = job.id

    _active_reclass_workers.add(job_id)
    batches_run = 0
    try:
        while True:
            if max_batches is not None and batches_run >= max_batches:
                break

            async with session_factory() as db:
                job = (
                    await db.execute(
                        select(ReclassificationJob).where(ReclassificationJob.id == job_id)
                    )
                ).scalar_one()
                rows = (
                    await db.execute(
                        select(Message, Channel)
                        .join(Channel, Channel.id == Message.channel_id)
                        .where(Message.id > job.last_processed_message_id)
                        .order_by(Message.id.asc())
                        .limit(batch_size)
                    )
                ).all()

                if not rows:
                    job.status = "done"
                    job.finished_at = datetime.utcnow()
                    break

                msg_ids = [m.id for m, _ in rows]
                alerts_by_mid = {
                    a.message_id: a
                    for a in (
                        await db.execute(select(Alert).where(Alert.message_id.in_(msg_ids)))
                    ).scalars().all()
                }
                ch_names = list({ch.username for _, ch in rows})
                tg_ids = list({m.telegram_msg_id for m, _ in rows})
                em_by_key = {
                    (em.channel_username, em.telegram_message_id): em
                    for em in (
                        await db.execute(
                            select(EvidenceMessage).where(
                                EvidenceMessage.channel_username.in_(ch_names),
                                EvidenceMessage.telegram_message_id.in_(tg_ids),
                            )
                        )
                    ).scalars().all()
                }
                em_ids = [em.id for em in em_by_key.values()]
                already_em_ids = set()
                if em_ids:
                    already_em_ids = set(
                        (
                            await db.execute(
                                select(EvidenceObservation.evidence_message_id).where(
                                    EvidenceObservation.evidence_message_id.in_(em_ids),
                                    EvidenceObservation.classifier_version == scoring_ver,
                                )
                            )
                        ).scalars().all()
                    )

                for msg, ch in rows:
                    try:
                        em = em_by_key.get((ch.username, msg.telegram_msg_id))
                        if em is not None and em.id in already_em_ids:
                            job.skipped_count += 1
                            job.last_processed_message_id = msg.id
                            continue

                        combined = " ".join(
                            filter(None, [msg.text, getattr(msg, "ocr_text", None)])
                        )
                        result = classify(combined, profile="illegal_trade")

                        existing_alert = alerts_by_mid.get(msg.id)

                        old_risk = existing_alert.risk_level if existing_alert else "LOW"
                        old_cats = (
                            sorted(c.strip() for c in (existing_alert.categories or "").split(",") if c.strip())
                            if existing_alert else []
                        )
                        new_cats = sorted(result.categories)
                        was_flagged = old_risk in ("HIGH", "MEDIUM")
                        now_flagged = result.is_flagged

                        job.processed_count += 1
                        if old_risk != result.risk_level:
                            job.changed_risk_count += 1
                        if old_cats != new_cats:
                            job.changed_category_count += 1
                        if not was_flagged and now_flagged:
                            job.newly_flagged_count += 1
                        if was_flagged and not now_flagged:
                            job.no_longer_flagged_count += 1

                        if not dry_run:
                            if em is None:
                                em = await upsert_evidence_message(
                                    db,
                                    channel_username=ch.username,
                                    telegram_message_id=msg.telegram_msg_id,
                                    message_timestamp=msg.created_at,
                                    raw_text=msg.text,
                                    ocr_text=getattr(msg, "ocr_text", None),
                                    normalised_text=result.normalised_text,
                                    media_path=msg.media_path,
                                    media_hash=getattr(msg, "media_hash", None),
                                )
                            orig_h = getattr(msg, "original_text_hash", None) or compute_original_text_hash(msg.text)
                            ev_h = getattr(msg, "evidence_hash", None) or compute_evidence_hash(
                                source_platform=msg.source or "telegram",
                                channel_identifier=ch.username,
                                source_message_id=msg.telegram_msg_id,
                                post_timestamp=msg.created_at,
                                original_text_hash=orig_h,
                                media_hashes=[msg.media_hash] if getattr(msg, "media_hash", None) else [],
                            )
                            em.original_text_hash = em.original_text_hash or orig_h
                            em.evidence_hash = em.evidence_hash or ev_h

                            obs = await insert_evidence_observation(
                                db,
                                evidence_message_id=em.id,
                                source_type="reclassification",
                                score=result.score,
                                risk_level=result.risk_level,
                                severity_tier=result.severity_tier,
                                categories=json.dumps(result.categories),
                                matched_terms=json.dumps([t.get("term", "") for t in result.matched_terms]),
                                classifier_version=scoring_ver,
                            )
                            obs.observation_hash = compute_observation_hash(
                                evidence_hash=ev_h,
                                collected_at=datetime.utcnow(),
                                collector_or_batch_id=f"reclassify:{job_id}",
                            )

                            if existing_alert is not None:
                                prev_ev = {}
                                try:
                                    prev_ev = json.loads(existing_alert.evidence) if existing_alert.evidence else {}
                                except Exception:
                                    prev_ev = {}
                                legacy_cats_list = prev_ev.get("legacy_categories", old_cats)
                                new_ev = {
                                    **result.evidence,
                                    "legacy_risk_level": prev_ev.get("legacy_risk_level", old_risk),
                                    "legacy_score": prev_ev.get("legacy_score", existing_alert.score),
                                    "legacy_categories": legacy_cats_list,
                                }
                                if not existing_alert.legacy_categories and legacy_cats_list:
                                    existing_alert.legacy_categories = ",".join(legacy_cats_list)
                                existing_alert.latest_scoring_version = scoring_ver
                                existing_alert.risk_level = result.risk_level
                                existing_alert.score = result.score
                                existing_alert.categories = ",".join(result.categories)
                                existing_alert.evidence = json.dumps(new_ev, default=str)
                                if not now_flagged:
                                    existing_alert.lifecycle_state = "resolved_by_reclassification"
                                    existing_alert.resolved_at = datetime.utcnow()
                                    existing_alert.resolved_by = actor
                                    existing_alert.resolution_reason = "downgraded_to_low_by_reclassification"
                                else:
                                    existing_alert.lifecycle_state = "active"
                                    existing_alert.resolved_at = None
                                    existing_alert.resolved_by = None
                                    existing_alert.resolution_reason = None
                            elif now_flagged:
                                db.add(Alert(
                                    message_id=msg.id,
                                    risk_level=result.risk_level,
                                    score=result.score,
                                    categories=",".join(result.categories),
                                    evidence=json.dumps(result.evidence, default=str),
                                    lifecycle_state="active",
                                    latest_scoring_version=scoring_ver,
                                ))
                    except Exception as exc:
                        logger.warning("Reclassification failed for msg_id=%d: %s", msg.id, exc)
                        job.failed_count += 1

                    job.last_processed_message_id = msg.id

                batch_now = datetime.utcnow()
                job.heartbeat_at = batch_now
                job.updated_at = batch_now
                batches_run += 1
                if max_batches is not None and batches_run >= max_batches:
                    job.status = "paused"
                    break

        async with session_factory() as db:
            job = (
                await db.execute(
                    select(ReclassificationJob).where(ReclassificationJob.id == job_id)
                )
            ).scalar_one()
            summary = _job_summary(job)
            await write_audit_log(
                db,
                actor=actor,
                action="reclassification_run",
                target_type="reclassification_job",
                target_id=job_id,
                details=summary,
            )
            return summary

    except Exception as exc:
        async with session_factory() as db:
            job = (
                await db.execute(
                    select(ReclassificationJob).where(ReclassificationJob.id == job_id)
                )
            ).scalar_one_or_none()
            if job:
                job.status = "failed"
                job.error = str(exc)
                job.updated_at = datetime.utcnow()
                job.finished_at = datetime.utcnow()
        raise
    finally:
        _active_reclass_workers.discard(job_id)


async def cleanup_stale_reclassification_jobs(db: AsyncSession) -> int:
    """
    On startup, mark running jobs as 'interrupted' ONLY if their heartbeat
    (or started_at when heartbeat_at is null) is older than RECLASSIFICATION_HEARTBEAT_TIMEOUT_SECONDS
    and no active in-process worker owns them.
    """
    cutoff = datetime.utcnow() - timedelta(seconds=settings.RECLASSIFICATION_HEARTBEAT_TIMEOUT_SECONDS)
    rows = (
        await db.execute(
            select(ReclassificationJob).where(ReclassificationJob.status == "running")
        )
    ).scalars().all()
    cleaned = 0
    for job in rows:
        if job.id in _active_reclass_workers:
            continue
        last_beat = job.heartbeat_at or job.started_at
        if last_beat and last_beat < cutoff:
            job.status = "interrupted"
            job.updated_at = datetime.utcnow()
            job.finished_at = datetime.utcnow()
            job.error = "Interrupted (stale heartbeat at startup)"
            cleaned += 1
    if cleaned:
        await db.flush()
    return cleaned


async def recover_stale_reclassification_job(
    db: AsyncSession,
    *,
    job_id: int,
    actor: str,
    confirm: bool,
    target_status: str = "interrupted",
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Explicit, operator-confirmed recovery for a stale/orphaned ReclassificationJob.
    Refuses if confirm is False or if an active worker with a fresh heartbeat owns it.
    """
    if not confirm:
        raise ValueError("Explicit operator confirmation (confirm=true) is required")
    if target_status not in ("interrupted", "failed", "superseded"):
        raise ValueError(f"Invalid target_status {target_status!r}")

    job = (
        await db.execute(select(ReclassificationJob).where(ReclassificationJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        raise ValueError(f"ReclassificationJob {job_id} not found")
    if job.status != "running":
        raise ValueError(f"ReclassificationJob #{job_id} is already '{job.status}', not 'running'")

    cutoff = datetime.utcnow() - timedelta(seconds=settings.RECLASSIFICATION_HEARTBEAT_TIMEOUT_SECONDS)
    last_beat = job.heartbeat_at or job.started_at
    if job.id in _active_reclass_workers or (last_beat and last_beat >= cutoff):
        raise ValueError(
            f"ReclassificationJob #{job_id} has a recent heartbeat or active worker; cannot recover"
        )

    now = datetime.utcnow()
    job.status = target_status
    job.updated_at = now
    job.finished_at = now
    job.error = reason or f"Recovered by operator ({actor}) as {target_status}"
    await db.flush()

    summary = _job_summary(job)
    await write_audit_log(
        db,
        actor=actor,
        action="reclassification_job_recover",
        target_type="reclassification_job",
        target_id=job.id,
        details={"target_status": target_status, "reason": job.error, "processed": job.processed_count},
    )
    return summary


async def backfill_alert_lifecycle(db: AsyncSession, *, actor: str = "stage_b_migration") -> Dict[str, Any]:
    """
    Idempotent migration for existing Alert rows:
    - Downgraded LOW alerts -> lifecycle_state='resolved_by_reclassification' with resolved_at/by/reason.
    - Blank categories preserve legacy_categories from evidence JSON if present.
    - Active HIGH/MEDIUM alerts get latest_scoring_version populated.
    """
    now = datetime.utcnow()
    alerts = (await db.execute(select(Alert))).scalars().all()
    resolved_count = 0
    legacy_cats_preserved = 0
    active_updated = 0

    for a in alerts:
        ev = {}
        try:
            ev = json.loads(a.evidence) if a.evidence else {}
        except Exception:
            ev = {}

        scoring_ver = ev.get("scoring_version") or a.latest_scoring_version or settings.SCORING_VERSION
        if not a.legacy_categories:
            leg = ev.get("legacy_categories")
            if isinstance(leg, list) and leg:
                a.legacy_categories = ",".join(str(x) for x in leg if str(x).strip())
                legacy_cats_preserved += 1

        if a.risk_level == "LOW":
            if a.lifecycle_state != "resolved_by_reclassification":
                a.lifecycle_state = "resolved_by_reclassification"
                a.resolved_at = a.resolved_at or now
                a.resolved_by = a.resolved_by or actor
                a.resolution_reason = a.resolution_reason or "downgraded_to_low_by_reclassification"
                a.latest_scoring_version = scoring_ver
                resolved_count += 1
        else:
            if not a.latest_scoring_version:
                a.latest_scoring_version = scoring_ver
                active_updated += 1

    counts = {
        "total_alerts": len(alerts),
        "resolved_by_reclassification": resolved_count,
        "legacy_categories_preserved": legacy_cats_preserved,
        "active_updated": active_updated,
    }
    await write_audit_log(
        db,
        actor=actor,
        action="alert_lifecycle_backfill",
        target_type="alert",
        details=counts,
    )
    await db.flush()
    return counts

