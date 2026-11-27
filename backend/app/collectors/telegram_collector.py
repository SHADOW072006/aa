"""
Telegram collector — MTProto-based message collector with OCR support.

Changes from v1:
- OCR: images from flagged (or media-only) messages are run through EasyOCR;
  extracted text is classified and identifiers extracted just like message text.
- OCR text is appended to the message record and merged with the original text
  for classification so a poster image with no text body is still scored.

Changes from v2 (intelligence-platform upgrade):
- Poll tier–based interval selection (HIGH/MEDIUM/LOW).
- FloodWait handling with exponential backoff and health event recording.
- Error state tracking: consecutive_error_count, error_state, last_poll_attempted_at.
- OCR gating: OCR only runs for HIGH/MEDIUM tier channels that are not in error_state.

Changes from v3 (scheduler-and-evidence-model):
- Removed run_forever(), _poll_all_channels(), _collect_channel_with_backoff().
  Scheduling and backoff are now owned by ChannelScheduler in scheduler.py.
  TelegramCollector only manages the Telegram client and per-channel collection.

Requirements: 1, 5, 14.1, 14.2, 14.3, 15.1, 15.2, 15.3
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional

from telethon import TelegramClient
from telethon.sessions import SQLiteSession
from telethon.tl.types import Message as TelegramMessage

from app.classifiers.classifier import classify
from app.core.config import settings
from app.db.crud import (
    get_message_by_channel_and_id,
    insert_evidence_observation,
    mark_channel_fetched,
    record_health_event,
    save_alert,
    save_identifiers,
    save_message,
    upsert_channel,
    upsert_entity_link,
    upsert_evidence_message,
)
from app.db.database import get_session
from app.db.models import Alert, Identifier, Message
from app.extractors.identifier_extractor import extract, is_contact_identifier
from app.extractors.ocr import extract_text_from_image
from app.services.evidence_hashing import (
    compute_evidence_hash,
    compute_media_hash,
    compute_observation_hash,
    compute_original_text_hash,
)

logger = logging.getLogger(__name__)

MEDIA_DIR = Path("./media")
MEDIA_DIR.mkdir(exist_ok=True)

# Poll tier → interval in seconds (Requirement 14.1)
POLL_INTERVALS = {
    "HIGH": settings.POLL_INTERVAL_HIGH,     # 30 s
    "MEDIUM": settings.POLL_INTERVAL_MEDIUM, # 60 s
    "LOW": settings.POLL_INTERVAL_LOW,       # 300 s
}


class _WALSQLiteSession(SQLiteSession):
    """SQLiteSession with WAL mode and 30s busy_timeout to reduce lock contention."""

    def _cursor(self):
        conn = self._conn
        if conn is None:
            import sqlite3
            self._conn = sqlite3.connect(self.filename, check_same_thread=False, timeout=30.0)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=30000")
        return super()._cursor()


class TelegramCollector:
    def __init__(self) -> None:
        self.client = TelegramClient(
            _WALSQLiteSession(settings.TELEGRAM_SESSION_FILE),
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
        )
        self._running = False

    async def start(self) -> None:
        await self.client.start(phone=settings.TELEGRAM_PHONE)
        logger.info("Telegram client connected.")

    async def stop(self) -> None:
        self._running = False
        await self.client.disconnect()
        logger.info("Telegram client disconnected.")

    async def _collect_channel(self, channel_row) -> None:
        entity = await self.client.get_entity(channel_row.username)
        messages: List[TelegramMessage] = []
        async for msg in self.client.iter_messages(
            entity,
            min_id=channel_row.last_message_id,
            limit=200,
            reverse=True,
        ):
            if isinstance(msg, TelegramMessage):
                messages.append(msg)

        if not messages:
            return

        logger.info("Channel %s: %d new messages", channel_row.username, len(messages))
        last_id = channel_row.last_message_id
        for tg_msg in messages:
            last_id = max(last_id, tg_msg.id)
            await self._process_message(tg_msg, channel_row)

        async with get_session() as db:
            await mark_channel_fetched(db, channel_row.id, last_id)

    async def _process_message(self, tg_msg: TelegramMessage, channel_row) -> None:
        text = tg_msg.message or ""
        has_media = bool(tg_msg.media)

        if not text.strip() and not has_media:
            return

        # ── OCR gating (Requirement 15.1 / 15.2 / 15.3) ─────────────────────
        # OCR only runs for HIGH/MEDIUM tier channels that are not in error_state.
        poll_tier = getattr(channel_row, "poll_tier", "LOW") or "LOW"
        error_state = getattr(channel_row, "error_state", False) or False

        media_path: Optional[str] = None
        ocr_text: Optional[str] = None
        ocr_skip_reason: Optional[str] = None

        if has_media:
            if poll_tier in ("HIGH", "MEDIUM") and not error_state:
                # Requirement 15.1: perform OCR only when tier warrants it
                media_path = await self._download_media(tg_msg, channel_row.username)
                if media_path:
                    ocr_text = await extract_text_from_image(media_path)
                    if ocr_text:
                        logger.debug(
                            "OCR on %s/%d: %d chars",
                            channel_row.username, tg_msg.id, len(ocr_text),
                        )
            else:
                # Requirement 15.2 / 15.3: skip OCR — record reason
                ocr_skip_reason = (
                    "poll_tier_low" if poll_tier == "LOW" else "error_state"
                )
                logger.debug(
                    "OCR skipped on %s/%d — %s",
                    channel_row.username, tg_msg.id, ocr_skip_reason,
                )

        # Merge text + OCR ONLY for classification/extraction; never overwrite raw original text
        combined = " ".join(filter(None, [text, ocr_text]))
        if not combined.strip():
            return

        result = classify(combined)
        orig_text_hash = compute_original_text_hash(text)
        m_hash = compute_media_hash(media_path) if media_path else None

        # If not flagged, delete media to save space (keep only flagged)
        if not result.is_flagged and media_path:
            try:
                Path(media_path).unlink(missing_ok=True)
            except Exception:
                pass
            media_path = None

        ev_hash = compute_evidence_hash(
            source_platform="telegram",
            channel_identifier=channel_row.username,
            source_message_id=tg_msg.id,
            post_timestamp=tg_msg.date,
            original_text_hash=orig_text_hash,
            media_hashes=[m_hash] if m_hash else [],
        )
        from datetime import datetime as _dt
        obs_hash = compute_observation_hash(
            evidence_hash=ev_hash,
            collected_at=_dt.utcnow(),
            collector_or_batch_id="telegram_collector",
        )
        ocr_status = (
            "success" if ocr_text
            else "skipped" if ocr_skip_reason
            else ("failed" if has_media and media_path else "not_applicable")
        )

        new_msg = Message(
            channel_id=channel_row.id,
            telegram_msg_id=tg_msg.id,
            sender_id=tg_msg.sender_id,
            sender_username=getattr(getattr(tg_msg, "sender", None), "username", None),
            text=text,  # preserve original text untouched
            text_hash=Message.compute_hash(combined),
            original_text_hash=orig_text_hash,
            evidence_hash=ev_hash,
            media_hash=m_hash,
            provenance_status="verified_hashes",
            ocr_text=ocr_text,
            ocr_status=ocr_status,
            ocr_skip_reason=ocr_skip_reason,
            has_media=has_media,
            media_path=media_path,
            created_at=tg_msg.date,
            source="telegram",
        )

        async with get_session() as db:
            from sqlalchemy import select as _select
            # Historical imports can contain duplicate hashes.  A duplicate must
            # be treated as an existing observation, never as a collector error.
            existing = (
                await db.execute(
                    _select(Message)
                    .where(Message.evidence_hash == ev_hash)
                    .order_by(Message.id.desc())
                )
            ).scalars().first()
            if existing is None:
                existing = await get_message_by_channel_and_id(
                    db, channel_row.id, tg_msg.id
                )
            if existing is None and orig_text_hash is not None:
                existing = (
                    await db.execute(
                        _select(Message)
                        .where(
                            Message.channel_id == channel_row.id,
                            Message.original_text_hash == orig_text_hash,
                        )
                        .order_by(Message.id.desc())
                    )
                ).scalars().first()
            if existing:
                ev_msg = await upsert_evidence_message(
                    db,
                    channel_username=channel_row.username,
                    telegram_message_id=existing.telegram_msg_id,
                    message_timestamp=tg_msg.date,
                    raw_text=text,
                    ocr_text=ocr_text,
                    media_path=media_path,
                    media_hash=m_hash,
                    ocr_outcome=ocr_status,
                    ocr_skip_reason=ocr_skip_reason,
                )
                ev_msg.original_text_hash = ev_msg.original_text_hash or orig_text_hash
                ev_msg.evidence_hash = ev_msg.evidence_hash or ev_hash
                obs = await insert_evidence_observation(
                    db,
                    evidence_message_id=ev_msg.id,
                    source_type="continuous_monitor",
                    score=result.score,
                    risk_level=result.risk_level,
                    severity_tier=result.severity_tier,
                    categories=json.dumps(result.categories),
                    matched_terms=json.dumps([t.get("term", "") for t in result.matched_terms]),
                )
                obs.observation_hash = obs_hash
                return

            saved_msg = await save_message(db, new_msg)
            from app.services.minhash_service import get_minhash_index
            # Near-duplicate identity is caption-level (see import_handler).
            sig_str, _ = get_minhash_index().add_message(saved_msg.id, channel_row.id, tg_msg.message or "")
            if sig_str:
                saved_msg.minhash_sig = sig_str

            # Extract identifiers from combined text
            identifiers = [
                Identifier(
                    message_id=saved_msg.id,
                    type=ident.type,
                    value=ident.value,
                    normalised=ident.normalised,
                )
                for ident in extract(combined)
            ]
            if identifiers:
                await save_identifiers(db, identifiers)
                # Only actor identifiers (phone/UPI/handle/wallet/...) are
                # linked; urls and locations are evidence, not identity.
                linkable = [i for i in identifiers if is_contact_identifier(i.type)]
                for i in range(len(linkable)):
                    for j in range(i + 1, len(linkable)):
                        await upsert_entity_link(db, linkable[i].id, linkable[j].id)

            # Single unified EvidenceMessage + EvidenceObservation write per collection event
            if result.is_flagged or result.score >= settings.MEDIUM_RISK_THRESHOLD * 0.5:
                try:
                    ev_msg = await upsert_evidence_message(
                        db,
                        channel_username=channel_row.username,
                        telegram_message_id=tg_msg.id,
                        message_timestamp=tg_msg.date,
                        raw_text=tg_msg.message or "",
                        ocr_text=ocr_text,
                        normalised_text=result.normalised_text,
                        media_path=media_path,
                        media_hash=m_hash,
                        ocr_outcome=ocr_status,
                        ocr_skip_reason=ocr_skip_reason,
                    )
                    ev_msg.original_text_hash = ev_msg.original_text_hash or orig_text_hash
                    ev_msg.evidence_hash = ev_msg.evidence_hash or ev_hash
                    ev_msg.provenance_status = ev_msg.provenance_status or "verified_hashes"
                    obs = await insert_evidence_observation(
                        db,
                        evidence_message_id=ev_msg.id,
                        source_type="continuous_monitor",
                        score=result.score,
                        risk_level=result.risk_level,
                        severity_tier=result.severity_tier,
                        categories=json.dumps(result.categories),
                        matched_terms=json.dumps(
                            [t.get("term", "") for t in result.evidence.get("matched_terms", [])]
                            if result.evidence else []
                        ),
                        classifier_version=settings.SCORING_VERSION,
                    )
                    obs.observation_hash = obs_hash
                except Exception as _ev_exc:
                    logger.warning(
                        "Failed to write evidence_v2 for @%s msg %d: %s",
                        channel_row.username, tg_msg.id, _ev_exc,
                    )

            if result.is_flagged:
                alert = Alert(
                    message_id=saved_msg.id,
                    risk_level=result.risk_level,
                    score=result.score,
                    categories=",".join(result.categories),
                    evidence=json.dumps(
                        {
                            **result.evidence,
                            "ocr_used": ocr_text is not None,
                            "ocr_skip_reason": ocr_skip_reason,
                        },
                        default=str,
                    ),
                )
                await save_alert(db, alert)
                logger.info(
                    "ALERT %s | %.2f | @%s | msg %d%s",
                    result.risk_level, result.score,
                    channel_row.username, tg_msg.id,
                    " [OCR]" if ocr_text else "",
                )

    async def _download_media(self, tg_msg: TelegramMessage, channel_username: str) -> Optional[str]:
        try:
            channel_dir = MEDIA_DIR / channel_username
            channel_dir.mkdir(parents=True, exist_ok=True)
            path = await self.client.download_media(tg_msg, file=str(channel_dir))
            return str(path) if path else None
        except Exception as exc:
            logger.debug("Media download failed: %s", exc)
            return None


_collector: Optional[TelegramCollector] = None


def get_collector() -> TelegramCollector:
    global _collector
    if _collector is None:
        _collector = TelegramCollector()
    return _collector
