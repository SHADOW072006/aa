"""
Unit tests for app/services/feedback_service.py
Requirements: 6.1, 6.2, 6.3, 7.1, 14.1, 14.4
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.feedback_service import (
    get_disposition_audit_trail,
    set_alert_disposition,
    set_evidence_disposition,
    update_poll_tier,
)
from app.core.config import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db() -> AsyncMock:
    """Return a minimal async DB session mock."""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    return db


def _scalar_result(value):
    """Wrap a value as a scalar_one_or_none result."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


# ---------------------------------------------------------------------------
# set_alert_disposition — disposition validation (Requirement 6.1)
# ---------------------------------------------------------------------------

class TestSetAlertDispositionValidation:
    """set_alert_disposition raises ValueError on bad inputs; succeeds on good ones."""

    def test_valid_disposition_confirmed_threat_does_not_raise(self):
        """confirmed_threat is accepted without raising ValueError (Req 6.1)."""
        db = _make_db()
        alert = MagicMock()
        alert.disposition = "needs_review"
        db.execute.return_value = _scalar_result(alert)

        with patch("app.services.feedback_service.record_disposition_change", new_callable=AsyncMock):
            result = asyncio.run(
                set_alert_disposition(db, alert_id=1, disposition="confirmed_threat",
                                      notes="verified", changed_by="analyst1")
            )
        # Returned the alert (not None)
        assert result is alert

    def test_invalid_disposition_raises_value_error(self):
        """Unrecognised disposition raises ValueError (Req 6.1)."""
        db = _make_db()
        with pytest.raises(ValueError, match="unknown_value"):
            asyncio.run(
                set_alert_disposition(db, alert_id=1, disposition="unknown_value",
                                      notes="", changed_by="analyst1")
            )

    def test_empty_disposition_raises_value_error(self):
        """Empty string disposition raises ValueError (Req 6.1)."""
        db = _make_db()
        with pytest.raises(ValueError):
            asyncio.run(
                set_alert_disposition(db, alert_id=1, disposition="",
                                      notes="", changed_by="analyst1")
            )

    def test_null_disposition_raises_value_error(self):
        """None disposition raises ValueError (Req 6.1)."""
        db = _make_db()
        with pytest.raises((ValueError, TypeError)):
            asyncio.run(
                set_alert_disposition(db, alert_id=1, disposition=None,  # type: ignore[arg-type]
                                      notes="", changed_by="analyst1")
            )

    def test_missing_alert_returns_none(self):
        """Returns None when alert_id does not exist (Req 6.1)."""
        db = _make_db()
        db.execute.return_value = _scalar_result(None)

        with patch("app.services.feedback_service.record_disposition_change", new_callable=AsyncMock):
            result = asyncio.run(
                set_alert_disposition(db, alert_id=999, disposition="false_positive",
                                      notes="", changed_by="analyst1")
            )
        assert result is None


# ---------------------------------------------------------------------------
# set_evidence_disposition — all valid values accepted (Requirement 6.2)
# ---------------------------------------------------------------------------

class TestSetEvidenceDispositionValidation:
    """set_evidence_disposition accepts all four valid dispositions (Req 6.2)."""

    @pytest.mark.parametrize("disposition", [
        "confirmed_threat", "false_positive", "needs_review", "escalated"
    ])
    def test_all_valid_dispositions_accepted(self, disposition: str):
        """Every member of the valid-dispositions set passes without ValueError (Req 6.2)."""
        db = _make_db()
        evidence = MagicMock()
        evidence.disposition = "needs_review"
        evidence.channel_scan_result_id = None
        db.execute.return_value = _scalar_result(evidence)

        with (
            patch("app.services.feedback_service.record_disposition_change", new_callable=AsyncMock),
            patch("app.services.feedback_service.update_evidence_disposition",
                  new_callable=AsyncMock, return_value=evidence),
        ):
            result = asyncio.run(
                set_evidence_disposition(db, evidence_id=1, disposition=disposition,
                                         notes="ok", changed_by="analyst1")
            )
        # Should not raise; result is the evidence object
        assert result is evidence

    def test_invalid_evidence_disposition_raises_value_error(self):
        """Unrecognised disposition raises ValueError (Req 6.2)."""
        db = _make_db()
        with pytest.raises(ValueError, match="bad_disposition"):
            asyncio.run(
                set_evidence_disposition(db, evidence_id=1, disposition="bad_disposition",
                                         notes="", changed_by="analyst1")
            )

    def test_missing_evidence_returns_none(self):
        """Returns None when evidence_id does not exist (Req 6.2)."""
        db = _make_db()
        db.execute.return_value = _scalar_result(None)

        with patch("app.services.feedback_service.record_disposition_change", new_callable=AsyncMock):
            result = asyncio.run(
                set_evidence_disposition(db, evidence_id=404, disposition="false_positive",
                                         notes="", changed_by="analyst1")
            )
        assert result is None


# ---------------------------------------------------------------------------
# update_poll_tier — tier validation (Requirement 7.1)
# ---------------------------------------------------------------------------

class TestUpdatePollTierValidation:
    """update_poll_tier accepts HIGH/MEDIUM/LOW and rejects everything else (Req 7.1)."""

    @pytest.mark.parametrize("tier", ["HIGH", "MEDIUM", "LOW"])
    def test_valid_tiers_accepted(self, tier: str):
        """All canonical tier values are accepted without ValueError (Req 7.1)."""
        db = _make_db()
        channel = MagicMock()
        channel.poll_tier = "LOW"
        db.execute.return_value = _scalar_result(channel)

        result = asyncio.run(
            update_poll_tier(db, channel_id=1, new_tier=tier)
        )
        assert result is channel
        assert channel.poll_tier == tier

    def test_invalid_tier_ultra_raises_value_error(self):
        """Tier 'ULTRA' raises ValueError (Req 7.1)."""
        db = _make_db()
        with pytest.raises(ValueError, match="ULTRA"):
            asyncio.run(
                update_poll_tier(db, channel_id=1, new_tier="ULTRA")
            )

    def test_lowercase_high_raises_value_error(self):
        """
        Lowercase 'high' is NOT in the valid set (which uses uppercase only).
        The service should raise ValueError for 'high' (Req 7.1).
        This test documents the case-sensitive behaviour.
        """
        db = _make_db()
        with pytest.raises(ValueError, match="high"):
            asyncio.run(
                update_poll_tier(db, channel_id=1, new_tier="high")
            )

    def test_missing_channel_returns_none(self):
        """Returns None when channel_id does not exist (Req 7.1)."""
        db = _make_db()
        db.execute.return_value = _scalar_result(None)

        result = asyncio.run(
            update_poll_tier(db, channel_id=999, new_tier="HIGH")
        )
        assert result is None


# ---------------------------------------------------------------------------
# get_disposition_audit_trail — output format (Requirement 14.1, 14.4)
# ---------------------------------------------------------------------------

class TestGetDispositionAuditTrail:
    """Audit-trail entries have the required keys and correct types (Req 14.1, 14.4)."""

    def _make_history_entry(self, entry_id: int, changed_at: datetime) -> MagicMock:
        entry = MagicMock()
        entry.id = entry_id
        entry.previous_disposition = "needs_review"
        entry.new_disposition = "confirmed_threat"
        entry.changed_by = "analyst_a"
        entry.changed_at = changed_at
        entry.notes = "High confidence"
        return entry

    def test_returned_dicts_have_required_keys(self):
        """Each entry contains id, previous_disposition, new_disposition, changed_by, changed_at, notes (Req 14.1)."""
        db = _make_db()
        entry = self._make_history_entry(1, datetime(2024, 6, 1, 12, 0, 0))

        with patch(
            "app.services.feedback_service.get_disposition_history",
            new_callable=AsyncMock,
            return_value=[entry],
        ):
            trail = asyncio.run(
                get_disposition_audit_trail(db, "alert", 1)
            )

        assert len(trail) == 1
        required_keys = {"id", "previous_disposition", "new_disposition",
                         "changed_by", "changed_at", "notes"}
        assert required_keys == set(trail[0].keys())

    def test_changed_at_is_iso_string(self):
        """changed_at is an ISO-formatted string (contains 'T' or '-') (Req 14.4)."""
        db = _make_db()
        entry = self._make_history_entry(2, datetime(2024, 6, 1, 15, 30, 0))

        with patch(
            "app.services.feedback_service.get_disposition_history",
            new_callable=AsyncMock,
            return_value=[entry],
        ):
            trail = asyncio.run(
                get_disposition_audit_trail(db, "evidence", 2)
            )

        changed_at = trail[0]["changed_at"]
        assert isinstance(changed_at, str)
        # ISO 8601 always contains either 'T' (datetime) or '-' (date) separators
        assert "T" in changed_at or "-" in changed_at

    def test_empty_history_returns_empty_list(self):
        """When no history exists the function returns an empty list (Req 14.1)."""
        db = _make_db()

        with patch(
            "app.services.feedback_service.get_disposition_history",
            new_callable=AsyncMock,
            return_value=[],
        ):
            trail = asyncio.run(
                get_disposition_audit_trail(db, "alert", 999)
            )

        assert trail == []

    def test_multiple_entries_all_serialised(self):
        """Multiple history entries are all returned (Req 14.4)."""
        db = _make_db()
        entries = [
            self._make_history_entry(i, datetime(2024, 1, i + 1, 10, 0, 0))
            for i in range(1, 4)
        ]

        with patch(
            "app.services.feedback_service.get_disposition_history",
            new_callable=AsyncMock,
            return_value=entries,
        ):
            trail = asyncio.run(
                get_disposition_audit_trail(db, "alert", 5)
            )

        assert len(trail) == 3
        assert all(isinstance(e["changed_at"], str) for e in trail)


# ---------------------------------------------------------------------------
# Poll tier constants (Requirement 6.3, 7.1)
# ---------------------------------------------------------------------------

class TestPollTierConstants:
    """settings values satisfy expected ordering and positivity invariants (Req 6.3, 7.1)."""

    def test_high_interval_less_than_medium(self):
        """HIGH poll interval is shorter than MEDIUM (Req 7.1)."""
        assert settings.POLL_INTERVAL_HIGH < settings.POLL_INTERVAL_MEDIUM

    def test_medium_interval_less_than_low(self):
        """MEDIUM poll interval is shorter than LOW (Req 7.1)."""
        assert settings.POLL_INTERVAL_MEDIUM < settings.POLL_INTERVAL_LOW

    def test_strict_ordering_high_medium_low(self):
        """HIGH < MEDIUM < LOW is a single transitive assertion (Req 7.1)."""
        assert settings.POLL_INTERVAL_HIGH < settings.POLL_INTERVAL_MEDIUM < settings.POLL_INTERVAL_LOW

    def test_error_state_threshold_positive(self):
        """ERROR_STATE_THRESHOLD must be greater than zero (Req 6.3)."""
        assert settings.ERROR_STATE_THRESHOLD > 0

    def test_max_retry_count_positive(self):
        """MAX_RETRY_COUNT must be greater than zero (Req 6.3)."""
        assert settings.MAX_RETRY_COUNT > 0
