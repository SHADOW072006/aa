"""
Analyst review service — structured labelling of automatically generated
alerts, evidence records, and collected/imported messages.

Operating boundaries
--------------------
- Raw evidence text is never copied into this layer or modified.
- Every label submission/update is appended to AnalystReviewHistory.
- Metrics are computed only from analyst-reviewed records.
- When reviewed record count is too low, metrics return an explicit
  "insufficient_reviewed_data" indicator rather than misleading figures.
- No synthetic/demo data is accepted; every review must reference a real
  target_id from alerts, evidence_messages, or messages.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    Alert,
    AnalystReview,
    AnalystReviewHistory,
    AuditLog,
    Channel,
    EvidenceMessage,
    Message,
    QueryVariant,
    SeedProfile,
)

# ── Constants ─────────────────────────────────────────────────────────────────

VALID_TARGET_TYPES = frozenset({"alert", "evidence_message", "message"})

VALID_LABELS = frozenset({
    "confirmed_relevant",
    "false_positive",
    "benign_or_news",
    "needs_review",
    "uncertain",
})

VALID_CATEGORIES = frozenset({
    "drugs", "arms", "fake_documents", "mule_accounts",
    "cards", "sim_cards", "other", "benign",
})

VALID_INTENTS = frozenset({
    "sale_or_supply", "rental_or_recruitment", "discussion_or_news",
    "prevention_or_awareness", "unrelated", "unknown",
})

# Minimum reviewed records per class before precision/recall/F1 are reported.
MIN_REVIEWED_FOR_METRIC: int = settings.MIN_REVIEWED_FOR_METRIC


# ── Evidence hash helper (canonical manifest) ────────────────────────────────

def compute_canonical_evidence_hash(
    *,
    source_platform: str,
    channel_identifier: str,
    source_message_id: int,
    post_timestamp: Optional[datetime],
    original_text_hash: Optional[str],
    media_hashes: Optional[List[str]] = None,
) -> str:
    """
    Compute SHA-256 of canonical JSON of:
    {source_platform, channel_id_or_username, source_message_id,
     post_timestamp (UTC ISO), original_text_hash, sorted media_hashes}.
    """
    ts_iso: Optional[str] = None
    if post_timestamp is not None:
        if post_timestamp.tzinfo is None:
            ts_utc = post_timestamp.replace(tzinfo=timezone.utc)
        else:
            ts_utc = post_timestamp.astimezone(timezone.utc)
        ts_iso = ts_utc.isoformat()

    manifest = {
        "source_platform": source_platform,
        "channel_id_or_username": channel_identifier,
        "source_message_id": source_message_id,
        "post_timestamp": ts_iso,
        "original_text_hash": original_text_hash,
        "media_hashes": sorted(media_hashes or []),
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── CRUD helpers ──────────────────────────────────────────────────────────────

async def upsert_analyst_review(
    db: AsyncSession,
    *,
    target_type: str,
    target_id: int,
    label: str,
    reviewed_by: str,
    category: Optional[str] = None,
    intent: Optional[str] = None,
    note: Optional[str] = None,
    sampling_stratum: Optional[str] = None,
) -> AnalystReview:
    """
    Create or update the analyst review for (target_type, target_id),
    and append an immutable record to analyst_review_history.

    target_type must be 'alert', 'evidence_message', or 'message'.
    Raises ValueError for invalid label/category/intent/target_type.
    Does NOT copy or alter raw evidence text.
    """
    if target_type not in VALID_TARGET_TYPES:
        raise ValueError(
            f"Invalid target_type {target_type!r}. "
            f"Must be one of: {sorted(VALID_TARGET_TYPES)}."
        )
    if label not in VALID_LABELS:
        raise ValueError(
            f"Invalid label {label!r}. Must be one of: {sorted(VALID_LABELS)}"
        )
    if category is not None and category not in VALID_CATEGORIES:
        raise ValueError(
            f"Invalid category {category!r}. Must be one of: {sorted(VALID_CATEGORIES)}"
        )
    if intent is not None and intent not in VALID_INTENTS:
        raise ValueError(
            f"Invalid intent {intent!r}. Must be one of: {sorted(VALID_INTENTS)}"
        )

    classifier_score: Optional[float] = None
    classifier_risk_level: Optional[str] = None

    if target_type == "alert":
        result = await db.execute(select(Alert).where(Alert.id == target_id))
        target = result.scalar_one_or_none()
        if target is None:
            raise ValueError(f"Alert {target_id} not found.")
        classifier_score = target.score
        classifier_risk_level = target.risk_level
    elif target_type == "evidence_message":
        result = await db.execute(
            select(EvidenceMessage).where(EvidenceMessage.id == target_id)
        )
        target = result.scalar_one_or_none()
        if target is None:
            raise ValueError(f"EvidenceMessage {target_id} not found.")
    else:  # message (collected or imported record)
        result = await db.execute(select(Message).where(Message.id == target_id))
        target = result.scalar_one_or_none()
        if target is None:
            raise ValueError(f"Message {target_id} not found.")
        alert_q = await db.execute(select(Alert).where(Alert.message_id == target_id))
        linked_alert = alert_q.scalar_one_or_none()
        if linked_alert is not None:
            classifier_score = linked_alert.score
            classifier_risk_level = linked_alert.risk_level
        else:
            classifier_score = 0.0
            classifier_risk_level = "LOW"

    existing = await db.execute(
        select(AnalystReview).where(
            AnalystReview.target_type == target_type,
            AnalystReview.target_id == target_id,
        )
    )
    review = existing.scalar_one_or_none()

    now = datetime.utcnow()
    if review is None:
        review = AnalystReview(
            target_type=target_type,
            target_id=target_id,
            label=label,
            category=category,
            intent=intent,
            reviewed_by=reviewed_by,
            reviewed_at=now,
            note=note,
            classifier_score=classifier_score,
            classifier_risk_level=classifier_risk_level,
            sampling_stratum=sampling_stratum,
        )
        db.add(review)
    else:
        review.label = label
        review.category = category
        review.intent = intent
        review.reviewed_by = reviewed_by
        review.reviewed_at = now
        review.note = note
        if sampling_stratum is not None:
            review.sampling_stratum = sampling_stratum
        if review.classifier_score is None and classifier_score is not None:
            review.classifier_score = classifier_score
            review.classifier_risk_level = classifier_risk_level

    await db.flush()

    history_entry = AnalystReviewHistory(
        review_id=review.id,
        target_type=target_type,
        target_id=target_id,
        label=label,
        category=category,
        intent=intent,
        reviewed_by=reviewed_by,
        reviewed_at=now,
        note=note,
        sampling_stratum=review.sampling_stratum,
        classifier_score=review.classifier_score,
        classifier_risk_level=review.classifier_risk_level,
    )
    db.add(history_entry)
    await db.flush()
    return review


async def get_review_for_target(
    db: AsyncSession,
    target_type: str,
    target_id: int,
) -> Optional[AnalystReview]:
    result = await db.execute(
        select(AnalystReview).where(
            AnalystReview.target_type == target_type,
            AnalystReview.target_id == target_id,
        )
    )
    return result.scalar_one_or_none()


async def list_review_history(
    db: AsyncSession,
    target_type: str,
    target_id: int,
) -> Sequence[AnalystReviewHistory]:
    result = await db.execute(
        select(AnalystReviewHistory)
        .where(
            AnalystReviewHistory.target_type == target_type,
            AnalystReviewHistory.target_id == target_id,
        )
        .order_by(AnalystReviewHistory.reviewed_at.desc(), AnalystReviewHistory.id.desc())
    )
    return result.scalars().all()


async def list_unreviewed_alerts(
    db: AsyncSession,
    *,
    risk_level: Optional[str] = None,
    min_score: Optional[float] = None,
    skip: int = 0,
    limit: int = 50,
) -> Sequence[Alert]:
    """
    Return HIGH/MEDIUM alerts that have no analyst review yet.
    Ordered by score descending so the highest-risk items come first.
    """
    reviewed_ids_q = select(AnalystReview.target_id).where(
        AnalystReview.target_type == "alert"
    )
    q = (
        select(Alert)
        .where(
            Alert.id.not_in(reviewed_ids_q),
            Alert.lifecycle_state == "active",
        )
        .order_by(Alert.score.desc())
    )
    if risk_level:
        q = q.where(Alert.risk_level == risk_level.upper())
    else:
        q = q.where(Alert.risk_level.in_(("HIGH", "MEDIUM")))
    if min_score is not None:
        q = q.where(Alert.score >= min_score)
    q = q.offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


async def list_reviewed_alerts(
    db: AsyncSession,
    *,
    label: Optional[str] = None,
    category: Optional[str] = None,
    target_type: Optional[str] = "alert",
    skip: int = 0,
    limit: int = 100,
) -> Sequence[AnalystReview]:
    """Return analyst reviews, optionally filtered by target_type, label, and/or category."""
    q = select(AnalystReview)
    if target_type:
        q = q.where(AnalystReview.target_type == target_type)
    if label:
        q = q.where(AnalystReview.label == label)
    if category:
        q = q.where(AnalystReview.category == category)
    q = q.order_by(AnalystReview.reviewed_at.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


# ── Stratified non-flagged sampling ──────────────────────────────────────────

def _build_stratum_key(
    *,
    source: str,
    created_at: Optional[datetime],
    score_band: str,
    profile: str,
) -> str:
    date_bucket = created_at.strftime("%Y-%m") if created_at else "unknown"
    return f"source={source}|date={date_bucket}|score={score_band}|profile={profile}"


async def sample_non_flagged_records(
    db: AsyncSession,
    *,
    limit: int = 50,
    per_stratum: int = 5,
    source: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a stratified sample of unreviewed NON-flagged messages
    stratified by source, date range (YYYY-MM), score band, and category/seed profile.
    Never returns raw message text or unmasked identifiers.
    """
    flagged_msg_ids_q = select(Alert.message_id).where(
        Alert.risk_level.in_(("HIGH", "MEDIUM"))
    )
    reviewed_msg_ids_q = select(AnalystReview.target_id).where(
        AnalystReview.target_type == "message"
    )

    q = (
        select(
            Message.id,
            Message.source,
            Message.created_at,
            Message.channel_id,
            Channel.username,
            Channel.discovery_variant_id,
            Alert.score,
        )
        .join(Channel, Channel.id == Message.channel_id)
        .outerjoin(Alert, Alert.message_id == Message.id)
        .where(Message.id.not_in(flagged_msg_ids_q))
        .where(Message.id.not_in(reviewed_msg_ids_q))
        .order_by(Message.created_at.desc(), Message.id.asc())
    )
    if source:
        q = q.where(Message.source == source)

    rows = (await db.execute(q)).all()

    # Map discovery_variant_id -> threat_category if present
    variant_ids = {r.discovery_variant_id for r in rows if r.discovery_variant_id is not None}
    variant_cat_map: Dict[int, str] = {}
    if variant_ids:
        vq = await db.execute(
            select(QueryVariant.id, SeedProfile.threat_category)
            .join(SeedProfile, SeedProfile.id == QueryVariant.seed_profile_id)
            .where(QueryVariant.id.in_(variant_ids))
        )
        for vid, cat in vq.all():
            variant_cat_map[vid] = cat

    strata: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        sc = float(r.score) if r.score is not None else 0.0
        if sc >= 0.30:
            score_band = "0.30-0.45"
        elif sc > 0.0:
            score_band = "0.01-0.30"
        else:
            score_band = "0.00"
        profile = variant_cat_map.get(r.discovery_variant_id, "direct") if r.discovery_variant_id else "direct"
        stratum = _build_stratum_key(
            source=r.source or "telegram",
            created_at=r.created_at,
            score_band=score_band,
            profile=profile,
        )
        strata[stratum].append({
            "target_type": "message",
            "target_id": r.id,
            "channel_username": r.username,
            "source": r.source or "telegram",
            "date_bucket": r.created_at.strftime("%Y-%m") if r.created_at else "unknown",
            "score_band": score_band,
            "seed_profile_category": profile,
            "sampling_stratum": stratum,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    stratum_population = {k: len(v) for k, v in strata.items()}

    # Round-robin across strata up to per_stratum and total limit
    selected: List[Dict[str, Any]] = []
    stratum_keys = sorted(strata.keys())
    idx = 0
    while len(selected) < limit and idx < per_stratum:
        added_any = False
        for k in stratum_keys:
            if len(selected) >= limit:
                break
            bucket = strata[k]
            if idx < len(bucket):
                selected.append(bucket[idx])
                added_any = True
        if not added_any:
            break
        idx += 1

    return {
        "total_non_flagged_unreviewed": len(rows),
        "stratum_count": len(strata),
        "stratum_population": stratum_population,
        "sampled_count": len(selected),
        "results": selected,
    }


# ── Metrics service ───────────────────────────────────────────────────────────

async def _get_non_flagged_stratum_populations(db: AsyncSession) -> Dict[str, int]:
    """Compute population size N_h for each non-flagged stratum."""
    flagged_msg_ids_q = select(Alert.message_id).where(
        Alert.risk_level.in_(("HIGH", "MEDIUM"))
    )
    q = (
        select(
            Message.source,
            Message.created_at,
            Channel.discovery_variant_id,
            Alert.score,
        )
        .join(Channel, Channel.id == Message.channel_id)
        .outerjoin(Alert, Alert.message_id == Message.id)
        .where(Message.id.not_in(flagged_msg_ids_q))
    )
    rows = (await db.execute(q)).all()
    variant_ids = {r.discovery_variant_id for r in rows if r.discovery_variant_id is not None}
    variant_cat_map: Dict[int, str] = {}
    if variant_ids:
        vq = await db.execute(
            select(QueryVariant.id, SeedProfile.threat_category)
            .join(SeedProfile, SeedProfile.id == QueryVariant.seed_profile_id)
            .where(QueryVariant.id.in_(variant_ids))
        )
        for vid, cat in vq.all():
            variant_cat_map[vid] = cat

    pops: Dict[str, int] = defaultdict(int)
    for r in rows:
        sc = float(r.score) if r.score is not None else 0.0
        score_band = "0.30-0.45" if sc >= 0.30 else ("0.01-0.30" if sc > 0.0 else "0.00")
        profile = variant_cat_map.get(r.discovery_variant_id, "direct") if r.discovery_variant_id else "direct"
        key = _build_stratum_key(
            source=r.source or "telegram",
            created_at=r.created_at,
            score_band=score_band,
            profile=profile,
        )
        pops[key] += 1
    return dict(pops)


async def compute_review_metrics(
    db: AsyncSession,
    *,
    min_reviewed: Optional[int] = None,
) -> dict:
    """
    Compute precision, stratified-weighted recall, F1, FPR, and per-category
    confusion matrix from analyst-reviewed records only.

    Returns "insufficient_reviewed_data" when reviewed records are below
    min_reviewed (default MIN_REVIEWED_FOR_METRIC = 20).
    Aggregate output never returns message text or unmasked identifiers.
    """
    threshold = min_reviewed if min_reviewed is not None else MIN_REVIEWED_FOR_METRIC

    all_reviews = (await db.execute(select(AnalystReview))).scalars().all()
    flagged_reviews = [
        r for r in all_reviews
        if r.target_type == "alert" or (r.target_type == "message" and r.classifier_risk_level in ("HIGH", "MEDIUM"))
    ]
    non_flagged_reviews = [
        r for r in all_reviews
        if r.target_type == "message" and r.classifier_risk_level not in ("HIGH", "MEDIUM")
    ]

    total_reviewed = len(flagged_reviews)
    if total_reviewed < threshold:
        return {
            "total_reviewed": total_reviewed,
            "non_flagged_reviewed": len(non_flagged_reviews),
            "minimum_required": threshold,
            "status": "insufficient_reviewed_data",
            "precision": None,
            "recall": None,
            "f1": None,
            "false_positive_rate": None,
            "by_category": {},
            "per_category_confusion": {},
            "note": (
                f"Metrics require at least {threshold} reviewed flagged records. "
                f"Currently have {total_reviewed}."
            ),
        }

    label_counts: Dict[str, int] = defaultdict(int)
    for r in flagged_reviews:
        label_counts[r.label] += 1

    tp = label_counts.get("confirmed_relevant", 0)
    fp = label_counts.get("false_positive", 0) + label_counts.get("benign_or_news", 0)
    uncertain = label_counts.get("uncertain", 0) + label_counts.get("needs_review", 0)

    definitive_flagged = tp + fp
    precision_val: Optional[float] = (
        round(tp / definitive_flagged, 3) if definitive_flagged >= threshold else None
    )

    # Stratified-weighted recall & FPR from reviewed non-flagged sample
    nf_definitive = [
        r for r in non_flagged_reviews
        if r.label in ("confirmed_relevant", "false_positive", "benign_or_news")
    ]
    recall_out: Any = "insufficient_reviewed_data"
    f1_out: Any = None
    fpr_out: Any = "insufficient_reviewed_data"

    if len(nf_definitive) >= threshold and precision_val is not None:
        stratum_pops = await _get_non_flagged_stratum_populations(db)
        by_stratum: Dict[str, List[AnalystReview]] = defaultdict(list)
        for r in nf_definitive:
            by_stratum[r.sampling_stratum or "unstratified"].append(r)

        total_nf_pop = sum(stratum_pops.values()) or len(nf_definitive)
        est_fn = 0.0
        est_tn = 0.0
        for s_key, items in by_stratum.items():
            n_h = len(items)
            fn_h = sum(1 for x in items if x.label == "confirmed_relevant")
            tn_h = n_h - fn_h
            pop_h = stratum_pops.get(s_key, n_h)
            if len(by_stratum) == 1 and s_key == "unstratified":
                pop_h = total_nf_pop
            est_fn += pop_h * (fn_h / n_h)
            est_tn += pop_h * (tn_h / n_h)

        # Scale TP & FP to total flagged population if available
        total_flagged_q = await db.execute(
            select(func.count(Alert.id)).where(Alert.risk_level.in_(("HIGH", "MEDIUM")))
        )
        total_flagged_pop = total_flagged_q.scalar_one() or definitive_flagged
        est_tp = total_flagged_pop * (tp / definitive_flagged)
        est_fp = total_flagged_pop * (fp / definitive_flagged)

        recall_num = est_tp / (est_tp + est_fn) if (est_tp + est_fn) > 0 else 0.0
        recall_out = round(recall_num, 3)
        if precision_val + recall_num > 0:
            f1_out = round(2 * precision_val * recall_num / (precision_val + recall_num), 3)
        else:
            f1_out = 0.0
        fpr_num = est_fp / (est_fp + est_tn) if (est_fp + est_tn) > 0 else 0.0
        fpr_out = round(fpr_num, 3)

    # Per-category breakdown and confusion
    by_category: Dict[str, Dict[str, Any]] = {}
    per_category_confusion: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    # Map alert_id -> predicted category string
    alert_ids = [r.target_id for r in flagged_reviews if r.target_type == "alert"]
    alert_pred_cat: Dict[int, str] = {}
    if alert_ids:
        aq = await db.execute(select(Alert.id, Alert.categories).where(Alert.id.in_(alert_ids)))
        for aid, cats in aq.all():
            first_cat = (cats or "").split(",")[0].strip() if cats else "uncategorised"
            alert_pred_cat[aid] = first_cat or "uncategorised"

    for r in flagged_reviews:
        cat_key = r.category or "uncategorised"
        if cat_key not in by_category:
            by_category[cat_key] = {}
        by_category[cat_key][r.label] = by_category[cat_key].get(r.label, 0) + 1

        pred_key = alert_pred_cat.get(r.target_id, "unknown") if r.target_type == "alert" else "message"
        actual_key = r.category or r.label
        per_category_confusion[pred_key][actual_key] += 1

    for cat, counts in by_category.items():
        c_tp = counts.get("confirmed_relevant", 0)
        c_fp = counts.get("false_positive", 0) + counts.get("benign_or_news", 0)
        c_total = sum(v for k, v in counts.items() if isinstance(v, int))
        counts["sample_size"] = c_total
        if c_total >= threshold and (c_tp + c_fp) >= threshold:
            counts["precision"] = round(c_tp / (c_tp + c_fp), 3)
        else:
            counts["precision"] = "insufficient_reviewed_data"

    return {
        "total_reviewed": total_reviewed,
        "non_flagged_reviewed": len(non_flagged_reviews),
        "minimum_required": threshold,
        "status": "ok",
        "label_counts": dict(label_counts),
        "uncertain_count": uncertain,
        "precision": precision_val if precision_val is not None else "insufficient_reviewed_data",
        "recall": recall_out,
        "f1": f1_out,
        "false_positive_rate": fpr_out,
        "by_category": by_category,
        "per_category_confusion": {k: dict(v) for k, v in per_category_confusion.items()},
        "note": (
            "Metrics are computed strictly from analyst-reviewed records. "
            "Recall and FPR are estimated from the stratified non-flagged sample when >= minimum_required."
        ),
    }


# ── Offline export (audit-logged, ID + hash + provenance only) ────────────────

async def export_reviewed_records_offline(
    db: AsyncSession,
    *,
    exported_by: str,
    output_dir: str = "exports",
) -> Dict[str, Any]:
    """
    Export reviewed records to a local JSONL file containing ONLY
    record ID, evidence_hash, original_text_hash, provenance, and label metadata.
    Never exports raw message text or unmasked identifiers.
    Writes an AuditLog entry for every export.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    file_path = out_path / f"reviewed_export_{ts}.jsonl"

    reviews = (await db.execute(select(AnalystReview).order_by(AnalystReview.id.asc()))).scalars().all()
    lines: List[str] = []

    for r in reviews:
        ev_hash: Optional[str] = None
        orig_text_hash: Optional[str] = None
        provenance: Dict[str, Any] = {}

        if r.target_type == "alert":
            q = await db.execute(
                select(Alert, Message, Channel)
                .join(Message, Message.id == Alert.message_id)
                .join(Channel, Channel.id == Message.channel_id)
                .where(Alert.id == r.target_id)
            )
            row = q.first()
            if row:
                _, msg, ch = row
                orig_text_hash = msg.text_hash
                ev_hash = compute_canonical_evidence_hash(
                    source_platform=msg.source or "telegram",
                    channel_identifier=ch.username,
                    source_message_id=msg.telegram_msg_id,
                    post_timestamp=msg.created_at,
                    original_text_hash=orig_text_hash,
                    media_hashes=[],
                )
                provenance = {
                    "channel_username": ch.username,
                    "source": msg.source,
                    "source_message_id": msg.telegram_msg_id,
                    "post_timestamp": msg.created_at.isoformat() if msg.created_at else None,
                }
        elif r.target_type == "message":
            q = await db.execute(
                select(Message, Channel)
                .join(Channel, Channel.id == Message.channel_id)
                .where(Message.id == r.target_id)
            )
            row = q.first()
            if row:
                msg, ch = row
                orig_text_hash = msg.text_hash
                ev_hash = compute_canonical_evidence_hash(
                    source_platform=msg.source or "telegram",
                    channel_identifier=ch.username,
                    source_message_id=msg.telegram_msg_id,
                    post_timestamp=msg.created_at,
                    original_text_hash=orig_text_hash,
                    media_hashes=[],
                )
                provenance = {
                    "channel_username": ch.username,
                    "source": msg.source,
                    "source_message_id": msg.telegram_msg_id,
                    "post_timestamp": msg.created_at.isoformat() if msg.created_at else None,
                }
        else:  # evidence_message
            q = await db.execute(select(EvidenceMessage).where(EvidenceMessage.id == r.target_id))
            em = q.scalar_one_or_none()
            if em:
                orig_text_hash = hashlib.sha256(em.raw_text.encode("utf-8")).hexdigest() if em.raw_text else None
                media_hashes = [em.media_hash] if em.media_hash else []
                ev_hash = compute_canonical_evidence_hash(
                    source_platform="telegram",
                    channel_identifier=em.channel_username,
                    source_message_id=em.telegram_message_id,
                    post_timestamp=em.message_timestamp,
                    original_text_hash=orig_text_hash,
                    media_hashes=media_hashes,
                )
                provenance = {
                    "channel_username": em.channel_username,
                    "source": "evidence_v2",
                    "source_message_id": em.telegram_message_id,
                    "post_timestamp": em.message_timestamp.isoformat() if em.message_timestamp else None,
                }

        record = {
            "record_id": r.target_id,
            "target_type": r.target_type,
            "evidence_hash": ev_hash,
            "original_text_hash": orig_text_hash,
            "provenance": provenance,
            "label": r.label,
            "category": r.category,
            "intent": r.intent,
            "sampling_stratum": r.sampling_stratum,
            "reviewed_by": r.reviewed_by,
            "reviewed_at": r.reviewed_at.isoformat(),
        }
        lines.append(json.dumps(record, sort_keys=True))

    payload = "\n".join(lines) + ("\n" if lines else "")
    file_path.write_text(payload, encoding="utf-8")
    export_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    audit = AuditLog(
        actor=exported_by,
        action="review_export",
        target_type="export",
        target_id=None,
        record_hash=export_hash,
        details=json.dumps({"file_path": str(file_path), "record_count": len(lines)}),
    )
    db.add(audit)
    await db.flush()

    return {
        "file_path": str(file_path),
        "record_count": len(lines),
        "export_hash": export_hash,
        "audit_log_id": audit.id,
    }


async def compute_false_positives_by_category_and_seed(db: AsyncSession) -> Dict[str, Any]:
    """Report reviewed false-positive counts and rates by category and by seed profile."""
    reviews = (await db.execute(select(AnalystReview))).scalars().all()
    by_cat: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "fp": 0})
    for r in reviews:
        c = r.category or "uncategorised"
        by_cat[c]["total"] += 1
        if r.label in ("false_positive", "benign_or_news"):
            by_cat[c]["fp"] += 1

    cat_summary = {
        k: {
            **v,
            "fp_rate": round(v["fp"] / v["total"], 3) if v["total"] > 0 else 0.0,
        }
        for k, v in by_cat.items()
    }

    seeds = (await db.execute(select(SeedProfile))).scalars().all()
    by_seed = [
        {
            "seed_id": s.id,
            "threat_category": s.threat_category,
            "profile": getattr(s, "profile", "illegal_trade"),
            "alert_count": getattr(s, "alert_count", 0),
            "reviewed_total": getattr(s, "reviewed_total_count", 0),
            "reviewed_fp": getattr(s, "reviewed_fp_count", 0),
            "fp_rate": (
                round(s.reviewed_fp_count / s.reviewed_total_count, 3)
                if getattr(s, "reviewed_total_count", 0) > 0
                else None
            ),
        }
        for s in seeds
        if getattr(s, "reviewed_total_count", 0) > 0 or getattr(s, "reviewed_fp_count", 0) > 0
    ]

    return {
        "by_category": cat_summary,
        "by_seed": by_seed,
    }

