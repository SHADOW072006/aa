import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import ChannelScanResult, ScanJob
from app.reports.pdf_generator import generate_channel_dossier_pdf, generate_scan_job_pdf
from app.services.retention_service import require_api_token, write_audit_log

def _build_risk_explanation(r) -> str:
    """One-line explanation of why this channel was rated HIGH/MEDIUM/LOW."""
    import json as _jj
    risk = r.risk_level
    high_c = r.high_count
    med_c = r.medium_count
    avg_s = round(r.avg_score * 100, 1)
    total = r.messages_scanned
    cats = []
    try:
        cats = _jj.loads(r.top_categories) if r.top_categories else []
    except Exception:
        pass
    cat_str = ', '.join(cats[:3]) if cats else 'no categories'
    if risk == 'HIGH':
        return (f'{high_c} HIGH-scored messages in {total} scanned '
                f'(avg {avg_s}%). Categories: {cat_str}.')
    if risk == 'MEDIUM':
        return (f'{high_c} HIGH + {med_c} MEDIUM in {total} scanned '
                f'(avg {avg_s}%). Categories: {cat_str}.')
    return f'avg score {avg_s}% across {total} messages. Categories: {cat_str}.'

router = APIRouter(prefix="/scan", tags=["scan"])


class ScanRequest(BaseModel):
    seed_terms: Optional[List[str]] = None
    mode: Optional[str] = None  # review (default) or auto
    profile: str = "illegal_trade"


def _serialise_job(job: ScanJob) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "seed_terms": json.loads(job.seed_terms) if job.seed_terms else [],
        "total_channels_found": job.total_channels_found,
        "total_channels_scanned": job.total_channels_scanned,
        "total_messages_scanned": job.total_messages_scanned,
        "total_flagged": job.total_flagged,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "created_at": job.created_at.isoformat(),
        "error": job.error,
    }


def _serialise_result(r: ChannelScanResult) -> dict:
    return {
        "id": r.id,
        "scan_job_id": r.scan_job_id,
        "channel_username": r.channel_username,
        "channel_title": r.channel_title,
        "channel_description": getattr(r, "channel_description", None),
        "telegram_id": r.telegram_id,
        "member_count": r.member_count,
        "is_verified": getattr(r, "is_verified", False),
        "is_scam": getattr(r, "is_scam", False),
        "invite_link": getattr(r, "invite_link", None) or f"https://t.me/{r.channel_username}",
        "messages_scanned": r.messages_scanned,
        "flagged_count": r.flagged_count,
        "high_count": r.high_count,
        "medium_count": r.medium_count,
        "avg_score": r.avg_score,
        "top_categories": json.loads(r.top_categories) if r.top_categories else [],
        "top_identifiers": json.loads(r.top_identifiers) if r.top_identifiers else [],
        "sample_messages": json.loads(r.sample_messages) if r.sample_messages else [],
        "connected_nodes": json.loads(r.connected_nodes) if getattr(r, "connected_nodes", None) else {},
        "risk_level": r.risk_level,
        "severity_tier": getattr(r, "severity_tier", "LOW") or "LOW",
        "is_serious": bool(getattr(r, "is_serious", False)),
        "seed_term": r.seed_term,
        "already_monitored": r.already_monitored,
        "scanned_at": r.scanned_at.isoformat(),
        "composite_score": getattr(r, "composite_score", None),
        "risk_explanation": _build_risk_explanation(r),
    }


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
async def run_scan(
    payload: ScanRequest,
    _actor: str = Depends(require_api_token),
):
    """
    Trigger a public channel scan. Runs in background.
    Returns immediately with job_id.
    If seed_terms is null/empty, uses the default illegal-trade seed catalogue (62 seeds).
    """
    from app.collectors.scanner import trigger_scan
    job_id = await trigger_scan(payload.seed_terms or None, mode=payload.mode, profile=payload.profile)
    return {"job_id": job_id, "status": "running", "profile": payload.profile, "message": "Scan started in background"}


@router.get("/jobs")
async def list_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ScanJob).order_by(ScanJob.created_at.desc()).offset(skip).limit(limit)
    )
    jobs = result.scalars().all()
    return [_serialise_job(j) for j in jobs]


@router.get("/jobs/{job_id}")
async def get_job(job_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ScanJob).where(ScanJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Scan job not found")
    return _serialise_job(job)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: int,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a running or stuck scan job."""
    from datetime import datetime
    from app.collectors.scanner import _active_tasks
    result = await db.execute(select(ScanJob).where(ScanJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Scan job not found")
    task = _active_tasks.pop(job_id, None)
    if task and not task.done():
        task.cancel()
    if job.status in ("running", "pending"):
        job.status = "interrupted"
        job.finished_at = datetime.utcnow()
        job.error = "Cancelled by analyst"
        await db.commit()
    return _serialise_job(job)


@router.get("/jobs/{job_id}/results")
async def get_job_results(
    job_id: int,
    risk_level: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    serious_only: Optional[bool] = Query(False),
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    q = select(ChannelScanResult).where(ChannelScanResult.scan_job_id == job_id)
    if risk_level:
        q = q.where(ChannelScanResult.risk_level == risk_level.upper())
    if severity:
        q = q.where(ChannelScanResult.severity_tier == severity.upper())
    if serious_only:
        q = q.where(ChannelScanResult.is_serious == True)
    if category:
        q = q.where(ChannelScanResult.top_categories.like(f"%{category}%"))
    if search:
        s = f"%{search.strip()}%"
        q = q.where(
            or_(
                ChannelScanResult.channel_username.like(s),
                ChannelScanResult.channel_title.like(s),
                ChannelScanResult.seed_term.like(s),
            )
        )
    q = q.order_by(ChannelScanResult.avg_score.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    rows = result.scalars().all()
    return [_serialise_result(r) for r in rows]


@router.get("/jobs/{job_id}/export/pdf")
async def export_job_pdf(
    job_id: int,
    actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Export complete PDF forensic threat report for a Scan Job."""
    job_res = await db.execute(select(ScanJob).where(ScanJob.id == job_id))
    job = job_res.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Scan job not found")

    res = await db.execute(
        select(ChannelScanResult)
        .where(ChannelScanResult.scan_job_id == job_id)
        .order_by(ChannelScanResult.avg_score.desc())
    )
    results = [_serialise_result(r) for r in res.scalars().all()]

    pdf_bytes = generate_scan_job_pdf(_serialise_job(job), results)
    await write_audit_log(db, actor=actor, action="pdf_export", target_type="scan_job", target_id=job_id)
    await db.commit()
    filename = f"telemonitor_scan_job_{job_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.get("/results/{result_id}/export/pdf")
async def export_result_pdf(
    result_id: int,
    actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Export individual Channel Intelligence PDF Dossier from a scan result."""
    result = await db.execute(
        select(ChannelScanResult).where(ChannelScanResult.id == result_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Result not found")

    res_dict = _serialise_result(row)
    pdf_bytes = generate_channel_dossier_pdf(res_dict)
    await write_audit_log(db, actor=actor, action="pdf_export", target_type="scan_result", target_id=result_id)
    await db.commit()
    filename = f"telemonitor_{row.channel_username}_dossier.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.get("/results/{result_id}")
async def get_result(
    result_id: int,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ChannelScanResult).where(ChannelScanResult.id == result_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Result not found")
    return _serialise_result(row)


@router.post("/jobs/{job_id}/add-channel/{result_id}", status_code=status.HTTP_201_CREATED)
async def add_channel_from_result(
    job_id: int,
    result_id: int,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Force-add a discovered channel to the watchlist."""
    result = await db.execute(
        select(ChannelScanResult).where(
            ChannelScanResult.id == result_id,
            ChannelScanResult.scan_job_id == job_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Result not found")
    from app.db.crud import upsert_channel
    ch = await upsert_channel(
        db,
        username=row.channel_username,
        telegram_id=row.telegram_id,
        title=row.channel_title,
    )
    row.already_monitored = True
    return {"channel_id": ch.id, "username": ch.username, "is_active": ch.is_active}


@router.get("/seeds")
async def get_default_seeds(
    profile: str = Query("illegal_trade"),
    db: AsyncSession = Depends(get_db),
):
    """Return active seed terms and category distribution from the actual DB profile."""
    from collections import Counter
    from app.db.crud import list_seed_profiles
    rows = list(
        await list_seed_profiles(
            db, is_active=True, profile=profile, status="active", limit=1000
        )
    )
    seeds = [r.seed_text for r in rows]
    by_category = dict(Counter(r.threat_category for r in rows))
    return {
        "count": len(seeds),
        "profile": profile,
        "by_category": by_category,
        "seeds": seeds,
    }

# ── Clear / Reset endpoint ────────────────────────────────────────────────────

class ClearDataRequest(BaseModel):
    confirm: str  # must equal "CLEAR" to execute

@router.delete("/clear", status_code=200)
async def clear_all_scan_data(
    payload: ClearDataRequest,
    actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete all scan jobs, channel scan results, messages, alerts, identifiers,
    entity links, and scan evidence.  Channels (watchlist) are preserved.

    Requires body: {"confirm": "CLEAR"}
    """
    if payload.confirm != "CLEAR":
        raise HTTPException(400, detail='Send {"confirm": "CLEAR"} to proceed.')
    await write_audit_log(db, actor=actor, action="scan_clear", target_type="system")

    from sqlalchemy import text, delete
    from app.db.models import (
        Alert, DispositionHistory, EntityLink, Identifier,
        Message, ScanJob, ChannelScanResult, ScanEvidence,
        PivotCandidate, ChannelScoreComponents, ChannelHealthEvent,
        QueryVariantExecution,
    )

    # Order matters — delete children before parents
    for model in [
        DispositionHistory,
        ScanEvidence,
        PivotCandidate,
        ChannelScoreComponents,
        ChannelHealthEvent,
        QueryVariantExecution,
        Alert,
        EntityLink,
        Identifier,
        ChannelScanResult,
        Message,
        ScanJob,
    ]:
        await db.execute(delete(model))

    # Reset channel stats so they look fresh
    from app.db.models import Channel
    await db.execute(
        text(
            "UPDATE channels SET last_fetched_at=NULL, last_message_id=0, "
            "consecutive_error_count=0, error_state=0, last_poll_attempted_at=NULL"
        )
    )

    await db.commit()
    return {"status": "cleared", "message": "All scan data deleted. Channels preserved."}
