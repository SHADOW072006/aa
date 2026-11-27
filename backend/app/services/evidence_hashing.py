"""
Canonical Evidence Hashing & Chain-of-Custody Verification.

Canonical serialisation specification:
- original_text_hash : SHA-256 hex digest of UTF-8 encoded raw original text
                       (None for media-only posts where raw text is empty).
- media_hash         : SHA-256 hex digest of raw bytes of a downloaded media file.
- evidence_hash      : SHA-256 hex digest of UTF-8 canonical JSON
                       (keys sorted, separators=(',', ':')) of:
                       {
                         "channel_id_or_username": str,
                         "media_hashes": sorted list[str],
                         "original_text_hash": str | None,
                         "post_timestamp": str | None (UTC ISO-8601),
                         "source_message_id": int,
                         "source_platform": str
                       }
- observation_hash   : SHA-256 hex digest of UTF-8 canonical JSON
                       (keys sorted, separators=(',', ':')) of:
                       {
                         "collected_at": str (UTC ISO-8601),
                         "collector_or_batch_id": str,
                         "evidence_hash": str
                       }
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _to_utc_iso(ts: Optional[datetime]) -> Optional[str]:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    return ts.isoformat()


def compute_original_text_hash(text: Optional[str]) -> Optional[str]:
    """SHA-256 of original text; None for media-only / empty posts."""
    if not text or not text.strip():
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_media_hash(file_path: str | Path) -> Optional[str]:
    """SHA-256 of a local media file's raw bytes, or None if missing."""
    p = Path(file_path)
    if not p.exists() or not p.is_file():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_evidence_hash(
    *,
    source_platform: str,
    channel_identifier: str,
    source_message_id: int,
    post_timestamp: Optional[datetime],
    original_text_hash: Optional[str],
    media_hashes: Optional[List[str]] = None,
) -> str:
    manifest = {
        "channel_id_or_username": str(channel_identifier),
        "media_hashes": sorted(m for m in (media_hashes or []) if m),
        "original_text_hash": original_text_hash,
        "post_timestamp": _to_utc_iso(post_timestamp),
        "source_message_id": int(source_message_id),
        "source_platform": str(source_platform),
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_observation_hash(
    *,
    evidence_hash: str,
    collected_at: datetime,
    collector_or_batch_id: str,
) -> str:
    payload = {
        "collected_at": _to_utc_iso(collected_at),
        "collector_or_batch_id": str(collector_or_batch_id),
        "evidence_hash": str(evidence_hash),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


UNVERIFIABLE_MEDIA_NOTE = "Original media unavailable; provenance cannot be fully recomputed."


def provenance_note_for_status(
    provenance_status: Optional[str],
    verification_status: Optional[str] = None,
) -> Optional[str]:
    """Return human-readable provenance guidance without overclaiming verification."""
    if provenance_status == "unverifiable_media" or verification_status == "unavailable":
        return UNVERIFIABLE_MEDIA_NOTE
    if provenance_status == "missing_content":
        return "Original content unavailable; provenance cannot be recomputed."
    if verification_status == "not_backfilled":
        return "Provenance hashes have not been backfilled for this record."
    if verification_status == "mismatch":
        return "Recomputed hash does not match stored provenance hash."
    if provenance_status == "verified_hashes" or verification_status == "verified":
        return "All available text, media, and manifest hashes verified."
    if provenance_status == "hash_backfilled":
        return "Provenance hashes backfilled from retained record."
    return None


def verify_record_hashes(
    *,
    raw_text: Optional[str],
    stored_original_text_hash: Optional[str],
    media_path: Optional[str],
    stored_media_hash: Optional[str],
    source_platform: str,
    channel_identifier: str,
    source_message_id: int,
    post_timestamp: Optional[datetime],
    stored_evidence_hash: Optional[str],
    has_media: bool = False,
    stored_provenance_status: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Recompute hashes and report explicit chain-of-custody verification status:
    - verified: all expected hashes present and match recomputed values
    - mismatch: hashes present and recomputed values differ
    - unavailable: media or raw text required for full verification is unavailable/purged
    - not_backfilled: stored evidence_hash is missing
    """
    recomputed_text_hash = compute_original_text_hash(raw_text)
    if raw_text and raw_text.strip():
        text_match: Optional[bool] = (recomputed_text_hash == stored_original_text_hash)
    elif stored_original_text_hash is None and not raw_text:
        text_match = True
    else:
        text_match = None

    recomputed_media_hash = compute_media_hash(media_path) if media_path else None
    media_expected = bool(has_media or stored_media_hash or media_path)
    if media_expected:
        if stored_media_hash and recomputed_media_hash is not None:
            media_match: Optional[bool] = (recomputed_media_hash == stored_media_hash)
        else:
            media_match = None  # media unavailable / purged on disk
    else:
        media_match = True

    eff_media = [stored_media_hash] if stored_media_hash else []
    recomputed_ev_hash = compute_evidence_hash(
        source_platform=source_platform,
        channel_identifier=channel_identifier,
        source_message_id=source_message_id,
        post_timestamp=post_timestamp,
        original_text_hash=recomputed_text_hash,
        media_hashes=eff_media,
    )
    evidence_match = (
        recomputed_ev_hash == stored_evidence_hash
        if stored_evidence_hash is not None
        else False
    )

    if media_expected and media_match is None:
        verification_status = "unavailable"
        overall_match = False
    elif text_match is None:
        verification_status = "unavailable"
        overall_match = False
    elif stored_evidence_hash is None:
        verification_status = "not_backfilled"
        overall_match = False
    elif text_match and evidence_match and (media_match is True):
        verification_status = "verified"
        overall_match = True
    else:
        verification_status = "mismatch"
        overall_match = False

    note = provenance_note_for_status(stored_provenance_status, verification_status)

    return {
        "verification_status": verification_status,
        "provenance_status": stored_provenance_status,
        "provenance_note": note,
        "overall_match": overall_match,
        "text_hash_match": text_match,
        "media_hash_match": media_match,
        "evidence_hash_match": evidence_match,
        "stored_original_text_hash": stored_original_text_hash,
        "recomputed_original_text_hash": recomputed_text_hash,
        "stored_media_hash": stored_media_hash,
        "recomputed_media_hash": recomputed_media_hash,
        "stored_evidence_hash": stored_evidence_hash,
        "recomputed_evidence_hash": recomputed_ev_hash,
    }


async def backfill_provenance_hashes(
    db,
    *,
    actor: str = "backfill_job",
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Safely backfill provenance hashes on historical Message and EvidenceMessage rows
    ONLY when retained evidence is available. Never invents hashes for missing content
    or unavailable media; marks gaps explicitly as 'missing_content' or 'unverifiable_media'.
    """
    from sqlalchemy import select
    from app.db.models import Channel, EvidenceMessage, Message
    from app.services.retention_service import write_audit_log

    rows = (
        await db.execute(
            select(Message, Channel)
            .join(Channel, Channel.id == Message.channel_id)
            .where((Message.evidence_hash.is_(None)) | (Message.provenance_status.is_(None)))
        )
    ).all()

    counts = {
        "dry_run": dry_run,
        "checked": len(rows),
        "backfilled": 0,
        "already_complete": 0,
        "unverifiable_media": 0,
        "missing_content": 0,
    }

    for msg, ch in rows:
        if msg.provenance_status is not None or (msg.evidence_hash and msg.provenance_status):
            counts["already_complete"] += 1
            continue

        has_text = bool(msg.text and msg.text.strip())
        m_hash = msg.media_hash
        if msg.has_media and not m_hash and msg.media_path:
            m_hash = compute_media_hash(msg.media_path)

        if msg.has_media and not m_hash:
            counts["unverifiable_media"] += 1
            if not dry_run:
                msg.provenance_status = "unverifiable_media"
                if has_text and not msg.original_text_hash:
                    msg.original_text_hash = compute_original_text_hash(msg.text)
            continue

        if not has_text and not m_hash:
            counts["missing_content"] += 1
            if not dry_run:
                msg.provenance_status = "missing_content"
            continue

        orig_h = msg.original_text_hash or (compute_original_text_hash(msg.text) if has_text else None)
        ev_h = msg.evidence_hash or compute_evidence_hash(
            source_platform=msg.source or "telegram",
            channel_identifier=ch.username,
            source_message_id=msg.telegram_msg_id,
            post_timestamp=msg.created_at,
            original_text_hash=orig_h,
            media_hashes=[m_hash] if m_hash else [],
        )
        counts["backfilled"] += 1
        if not dry_run:
            msg.original_text_hash = orig_h
            msg.media_hash = m_hash
            msg.evidence_hash = ev_h
            msg.provenance_status = "hash_backfilled"

    # Also sync EvidenceMessage rows missing evidence_hash / provenance_status
    em_rows = (
        await db.execute(
            select(EvidenceMessage).where(
                (EvidenceMessage.evidence_hash.is_(None)) | (EvidenceMessage.provenance_status.is_(None))
            )
        )
    ).scalars().all()
    em_backfilled = 0
    for em in em_rows:
        if em.provenance_status is not None:
            continue
        has_raw = bool(em.raw_text and em.raw_text.strip())
        m_h = em.media_hash or (compute_media_hash(em.media_path) if em.media_path else None)
        if not has_raw and not m_h:
            if not dry_run:
                em.provenance_status = "missing_content"
            continue
        orig_h = em.original_text_hash or (compute_original_text_hash(em.raw_text) if has_raw else None)
        ev_h = em.evidence_hash or compute_evidence_hash(
            source_platform="telegram",
            channel_identifier=em.channel_username,
            source_message_id=em.telegram_message_id,
            post_timestamp=em.message_timestamp,
            original_text_hash=orig_h,
            media_hashes=[m_h] if m_h else [],
        )
        em_backfilled += 1
        if not dry_run:
            em.original_text_hash = orig_h
            em.media_hash = m_h
            em.evidence_hash = ev_h
            em.provenance_status = "hash_backfilled"

    counts["evidence_messages_backfilled"] = em_backfilled
    if not dry_run:
        await write_audit_log(
            db,
            actor=actor,
            action="hash_backfill",
            target_type="system",
            details=counts,
        )
        await db.flush()

    return counts

