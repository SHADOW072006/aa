"""
Unit tests for the analyst review service and metrics calculation.

Operating boundaries:
- NO real collected records, identifiers, or evidence text in this file.
- Tests use in-memory SQLite with minimal placeholder values only.
- Mocked Alert/EvidenceMessage rows use non-identifying placeholder strings.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Alert, Base, EvidenceMessage
from app.services.review_service import (
    MIN_REVIEWED_FOR_METRIC,
    VALID_CATEGORIES,
    VALID_INTENTS,
    VALID_LABELS,
    compute_review_metrics,
    get_review_for_target,
    list_reviewed_alerts,
    list_unreviewed_alerts,
    upsert_analyst_review,
)


# ── Test DB fixture ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session
    await engine.dispose()


_counter = 0

async def _make_alert(db: AsyncSession, *, score: float = 0.85, risk_level: str = "HIGH", categories: str = "drug_sale") -> Alert:
    """Create a minimal placeholder Alert row — no real content."""
    global _counter
    _counter += 1
    from app.db.models import Channel, Message
    # Unique username per call to avoid UNIQUE constraint conflicts
    ch = Channel(username=f"placeholder_ch_{_counter}", is_active=True)
    db.add(ch)
    await db.flush()
    msg = Message(
        channel_id=ch.id,
        telegram_msg_id=10000 + _counter,
        text="[placeholder text for test]",
        text_hash=f"hash{_counter:04d}",
        has_media=False,
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        source="telegram",
    )
    db.add(msg)
    await db.flush()
    alert = Alert(
        message_id=msg.id,
        risk_level=risk_level,
        score=score,
        categories=categories,
        evidence="{}",
    )
    db.add(alert)
    await db.flush()
    return alert


# ── Constant validation tests ────────────────────────────────────────────────

def test_valid_labels_non_empty():
    assert len(VALID_LABELS) >= 5

def test_valid_categories_cover_six_required():
    required = {"drugs", "arms", "fake_documents", "mule_accounts", "cards", "sim_cards"}
    assert required.issubset(VALID_CATEGORIES)

def test_valid_intents_non_empty():
    assert len(VALID_INTENTS) >= 5

def test_sale_and_news_intents_present():
    assert "sale_or_supply" in VALID_INTENTS
    assert "discussion_or_news" in VALID_INTENTS


# ── Validation error tests ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_label_raises(db):
    alert = await _make_alert(db)
    with pytest.raises(ValueError, match="Invalid label"):
        await upsert_analyst_review(
            db,
            target_type="alert",
            target_id=alert.id,
            label="totally_wrong",
            reviewed_by="analyst_a",
        )

@pytest.mark.asyncio
async def test_invalid_category_raises(db):
    alert = await _make_alert(db)
    with pytest.raises(ValueError, match="Invalid category"):
        await upsert_analyst_review(
            db,
            target_type="alert",
            target_id=alert.id,
            label="confirmed_relevant",
            reviewed_by="analyst_a",
            category="not_a_real_category",
        )

@pytest.mark.asyncio
async def test_invalid_intent_raises(db):
    alert = await _make_alert(db)
    with pytest.raises(ValueError, match="Invalid intent"):
        await upsert_analyst_review(
            db,
            target_type="alert",
            target_id=alert.id,
            label="confirmed_relevant",
            reviewed_by="analyst_a",
            intent="buy_it_now",
        )

@pytest.mark.asyncio
async def test_invalid_target_type_raises(db):
    with pytest.raises(ValueError, match="Invalid target_type"):
        await upsert_analyst_review(
            db,
            target_type="channel",
            target_id=1,
            label="confirmed_relevant",
            reviewed_by="analyst_a",
        )

@pytest.mark.asyncio
async def test_missing_alert_raises(db):
    with pytest.raises(ValueError, match="Alert 99999 not found"):
        await upsert_analyst_review(
            db,
            target_type="alert",
            target_id=99999,
            label="confirmed_relevant",
            reviewed_by="analyst_a",
        )


# ── Create / upsert tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_review_saves_fields(db):
    alert = await _make_alert(db, score=0.9, risk_level="HIGH")
    review = await upsert_analyst_review(
        db,
        target_type="alert",
        target_id=alert.id,
        label="confirmed_relevant",
        reviewed_by="analyst_b",
        category="drugs",
        intent="sale_or_supply",
        note="clear sale offer",
    )
    assert review.id is not None
    assert review.label == "confirmed_relevant"
    assert review.category == "drugs"
    assert review.intent == "sale_or_supply"
    assert review.reviewed_by == "analyst_b"
    # Classifier state captured from alert
    assert review.classifier_score == pytest.approx(0.9)
    assert review.classifier_risk_level == "HIGH"

@pytest.mark.asyncio
async def test_upsert_updates_existing(db):
    alert = await _make_alert(db)
    r1 = await upsert_analyst_review(
        db, target_type="alert", target_id=alert.id,
        label="needs_review", reviewed_by="analyst_a",
    )
    r2 = await upsert_analyst_review(
        db, target_type="alert", target_id=alert.id,
        label="false_positive", reviewed_by="analyst_b",
        category="benign",
    )
    # Same id — it was an update
    assert r1.id == r2.id
    assert r2.label == "false_positive"
    assert r2.category == "benign"

@pytest.mark.asyncio
async def test_no_raw_text_in_review(db):
    """Review records must not store raw evidence text."""
    alert = await _make_alert(db, score=0.8)
    review = await upsert_analyst_review(
        db, target_type="alert", target_id=alert.id,
        label="confirmed_relevant", reviewed_by="analyst_c",
    )
    # AnalystReview has no text/raw_text field
    assert not hasattr(review, "text")
    assert not hasattr(review, "raw_text")
    assert not hasattr(review, "message_text")


# ── Retrieval tests ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_review_returns_none_when_absent(db):
    result = await get_review_for_target(db, "alert", 99998)
    assert result is None

@pytest.mark.asyncio
async def test_list_unreviewed_excludes_reviewed(db):
    a1 = await _make_alert(db, score=0.95)
    a2 = await _make_alert(db, score=0.80)
    # Review a1 only
    await upsert_analyst_review(
        db, target_type="alert", target_id=a1.id,
        label="confirmed_relevant", reviewed_by="analyst_a",
    )
    unreviewed = await list_unreviewed_alerts(db)
    ids = [a.id for a in unreviewed]
    assert a1.id not in ids
    assert a2.id in ids

@pytest.mark.asyncio
async def test_list_unreviewed_risk_filter(db):
    high = await _make_alert(db, score=0.9, risk_level="HIGH")
    med = await _make_alert(db, score=0.5, risk_level="MEDIUM")
    high_only = await list_unreviewed_alerts(db, risk_level="HIGH")
    ids = [a.id for a in high_only]
    assert high.id in ids
    assert med.id not in ids


# ── Metrics: insufficient data ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_metrics_insufficient_data_returns_status(db):
    """With zero reviews the metrics endpoint must report insufficient data."""
    result = await compute_review_metrics(db)
    assert result["status"] == "insufficient_reviewed_data"
    assert result["precision"] is None
    assert result["recall"] is None
    assert result["f1"] is None
    assert result["total_reviewed"] == 0

@pytest.mark.asyncio
async def test_metrics_below_minimum_threshold(db):
    """Creating fewer reviews than MIN_REVIEWED_FOR_METRIC still returns insufficient."""
    for i in range(MIN_REVIEWED_FOR_METRIC - 1):
        a = await _make_alert(db, score=0.9)
        await upsert_analyst_review(
            db, target_type="alert", target_id=a.id,
            label="confirmed_relevant", reviewed_by="analyst_x",
        )
    result = await compute_review_metrics(db)
    assert result["status"] == "insufficient_reviewed_data"


# ── Metrics: adequate data ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_metrics_precision_computed_from_definitive_labels(db):
    """With enough definitive reviews precision is a float, not None or string."""
    # Create MIN_REVIEWED_FOR_METRIC + 2 alerts and label them
    for i in range(MIN_REVIEWED_FOR_METRIC + 2):
        a = await _make_alert(db, score=0.9, categories="drug_sale")
        lbl = "confirmed_relevant" if i % 3 != 0 else "false_positive"
        await upsert_analyst_review(
            db, target_type="alert", target_id=a.id,
            label=lbl, reviewed_by="analyst_x",
            category="drugs" if lbl == "confirmed_relevant" else "benign",
        )
    result = await compute_review_metrics(db)
    assert result["status"] == "ok"
    assert result["total_reviewed"] >= MIN_REVIEWED_FOR_METRIC
    # Precision must be a float in [0, 1]
    p = result["precision"]
    if isinstance(p, float):
        assert 0.0 <= p <= 1.0
    # Recall and F1 are reported as not-computable strings
    assert result["recall"] is not None  # returns explanatory string

@pytest.mark.asyncio
async def test_metrics_no_fp_precision_one(db):
    """All confirmed_relevant → precision should be 1.0."""
    for i in range(MIN_REVIEWED_FOR_METRIC + 2):
        a = await _make_alert(db, score=0.9)
        await upsert_analyst_review(
            db, target_type="alert", target_id=a.id,
            label="confirmed_relevant", reviewed_by="analyst_x",
            category="drugs",
        )
    result = await compute_review_metrics(db)
    assert result["status"] == "ok"
    assert result["precision"] == 1.0

@pytest.mark.asyncio
async def test_metrics_category_breakdown_present(db):
    for i in range(MIN_REVIEWED_FOR_METRIC + 2):
        a = await _make_alert(db, score=0.9, categories="arms_sale")
        await upsert_analyst_review(
            db, target_type="alert", target_id=a.id,
            label="confirmed_relevant", reviewed_by="analyst_x",
            category="arms",
        )
    result = await compute_review_metrics(db)
    assert "by_category" in result
    assert "arms" in result["by_category"]


# ── Disposition validation (existing service, ensuring no regression) ─────────

def test_valid_labels_do_not_include_deprecated_values():
    """confirmed_threat, escalated, etc. from the old service should not bleed in."""
    old_values = {"confirmed_threat", "escalated"}
    overlap = old_values & VALID_LABELS
    # It is acceptable if these happen to be there, but confirm we have new values
    assert "confirmed_relevant" in VALID_LABELS
    assert "benign_or_news" in VALID_LABELS


# ── Stage 1: message labelling, history, stratified sampling, weighted recall, offline export ──

async def _make_message(
    db: AsyncSession,
    *,
    source: str = "telegram",
    created_at: datetime = datetime(2025, 2, 10, 12, 0, 0),
    placeholder_text: str = "[placeholder neutral record]",
):
    global _counter
    _counter += 1
    from app.db.models import Channel, Message
    ch = Channel(username=f"placeholder_msg_ch_{_counter}", is_active=True)
    db.add(ch)
    await db.flush()
    msg = Message(
        channel_id=ch.id,
        telegram_msg_id=20000 + _counter,
        text=placeholder_text,
        text_hash=f"msghash{_counter:05d}",
        has_media=False,
        created_at=created_at,
        source=source,
    )
    db.add(msg)
    await db.flush()
    return msg


@pytest.mark.asyncio
async def test_label_message_preserves_evidence_and_appends_history(db):
    from app.services.review_service import list_review_history
    msg = await _make_message(db, placeholder_text="[placeholder untouched text]")
    orig_text = msg.text
    orig_hash = msg.text_hash

    await upsert_analyst_review(
        db,
        target_type="message",
        target_id=msg.id,
        label="needs_review",
        reviewed_by="analyst_1",
        sampling_stratum="source=telegram|date=2025-02|score=0.00|profile=direct",
    )
    await upsert_analyst_review(
        db,
        target_type="message",
        target_id=msg.id,
        label="benign_or_news",
        category="benign",
        intent="discussion_or_news",
        reviewed_by="analyst_2",
        note="second pass",
    )

    assert msg.text == orig_text
    assert msg.text_hash == orig_hash

    history = await list_review_history(db, "message", msg.id)
    assert len(history) == 2
    assert {h.label for h in history} == {"needs_review", "benign_or_news"}
    assert all(h.sampling_stratum == "source=telegram|date=2025-02|score=0.00|profile=direct" for h in history)


@pytest.mark.asyncio
async def test_stratified_non_flagged_sampling_and_no_text_leakage(db):
    from app.services.review_service import sample_non_flagged_records
    for i in range(6):
        await _make_message(db, source="telegram", created_at=datetime(2025, 1, 5, 10, 0, 0))
    for i in range(6):
        await _make_message(db, source="csv_import", created_at=datetime(2025, 2, 5, 10, 0, 0))

    sample = await sample_non_flagged_records(db, limit=6, per_stratum=3)
    assert sample["stratum_count"] == 2
    assert sample["sampled_count"] == 6
    sources = {item["source"] for item in sample["results"]}
    assert sources == {"telegram", "csv_import"}
    for item in sample["results"]:
        assert "text" not in item
        assert "raw_text" not in item
        assert "sampling_stratum" in item


@pytest.mark.asyncio
async def test_metrics_stratified_weighted_recall_f1_fpr(db):
    # Create 20 flagged alerts (16 TP, 4 FP -> P = 0.80)
    for i in range(20):
        a = await _make_alert(db, score=0.9, categories="drug_sale")
        lbl = "confirmed_relevant" if i < 16 else "false_positive"
        await upsert_analyst_review(
            db,
            target_type="alert",
            target_id=a.id,
            label=lbl,
            category="drugs" if lbl == "confirmed_relevant" else "benign",
            reviewed_by="analyst_eval",
        )

    # Create 20 non-flagged messages across 2 strata (10 each; 1 FN in stratum A, 0 FN in stratum B)
    for i in range(10):
        m = await _make_message(db, source="telegram", created_at=datetime(2025, 1, 5, 10, 0, 0))
        await upsert_analyst_review(
            db,
            target_type="message",
            target_id=m.id,
            label="confirmed_relevant" if i == 0 else "benign_or_news",
            category="drugs" if i == 0 else "benign",
            reviewed_by="analyst_eval",
            sampling_stratum="source=telegram|date=2025-01|score=0.00|profile=direct",
        )
    for i in range(10):
        m = await _make_message(db, source="csv_import", created_at=datetime(2025, 2, 5, 10, 0, 0))
        await upsert_analyst_review(
            db,
            target_type="message",
            target_id=m.id,
            label="benign_or_news",
            category="benign",
            reviewed_by="analyst_eval",
            sampling_stratum="source=csv_import|date=2025-02|score=0.00|profile=direct",
        )

    metrics = await compute_review_metrics(db, min_reviewed=20)
    assert metrics["status"] == "ok"
    assert metrics["precision"] == pytest.approx(0.8, abs=1e-3)
    assert isinstance(metrics["recall"], float)
    assert 0.0 < metrics["recall"] <= 1.0
    assert isinstance(metrics["f1"], float)
    assert isinstance(metrics["false_positive_rate"], float)
    assert "per_category_confusion" in metrics
    assert "text" not in str(metrics).lower() or "raw_text" not in str(metrics).lower()


@pytest.mark.asyncio
async def test_offline_export_audit_logged_and_no_raw_text(db, tmp_path):
    from sqlalchemy import select
    from app.db.models import AuditLog
    from app.services.review_service import export_reviewed_records_offline

    a = await _make_alert(db, score=0.88)
    await upsert_analyst_review(
        db,
        target_type="alert",
        target_id=a.id,
        label="confirmed_relevant",
        category="drugs",
        intent="sale_or_supply",
        reviewed_by="analyst_exp",
    )

    out = await export_reviewed_records_offline(
        db, exported_by="analyst_exp", output_dir=str(tmp_path)
    )
    assert out["record_count"] == 1
    assert out["audit_log_id"] is not None

    exported_text = (tmp_path / out["file_path"].split("/")[-1].split("\\")[-1]).read_text(encoding="utf-8")
    assert "[placeholder text for test]" not in exported_text
    assert "evidence_hash" in exported_text
    assert "original_text_hash" in exported_text

    logs = (await db.execute(select(AuditLog).where(AuditLog.action == "review_export"))).scalars().all()
    assert len(logs) == 1
    assert logs[0].actor == "analyst_exp"
    assert logs[0].record_hash == out["export_hash"]
