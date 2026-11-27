"""
Unit tests for app/services/scoring_service.py
Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.scoring_service import compute_composite_score


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _evidence(
    classifier_score: float = 0.5,
    risk_level: str = "medium",
    severity_tier: str = "P3",
    message_timestamp: datetime | None = None,
) -> dict:
    return {
        "classifier_score": classifier_score,
        "risk_level": risk_level,
        "severity_tier": severity_tier,
        "message_timestamp": message_timestamp,
    }


# ---------------------------------------------------------------------------
# Empty evidence list → zeroed components
# ---------------------------------------------------------------------------

class TestEmptyEvidenceList:
    def test_returns_all_keys(self):
        result = compute_composite_score([])
        expected_keys = {
            "composite_score",
            "max_message_score",
            "high_confidence_message_count",
            "distinct_incident_count",
            "recency_weight",
            "identifier_density",
            "valid_pivot_count",
            "analyst_confirmation_signal",
        }
        assert expected_keys == result.keys()

    def test_max_message_score_zero_for_empty(self):
        result = compute_composite_score([])
        assert result["max_message_score"] == 0.0

    def test_high_confidence_count_zero_for_empty(self):
        result = compute_composite_score([])
        assert result["high_confidence_message_count"] == 0

    def test_distinct_incident_count_zero_for_empty(self):
        result = compute_composite_score([])
        assert result["distinct_incident_count"] == 0

    def test_identifier_density_zero_for_empty(self):
        result = compute_composite_score([])
        assert result["identifier_density"] == 0.0

    def test_recency_weight_min_for_empty(self):
        # No timestamps → minimum recency weight
        result = compute_composite_score([])
        assert result["recency_weight"] == 0.2


# ---------------------------------------------------------------------------
# Step 1: max_message_score
# ---------------------------------------------------------------------------

class TestMaxMessageScore:
    def test_capped_at_one(self):
        evidence = [_evidence(classifier_score=1.5)]
        result = compute_composite_score(evidence)
        assert result["max_message_score"] == 1.0

    def test_picks_max(self):
        evidence = [_evidence(classifier_score=0.3), _evidence(classifier_score=0.9)]
        result = compute_composite_score(evidence)
        assert result["max_message_score"] == pytest.approx(0.9)

    def test_single_item(self):
        evidence = [_evidence(classifier_score=0.6)]
        result = compute_composite_score(evidence)
        assert result["max_message_score"] == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# Step 2: high_confidence_message_count
# ---------------------------------------------------------------------------

class TestHighConfidenceCount:
    def test_counts_at_or_above_0_7(self):
        evidence = [
            _evidence(classifier_score=0.6),  # below threshold
            _evidence(classifier_score=0.7),  # exactly at threshold
            _evidence(classifier_score=0.9),  # above threshold
        ]
        result = compute_composite_score(evidence)
        assert result["high_confidence_message_count"] == 2

    def test_none_above_threshold(self):
        evidence = [_evidence(classifier_score=0.5), _evidence(classifier_score=0.69)]
        result = compute_composite_score(evidence)
        assert result["high_confidence_message_count"] == 0


# ---------------------------------------------------------------------------
# Step 3: distinct_incident_count (P1 and P2 severity tiers only)
# ---------------------------------------------------------------------------

class TestDistinctIncidentCount:
    def test_counts_p1_p2_only(self):
        evidence = [
            _evidence(severity_tier="P1"),
            _evidence(severity_tier="P2"),
            _evidence(severity_tier="P3"),  # excluded
        ]
        result = compute_composite_score(evidence)
        assert result["distinct_incident_count"] == 2

    def test_duplicate_tiers_counted_once(self):
        evidence = [
            _evidence(severity_tier="P1"),
            _evidence(severity_tier="P1"),
            _evidence(severity_tier="P2"),
        ]
        result = compute_composite_score(evidence)
        assert result["distinct_incident_count"] == 2

    def test_no_p1_p2(self):
        evidence = [_evidence(severity_tier="P3"), _evidence(severity_tier="LOW")]
        result = compute_composite_score(evidence)
        assert result["distinct_incident_count"] == 0


# ---------------------------------------------------------------------------
# Step 4: recency_weight
# ---------------------------------------------------------------------------

class TestRecencyWeight:
    def test_within_24h(self):
        ts = _now_utc() - timedelta(hours=12)
        result = compute_composite_score([_evidence(message_timestamp=ts)])
        assert result["recency_weight"] == 1.0

    def test_within_7_days(self):
        ts = _now_utc() - timedelta(days=3)
        result = compute_composite_score([_evidence(message_timestamp=ts)])
        assert result["recency_weight"] == 0.7

    def test_within_30_days(self):
        ts = _now_utc() - timedelta(days=15)
        result = compute_composite_score([_evidence(message_timestamp=ts)])
        assert result["recency_weight"] == 0.4

    def test_older_than_30_days(self):
        ts = _now_utc() - timedelta(days=60)
        result = compute_composite_score([_evidence(message_timestamp=ts)])
        assert result["recency_weight"] == 0.2

    def test_all_none_timestamps(self):
        result = compute_composite_score([_evidence(message_timestamp=None)])
        assert result["recency_weight"] == 0.2

    def test_uses_most_recent_timestamp(self):
        old_ts = _now_utc() - timedelta(days=60)
        new_ts = _now_utc() - timedelta(hours=6)
        evidence = [
            _evidence(message_timestamp=old_ts),
            _evidence(message_timestamp=new_ts),
        ]
        result = compute_composite_score(evidence)
        assert result["recency_weight"] == 1.0

    def test_naive_timestamps_handled(self):
        # Naive datetimes (no tzinfo) should not raise
        ts = datetime.utcnow() - timedelta(hours=1)
        assert ts.tzinfo is None
        result = compute_composite_score([_evidence(message_timestamp=ts)])
        assert result["recency_weight"] == 1.0


# ---------------------------------------------------------------------------
# Step 5: identifier_density
# ---------------------------------------------------------------------------

class TestIdentifierDensity:
    def test_density_calculation(self):
        evidence = [
            _evidence(risk_level="critical", classifier_score=0.9),  # counts
            _evidence(risk_level="high", classifier_score=0.8),       # counts
            _evidence(risk_level="medium", classifier_score=0.9),     # risk_level wrong
            _evidence(risk_level="critical", classifier_score=0.7),   # score too low
        ]
        result = compute_composite_score(evidence)
        assert result["identifier_density"] == pytest.approx(2 / 4)

    def test_density_zero_when_no_matches(self):
        evidence = [_evidence(risk_level="low", classifier_score=0.5)]
        result = compute_composite_score(evidence)
        assert result["identifier_density"] == 0.0


# ---------------------------------------------------------------------------
# Step 6 & 7: pivot count and composite formula
# ---------------------------------------------------------------------------

class TestCompositScore:
    def test_composite_clamped_to_zero_minimum(self):
        result = compute_composite_score([])
        # Min possible: 0.15 * 0.2 (recency) = 0.03 — still ≥ 0
        assert result["composite_score"] >= 0.0

    def test_composite_clamped_to_one_maximum(self):
        ts = _now_utc()
        evidence = [
            _evidence(classifier_score=1.0, risk_level="critical",
                      severity_tier="P1", message_timestamp=ts)
        ] * 20  # many high-score items
        result = compute_composite_score(evidence, valid_pivot_count=10, analyst_signal=2.0)
        assert result["composite_score"] <= 1.0

    def test_analyst_signal_capped_at_one(self):
        result = compute_composite_score([], analyst_signal=5.0)
        assert result["analyst_confirmation_signal"] == 1.0

    def test_valid_pivot_count_passthrough(self):
        result = compute_composite_score([], valid_pivot_count=3)
        assert result["valid_pivot_count"] == 3

    def test_known_weights_calculation(self):
        """Verify the weighted formula with controlled inputs."""
        from app.core.config import settings

        ts = _now_utc() - timedelta(hours=1)  # recency = 1.0
        # 1 item: score 0.9, risk=critical, severity=P1
        evidence = [
            _evidence(classifier_score=0.9, risk_level="critical",
                      severity_tier="P1", message_timestamp=ts)
        ]
        result = compute_composite_score(evidence, valid_pivot_count=1, analyst_signal=0.5)

        max_msg = 0.9
        high_msg_norm = min(1, settings.COMPOSITE_HIGH_MSG_CAP) / settings.COMPOSITE_HIGH_MSG_CAP
        incident_norm = min(1, settings.COMPOSITE_INCIDENT_CAP) / settings.COMPOSITE_INCIDENT_CAP
        recency = 1.0
        density = 1.0  # 1/1 matches criteria
        pivot_norm = min(1, settings.COMPOSITE_PIVOT_CAP) / settings.COMPOSITE_PIVOT_CAP

        expected = (
            0.30 * max_msg
            + 0.20 * high_msg_norm
            + 0.15 * incident_norm
            + 0.15 * recency
            + 0.10 * density
            + 0.05 * pivot_norm
            + 0.05 * 0.5
        )
        expected = max(0.0, min(1.0, expected))
        assert result["composite_score"] == pytest.approx(expected, abs=1e-6)
