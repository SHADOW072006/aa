"""
CSV / JSON import handler with canonical evidence hashing, deduplication,
observation recording, and ImportBatch tracking.

Also provides a write-nothing preview (validate_rows) used by
POST /import/validate so unknown datasets can be inspected before import.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select

from app.classifiers.classifier import classify
from app.core.config import settings
from app.db.crud import (
    insert_evidence_observation,
    save_alert,
    save_identifiers,
    save_message,
    upsert_channel,
    upsert_entity_link,
    upsert_evidence_message,
)
from app.db.database import get_session
from app.db.models import Alert, Identifier, ImportBatch, Message
from app.extractors.identifier_extractor import extract, is_contact_identifier
from app.extractors.ocr import extract_text_from_image
from app.services.evidence_hashing import (
    compute_evidence_hash,
    compute_media_hash,
    compute_observation_hash,
    compute_original_text_hash,
)
from app.services.minhash_service import get_minhash_index

logger = logging.getLogger(__name__)

_TEXT_COLS = ("text", "message", "content", "post", "body")
_CHANNEL_COLS = ("channel", "source", "group", "chat", "author", "platform", "account", "page")
_DATE_COLS = ("created_at", "timestamp", "date", "time", "sent_at", "posted_at", "posted_at_ist",
              "post_date", "datetime")
_SENDER_COLS = ("sender", "username", "user", "from", "author")
_ID_COLS = ("message_id", "msg_id", "id", "post_id")
_IMAGE_COLS = ("image_attachment", "image", "image_path", "media_path", "media", "image_file")
_LABEL_COLS = ("label", "expected_label", "expected_category", "ground_truth")
_ALLOWED_IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"})

# Channel values may arrive as "@name", "t.me/name" or "https://t.me/name"
_CHANNEL_LINK_PREFIX_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/(?:s/)?", re.IGNORECASE
)

_DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y",
    "%Y/%m/%d",
)

# Row-count cadence for import progress logging
_LOG_EVERY_N_ROWS = 500

# OCR result cache: keyed by media SHA-256, persisted to the JSON file given
# by TELEMONITOR_OCR_CACHE so repeated imports of the same dataset skip the
# (slow) EasyOCR pass. Nothing else about OCR changes.
_ocr_cache: Dict[str, Optional[str]] = {}
_ocr_cache_loaded = False


def _load_ocr_cache() -> None:
    global _ocr_cache_loaded
    if _ocr_cache_loaded:
        return
    cache_file = os.environ.get("TELEMONITOR_OCR_CACHE", "")
    if cache_file and Path(cache_file).exists():
        try:
            _ocr_cache.update(json.loads(Path(cache_file).read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001
            logger.warning("OCR cache load failed (%s); starting empty", exc)
    _ocr_cache_loaded = True


def _save_ocr_cache() -> None:
    cache_file = os.environ.get("TELEMONITOR_OCR_CACHE", "")
    if not cache_file:
        return
    try:
        Path(cache_file).write_text(
            json.dumps(_ocr_cache, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug("OCR cache save failed: %s", exc)


async def _cached_ocr(validated_path: Path, media_hash: Optional[str]) -> Optional[str]:
    """OCR with a media-hash-keyed cache (TELEMONITOR_OCR_CACHE json file)."""
    _load_ocr_cache()
    key = media_hash or str(validated_path)
    if key in _ocr_cache:
        return _ocr_cache[key]
    text = await extract_text_from_image(str(validated_path))
    _ocr_cache[key] = text
    _save_ocr_cache()
    return text


def _image_phash(validated_path: Optional[Path]) -> Optional[str]:
    """Perceptual hash of an imported image (near-duplicate detection)."""
    if validated_path is None:
        return None
    try:
        from PIL import Image  # noqa: PLC0415
        import imagehash  # noqa: PLC0415

        with Image.open(validated_path) as img:
            return str(imagehash.phash(img))
    except Exception as exc:  # noqa: BLE001
        logger.debug("phash failed for %s: %s", validated_path, exc)
        return None


def validate_import_media_path(raw_path: str, media_root: Optional[str] = None) -> Path:
    """
    Validate a relative media path against the configured allow-listed IMPORT_MEDIA_ROOT.
    Rejects absolute paths, UNC paths, parent traversal ('..'), symlink escapes,
    and unsupported extensions.
    """
    if not raw_path or not raw_path.strip():
        raise ValueError("Empty image path")
    cleaned = raw_path.strip()
    if cleaned.startswith("\\\\") or cleaned.startswith("//"):
        raise ValueError("UNC or network paths are not allowed")
    p = Path(cleaned)
    if p.is_absolute() or p.drive:
        raise ValueError("Absolute paths are not allowed for import media")
    if ".." in p.parts:
        raise ValueError("Parent directory traversal ('..') is not allowed")
    if p.suffix.lower() not in _ALLOWED_IMAGE_EXTS:
        raise ValueError(f"Unsupported media file extension: {p.suffix!r}")

    root = Path(media_root or settings.IMPORT_MEDIA_ROOT).resolve()
    candidate = (root / p).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("Resolved path escapes allowed import media root")
    if not candidate.exists() or not candidate.is_file():
        raise ValueError("Import media file does not exist inside allowed root")
    return candidate


def _pick(row: Dict[str, Any], candidates: tuple) -> Optional[str]:
    for key in candidates:
        for k in row:
            if k.lower().strip() == key:
                return str(row[k]).strip() if row[k] is not None and str(row[k]).strip() != "" else None
    return None


def _to_naive_utc(dt: datetime) -> datetime:
    """Normalise tz-aware input to naive UTC so stored timestamps stay uniform."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _parse_date(raw: Optional[str]) -> Tuple[Optional[datetime], str]:
    """
    Parse a row timestamp. Returns (datetime_or_None, status) where status is
    one of "missing", "parsed", "epoch", "unparsed".

    Never substitutes wall-clock time: an unparseable value yields
    (None, "unparsed") so callers can report the row instead of silently
    corrupting evidence timestamps.
    """
    if raw is None or not raw.strip():
        return None, "missing"
    text = raw.strip()
    try:
        # ISO-8601 including 'Z' suffix and explicit offsets (replace keeps
        # this working on Python versions whose fromisoformat rejects 'Z').
        return _to_naive_utc(datetime.fromisoformat(text.replace("Z", "+00:00"))), "parsed"
    except ValueError:
        pass
    try:
        value = float(text)
        if abs(value) >= 1e12:  # milliseconds-since-epoch
            value /= 1000.0
        return _to_naive_utc(datetime.fromtimestamp(value, tz=timezone.utc)), "epoch"
    except (ValueError, TypeError, OSError, OverflowError):
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt), "parsed"
        except ValueError:
            continue
    return None, "unparsed"


def _clean_channel(raw: Optional[str]) -> Optional[str]:
    """Reduce a channel cell to its bare name so link forms don't split one channel."""
    if not raw:
        return raw
    cleaned = _CHANNEL_LINK_PREFIX_RE.sub("", raw.strip()).strip("@ /")
    return cleaned or raw


def _row_fields(row: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """Map a raw import row onto canonical field names."""
    return {
        "text": _pick(row, _TEXT_COLS),
        "channel": _clean_channel(_pick(row, _CHANNEL_COLS)),
        "date_raw": _pick(row, _DATE_COLS),
        "sender": _pick(row, _SENDER_COLS),
        "explicit_id": _pick(row, _ID_COLS),
        "image_path": _pick(row, _IMAGE_COLS),
        "label": _pick(row, _LABEL_COLS),
    }


def _find_label_col(row: Dict[str, Any]) -> Optional[str]:
    for key in row:
        if key.lower().strip() in _LABEL_COLS:
            return key
    return None


def _flag_label(raw: Optional[str]) -> Optional[bool]:
    """
    Map a free-form dataset label to a boolean "should be flagged" verdict:
    benign synonyms -> False, everything else (crime category names,
    "flag"/"illegal"/"1") -> True. Returns None when no label is usable.
    """
    if raw is None:
        return None
    v = raw.strip().lower()
    if v in {"", "unknown", "na", "none", "n/a"}:
        return None
    if v in {"0", "false", "benign", "clear", "clean", "legal", "normal", "ok", "negative", "non_flagged", "non-flagged", "ham"}:
        return False
    return True


def _deterministic_import_msg_id(
    channel_name: str,
    created_at: datetime,
    original_text_hash: Optional[str],
    row_idx: int,
    explicit_id: Optional[str],
) -> int:
    """
    Generate a collision-free message ID for imported records.
    Uses explicit numeric ID if provided; otherwise a deterministic negative
    63-bit integer derived from (channel, timestamp, original_text_hash).
    """
    if explicit_id is not None:
        try:
            val = int(explicit_id)
            if val != 0:
                return val
        except ValueError:
            pass
    seed = f"{channel_name}|{created_at.isoformat()}|{original_text_hash or row_idx}"
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    val = int.from_bytes(digest[:8], "big") & ((1 << 62) - 1)
    return -(val or 1)


# ---------------------------------------------------------------------------
# Dry-run preview (no database access, no OCR)
# ---------------------------------------------------------------------------

def validate_rows(
    rows: List[Dict[str, Any]],
    *,
    default_source: str = "csv_import",
    filename: str = "preview",
) -> Dict[str, Any]:
    """
    Preview an import batch without writing anything: field mapping, timestamp
    health, classification outcome, identifier extraction and — when the
    dataset carries a label column — classifier/label agreement.

    OCR is intentionally not run here so the preview stays fast; media rows
    are counted only.
    """
    report: Dict[str, Any] = {
        "filename": filename,
        "source_type": default_source,
        "total_rows": len(rows),
        "errors": [],
        "channels": {},
        "timestamps": {
            "missing": 0, "parsed": 0, "epoch": 0, "unparsed": 0,
            "unparsed_row_indices": [],
        },
        "labels": {"column": None, "distribution": {}},
        "classification": {"flagged": 0, "by_risk": {}, "by_category": {}},
        "label_agreement": None,
        "identifiers": {"total": 0, "distinct": 0, "by_type": {}, "shared_across_channels": 0},
        "media_rows": 0,
        "sample_flagged": [],
        "note": "Preview only — nothing was imported. OCR is not run in preview.",
    }

    label_counts: Dict[str, int] = {}
    labelled: List[Tuple[int, Optional[str], bool, bool, float]] = []  # idx, raw, expected, flagged, score
    ident_channels: Dict[str, set] = {}
    ident_type_count: Dict[str, int] = {}
    total_idents = 0

    for idx, row in enumerate(rows):
        try:
            f = _row_fields(row)
            if f["channel"]:
                report["channels"][f["channel"]] = report["channels"].get(f["channel"], 0) + 1
            if f["image_path"]:
                report["media_rows"] += 1

            _, ts_status = _parse_date(f["date_raw"])
            report["timestamps"][ts_status] += 1
            if ts_status == "unparsed" and len(report["timestamps"]["unparsed_row_indices"]) < 20:
                report["timestamps"]["unparsed_row_indices"].append(idx)

            if f["label"] is not None:
                if report["labels"]["column"] is None:
                    report["labels"]["column"] = _find_label_col(row)
                label_counts[f["label"]] = label_counts.get(f["label"], 0) + 1

            combined = f["text"] or ""
            result = classify(combined)
            if result.is_flagged:
                cls = report["classification"]
                cls["flagged"] += 1
                cls["by_risk"][result.risk_level] = cls["by_risk"].get(result.risk_level, 0) + 1
                for c in result.categories:
                    cls["by_category"][c] = cls["by_category"].get(c, 0) + 1
                if len(report["sample_flagged"]) < 10:
                    report["sample_flagged"].append({
                        "row_index": idx,
                        "channel": f["channel"],
                        "risk_level": result.risk_level,
                        "score": round(result.score, 4),
                        "categories": result.categories,
                        "matched_terms": [t.get("term") for t in result.matched_terms][:8],
                        "text_preview": combined[:120],
                    })

            expected = _flag_label(f["label"])
            if expected is not None:
                labelled.append((idx, f["label"], expected, result.is_flagged, result.score))

            idents = extract(combined)
            total_idents += len(idents)
            for ident in idents:
                ident_type_count[ident.type] = ident_type_count.get(ident.type, 0) + 1
                if is_contact_identifier(ident.type):
                    ident_channels.setdefault(ident.normalised, set()).add(f["channel"] or "?")
        except Exception as exc:
            if len(report["errors"]) < 20:
                report["errors"].append({"row_index": idx, "error": str(exc)})

    report["labels"]["distribution"] = dict(
        sorted(label_counts.items(), key=lambda kv: -kv[1])[:20]
    )
    shared = sum(1 for chans in ident_channels.values() if len(chans) >= 2)
    report["identifiers"] = {
        "total": total_idents,
        "distinct_contact_identifiers": len(ident_channels),
        "by_type": ident_type_count,
        "shared_across_channels": shared,
    }
    if labelled:
        agree = sum(1 for _, _, exp, got, _ in labelled if exp == got)
        disagreements = [
            {
                "row_index": idx,
                "label": raw,
                "expected_flag": exp,
                "predicted_flag": got,
                "score": round(score, 4),
            }
            for idx, raw, exp, got, score in labelled
            if exp != got
        ][:10]
        report["label_agreement"] = {
            "labelled_rows": len(labelled),
            "agree": agree,
            "disagree": len(labelled) - agree,
            "agreement_rate": round(agree / len(labelled), 4),
            "disagreement_samples": disagreements,
        }
    return report


# ---------------------------------------------------------------------------
# Real import
# ---------------------------------------------------------------------------

_INQUIRY_RE = re.compile(
    r"(?:rate\s+kya|price\s+kya|kitna\s+(?:lagega|hai)|mil\s+jayega|milega\s+pehle|"
    r"sample\s+milega|delivery\s+hogi|bhejoge|chalega|trusted\s+ho|inbox\s+check|"
    r"minimum\s+order|kab\s+milega|available\s+hai\s+kya)",
    re.IGNORECASE,
)


async def _flag_buyer_inquiries(db, timeline: Dict[str, List[tuple]]) -> int:
    """
    Flag short question-like messages that trail a flagged ad in the same
    channel (±72 h, different sender). Returns the number of new alerts.
    """
    created = 0
    for _channel, events in timeline.items():
        ads = [(ts, sender) for ts, sender, _mid, _text, is_ad in events if is_ad]
        for ts, sender, mid, text, is_ad in events:
            if is_ad or ts is None or not text or len(text) > 90:
                continue
            if not _INQUIRY_RE.search(text):
                continue
            if sender and any(a_sender == sender for _a_ts, a_sender in ads):
                continue
            if not any(
                a_ts is not None
                and a_sender != sender
                and abs((ts - a_ts).total_seconds()) <= 72 * 3600
                for a_ts, a_sender in ads
            ):
                continue
            alert = Alert(
                message_id=mid,
                risk_level="MEDIUM",
                score=0.5,
                categories="buyer_inquiry",
                evidence=json.dumps(
                    {"reason_codes": ["CONTEXT_BUYER_INQUIRY"], "final_score": 0.5,
                     "scoring_version": settings.SCORING_VERSION,
                     "context": "short inquiry following a flagged ad in the same channel"},
                    default=str),
            )
            await save_alert(db, alert)
            created += 1
    return created


async def process_rows(
    rows: List[Dict[str, Any]],
    default_source: str = "csv_import",
    filename: str = "upload",
) -> Dict[str, Any]:
    imported = 0
    duplicates = 0
    errors = 0
    flagged = 0
    buyer_flagged = 0
    timestamp_unparsed: List[int] = []
    timestamp_missing = 0
    # per-channel (created_at, sender, message_id, text, is_flagged) for the
    # buyer-inquiry context pass
    channel_timeline: Dict[str, List[tuple]] = {}

    async with get_session() as db:
        batch = ImportBatch(filename=filename, source_type=default_source)
        db.add(batch)
        await db.flush()
        await db.commit()
        batch_id = batch.id

        for idx, row in enumerate(rows):
            try:
                fields = _row_fields(row)
                text = fields["text"] or ""
                channel_name = fields["channel"] or "imported_channel"
                sender = fields["sender"]
                explicit_id = fields["explicit_id"]
                image_path = fields["image_path"]

                ocr_text: Optional[str] = None
                m_hash: Optional[str] = None
                validated_path: Optional[Path] = None
                validated_img_str: Optional[str] = None
                ocr_status = "not_applicable"
                if image_path:
                    validated_path = validate_import_media_path(image_path)
                    validated_img_str = str(validated_path)
                    m_hash = compute_media_hash(validated_path)
                    ocr_text = await _cached_ocr(validated_path, m_hash)
                    ocr_status = "success" if ocr_text else ("failed" if m_hash else "skipped")

                combined = " ".join(filter(None, [text, ocr_text]))
                created_at, ts_status = _parse_date(fields["date_raw"])
                if ts_status == "unparsed":
                    timestamp_unparsed.append(idx)
                elif ts_status == "missing":
                    timestamp_missing += 1
                if created_at is None:
                    # Genuinely unknown timestamp: import time is the only
                    # possible fallback and it is reported in the summary, so
                    # the batch stays auditable instead of silently corrupting
                    # evidence timestamps.
                    created_at = datetime.utcnow()
                orig_text_hash = compute_original_text_hash(text)
                msg_id = _deterministic_import_msg_id(
                    channel_name, created_at, orig_text_hash or m_hash, idx, explicit_id
                )
                ev_hash = compute_evidence_hash(
                    source_platform=default_source,
                    channel_identifier=channel_name,
                    source_message_id=msg_id,
                    post_timestamp=created_at,
                    original_text_hash=orig_text_hash,
                    media_hashes=[m_hash] if m_hash else [],
                )
                now = datetime.utcnow()
                obs_hash = compute_observation_hash(
                    evidence_hash=ev_hash,
                    collected_at=now,
                    collector_or_batch_id=f"import_batch:{batch_id}",
                )

                channel = await upsert_channel(db, username=channel_name)

                # Dedup: evidence_hash covers re-imports of the same row
                # (it binds platform + channel + message id + timestamp +
                # content hashes). A same-text re-post WITHIN a channel is a
                # distinct message, not a duplicate — the answer-key dataset
                # deliberately repeats identical ad texts.
                existing = (
                    await db.execute(select(Message).where(Message.evidence_hash == ev_hash))
                ).scalar_one_or_none()
                if existing is None:
                    existing = (
                        await db.execute(
                            select(Message).where(
                                Message.channel_id == channel.id,
                                Message.telegram_msg_id == msg_id,
                            )
                        )
                    ).scalar_one_or_none()

                result = classify(combined)

                if existing is not None:
                    duplicates += 1
                    ev_msg = await upsert_evidence_message(
                        db,
                        channel_username=channel_name,
                        telegram_message_id=existing.telegram_msg_id,
                        message_timestamp=created_at,
                        raw_text=text,
                    )
                    ev_msg.original_text_hash = ev_msg.original_text_hash or orig_text_hash
                    ev_msg.evidence_hash = ev_msg.evidence_hash or ev_hash
                    obs = await insert_evidence_observation(
                        db,
                        evidence_message_id=ev_msg.id,
                        source_type=default_source,
                        score=result.score,
                        risk_level=result.risk_level,
                        severity_tier=result.severity_tier,
                        categories=json.dumps(result.categories),
                        matched_terms=json.dumps([t.get("term", "") for t in result.matched_terms]),
                    )
                    obs.observation_hash = obs_hash
                    obs.import_batch_id = batch_id
                else:
                    new_msg = Message(
                        channel_id=channel.id,
                        telegram_msg_id=msg_id,
                        sender_username=sender,
                        text=text,
                        text_hash=Message.compute_hash(combined) if combined else None,
                        original_text_hash=orig_text_hash,
                        evidence_hash=ev_hash,
                        media_hash=m_hash,
                        provenance_status="verified_hashes",
                        ocr_text=ocr_text,
                        ocr_status=ocr_status,
                        has_media=bool(validated_img_str),
                        media_path=validated_img_str,
                        image_phash=_image_phash(validated_path),
                        forwarded_from=(str(row["forwarded_from"]).strip()[:256] if row.get("forwarded_from") else None),
                        created_at=created_at,
                        source=default_source,
                    )
                    saved_msg = await save_message(db, new_msg)
                    # Near-duplicate identity is caption-level: the copy-pasted
                    # ad text, not the channel-specific OCR noise.
                    sig_str, _ = get_minhash_index().add_message(saved_msg.id, channel.id, text)
                    if sig_str:
                        saved_msg.minhash_sig = sig_str
                    imported += 1

                    ev_msg = await upsert_evidence_message(
                        db,
                        channel_username=channel_name,
                        telegram_message_id=msg_id,
                        message_timestamp=created_at,
                        raw_text=text,
                        ocr_text=ocr_text,
                        normalised_text=result.normalised_text,
                        media_path=validated_img_str,
                        media_hash=m_hash,
                        ocr_outcome=ocr_status,
                    )
                    ev_msg.original_text_hash = orig_text_hash
                    ev_msg.evidence_hash = ev_hash
                    ev_msg.provenance_status = "verified_hashes"
                    obs = await insert_evidence_observation(
                        db,
                        evidence_message_id=ev_msg.id,
                        source_type=default_source,
                        score=result.score,
                        risk_level=result.risk_level,
                        severity_tier=result.severity_tier,
                        categories=json.dumps(result.categories),
                        matched_terms=json.dumps([t.get("term", "") for t in result.matched_terms]),
                    )
                    obs.observation_hash = obs_hash
                    obs.import_batch_id = batch_id

                    identifiers = [
                        Identifier(
                            message_id=saved_msg.id,
                            type=ident.type,
                            value=ident.value,
                            normalised=ident.normalised,
                        )
                        for ident in extract(combined)
                        if not (ident.type == "location" and not result.is_flagged)
                    ]
                    # The poster's own handle is an identity on flagged posts even when it never
                    # appears in the text (e.g. an Instagram author posting
                    # without signing the caption).
                    if result.is_flagged and sender and sender.strip().startswith("@"):
                        h = sender.strip()
                        hn = h.lstrip("@").lower()
                        if hn and hn not in {i.normalised for i in identifiers if i.type == "handle"}:
                            identifiers.append(
                                Identifier(message_id=saved_msg.id, type="handle",
                                           value=h, normalised=hn)
                            )
                    if identifiers:
                        await save_identifiers(db, identifiers)
                        # Only actor identifiers (phone/UPI/handle/wallet/...) are
                        # linked; urls and locations are evidence, not identity.
                        linkable = [i for i in identifiers if is_contact_identifier(i.type)]
                        for i in range(len(linkable)):
                            for j in range(i + 1, len(linkable)):
                                await upsert_entity_link(db, linkable[i].id, linkable[j].id)

                    if result.is_flagged:
                        alert = Alert(
                            message_id=saved_msg.id,
                            risk_level=result.risk_level,
                            score=result.score,
                            categories=",".join(result.categories),
                            evidence=json.dumps(result.evidence, default=str),
                        )
                        await save_alert(db, alert)
                        flagged += 1

                    channel_timeline.setdefault(channel_name, []).append(
                        (created_at, sender or "", saved_msg.id, text, result.is_flagged)
                    )

                await db.commit()
                if (idx + 1) % _LOG_EVERY_N_ROWS == 0:
                    logger.info(
                        "Import %s: %d/%d rows (imported=%d duplicates=%d errors=%d)",
                        filename, idx + 1, len(rows), imported, duplicates, errors,
                    )

            except Exception as exc:
                await db.rollback()
                logger.error("Import error on row %d: %s", idx, exc)
                errors += 1

        b = (await db.execute(select(ImportBatch).where(ImportBatch.id == batch_id))).scalar_one_or_none()
        if b:
            b.imported_count = imported
            b.duplicate_count = duplicates
            b.failed_count = errors

        # ── Buyer-inquiry context pass ────────────────────────────────────────
        # Short question-like messages from other users that trail a flagged ad
        # in the same channel are buyer-side signals ("sample milega pehle?",
        # "rate kya hai?") even though they carry no category keywords.
        buyer_flagged = await _flag_buyer_inquiries(db, channel_timeline)

    return {
        "batch_id": batch_id,
        "imported": imported,
        "duplicates": duplicates,
        "flagged": flagged + buyer_flagged,
        "errors": errors,
        "timestamps_unparsed": len(timestamp_unparsed),
        "timestamps_unparsed_rows": timestamp_unparsed[:20],
        "timestamps_missing": timestamp_missing,
    }


def _unwrap_json_records(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, dict):
        for key in ("data", "messages", "posts", "records", "items"):
            if key in data and isinstance(data[key], list):
                return list(data[key])
        return [data]
    return list(data)


async def import_csv(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    text_content = file_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text_content))
    rows = list(reader)
    return await process_rows(rows, default_source="csv_import", filename=filename)


async def import_json(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    data = json.loads(file_bytes.decode("utf-8", errors="replace"))
    rows = _unwrap_json_records(data)
    return await process_rows(rows, default_source="json_import", filename=filename)


async def validate_csv(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    text_content = file_bytes.decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text_content)))
    return validate_rows(rows, default_source="csv_import", filename=filename)


async def validate_json(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    data = json.loads(file_bytes.decode("utf-8", errors="replace"))
    rows = _unwrap_json_records(data)
    return validate_rows(rows, default_source="json_import", filename=filename)
