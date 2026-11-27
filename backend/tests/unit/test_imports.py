"""
Task 7 checkpoint: verify that all DB-layer modules import cleanly
and that the core functions are callable.

Requirements: 17.4
"""

import pytest


# ── Import checks ─────────────────────────────────────────────────────────────

def test_models_import():
    """All ORM models must be importable without errors."""
    from app.db.models import (
        Alert,
        Channel,
        ChannelHealthEvent,
        ChannelScanResult,
        ChannelScoreComponents,
        DispositionHistory,
        EntityLink,
        Identifier,
        Message,
        PivotCandidate,
        QueryVariant,
        QueryVariantExecution,
        ScanEvidence,
        ScanJob,
        SeedProfile,
    )
    # Spot-check table names
    assert Channel.__tablename__ == "channels"
    assert SeedProfile.__tablename__ == "seed_profiles"
    assert QueryVariant.__tablename__ == "query_variants"
    assert QueryVariantExecution.__tablename__ == "query_variant_executions"
    assert ScanEvidence.__tablename__ == "scan_evidence"
    assert PivotCandidate.__tablename__ == "pivot_candidates"
    assert ChannelScoreComponents.__tablename__ == "channel_score_components"
    assert ChannelHealthEvent.__tablename__ == "channel_health_events"
    assert DispositionHistory.__tablename__ == "disposition_history"


def test_crud_import():
    """All CRUD helpers must be importable without errors."""
    from app.db.crud import (
        create_seed_profile,
        get_seed_profile_by_id,
        get_seed_profile_by_normalised,
        list_seed_profiles,
        update_seed_profile,
        create_query_variant,
        get_variants_for_seed,
        get_variant_by_text,
        record_variant_execution,
        upsert_scan_evidence,
        get_evidence_for_scan,
        get_evidence_for_channel,
        update_evidence_disposition,
        upsert_pivot_candidate,
        list_pivot_candidates,
        update_pivot_status,
        upsert_channel_score,
        get_score_for_result,
        record_health_event,
        get_health_events,
        record_disposition_change,
        get_disposition_history,
    )
    assert callable(create_seed_profile)
    assert callable(upsert_scan_evidence)
    assert callable(upsert_channel_score)


def test_normaliser_import():
    """normalise and normalise_text must both be importable from the normaliser module."""
    from app.extractors.normaliser import normalise, normalise_text
    assert callable(normalise)
    assert callable(normalise_text)
    # normalise_text is an alias for normalise
    assert normalise_text("hello") == normalise("hello")


def test_classifier_import():
    """classify() must be importable and return a ClassificationResult.

    We initialise with non-existent paths — load() silently skips missing
    files, so we get an empty store.  With no terms loaded every input scores LOW.
    """
    from app.classifiers.classifier import classify, ClassificationResult
    from app.classifiers.lexicon_loader import init_lexicons
    init_lexicons(
        "/nonexistent/drug.json",
        "/nonexistent/financial.json",
        "/nonexistent/arms.json",
    )
    result = classify("hello world")
    assert isinstance(result, ClassificationResult)
    assert result.risk_level in ("HIGH", "MEDIUM", "LOW")
    assert 0.0 <= result.score <= 1.0


# ── Model column checks ───────────────────────────────────────────────────────

def test_channel_new_columns():
    """Channel must have all new polling/health columns from Task 1."""
    from app.db.models import Channel
    cols = {c.key for c in Channel.__table__.columns}
    for col in ("poll_tier", "last_poll_attempted_at", "consecutive_error_count",
                "error_state", "channel_status", "discovery_variant_id"):
        assert col in cols, f"Missing column on channels: {col}"


def test_channel_scan_result_new_columns():
    """ChannelScanResult must have discovered_by_variant_id and composite_score."""
    from app.db.models import ChannelScanResult
    cols = {c.key for c in ChannelScanResult.__table__.columns}
    assert "discovered_by_variant_id" in cols
    assert "composite_score" in cols


def test_alert_disposition_columns():
    """Alert must have the four new disposition columns from Task 1."""
    from app.db.models import Alert
    cols = {c.key for c in Alert.__table__.columns}
    for col in ("disposition", "disposition_notes", "disposition_by", "disposition_at"):
        assert col in cols, f"Missing column on alerts: {col}"


def test_seed_profile_unique_constraint():
    """SeedProfile must have a unique constraint on seed_text_normalised."""
    from app.db.models import SeedProfile
    constraint_names = {c.name for c in SeedProfile.__table__.constraints}
    assert "uq_seed_profiles_normalised" in constraint_names


def test_scan_evidence_unique_constraint():
    """ScanEvidence must have a unique constraint on (channel_username, telegram_message_id)."""
    from app.db.models import ScanEvidence
    constraint_names = {c.name for c in ScanEvidence.__table__.constraints}
    assert "uq_scan_evidence_channel_msg" in constraint_names


def test_pivot_candidate_unique_constraint():
    """PivotCandidate must have unique constraint on (candidate_value, source_channel_username)."""
    from app.db.models import PivotCandidate
    constraint_names = {c.name for c in PivotCandidate.__table__.constraints}
    assert "uq_pivot_candidates_value_channel" in constraint_names


# ── Settings (Task 3) ─────────────────────────────────────────────────────────

def test_new_settings_fields():
    """All new config fields added in Task 3 must be present and have correct defaults."""
    from app.core.config import settings
    assert settings.MIN_BACKOFF == 10
    assert settings.BACKOFF_MULTIPLIER == 2.0
    assert settings.MAX_RETRY_COUNT == 5
    assert settings.ERROR_STATE_WINDOW_HOURS == 24
    assert settings.ERROR_STATE_THRESHOLD == 3
    assert settings.POLL_INTERVAL_HIGH == 30
    assert settings.POLL_INTERVAL_MEDIUM == 60
    assert settings.POLL_INTERVAL_LOW == 300
    assert settings.COMPOSITE_HIGH_MSG_CAP == 10
    assert settings.COMPOSITE_INCIDENT_CAP == 5
    assert settings.COMPOSITE_PIVOT_CAP == 5


# ── Normaliser behaviour (Task 4) ────────────────────────────────────────────

def test_normalise_basic():
    from app.extractors.normaliser import normalise
    # Cyrillic confusables get replaced and lowercased
    assert normalise("сrасk") == "crack"


def test_normalise_zero_width_removal():
    from app.extractors.normaliser import normalise
    text_with_zwsp = "hello\u200bworld"
    assert normalise(text_with_zwsp) == "helloworld"


def test_normalise_repeated_punct():
    from app.extractors.normaliser import normalise
    assert normalise("wow!!!!!!") == "wow!!"


def test_normalise_hyphen_space():
    from app.extractors.normaliser import normalise
    assert normalise("drug-sale") == normalise("drug sale")


def test_normalise_immutability():
    from app.extractors.normaliser import normalise
    original = "hello\u200bworld"
    _ = normalise(original)
    assert original == "hello\u200bworld"
