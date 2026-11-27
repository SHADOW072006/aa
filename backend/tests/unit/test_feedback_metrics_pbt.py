"""
Property-based tests for app/services/feedback_service.py using Hypothesis.

**Validates: Requirements 6.1, 6.3, 7.1**

Properties tested:
  P1 – set_alert_disposition always raises ValueError for unknown dispositions
  P2 – update_poll_tier always raises ValueError for unknown tiers
  P3 – Valid disposition set never raises (mocked DB)
  P4 – get_disposition_audit_trail always returns a list (even for nonexistent targets)
  P5 – Audit trail changed_at is always an ISO 8601 string
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings as h_settings, assume
from hypothesis import strategies as st

from app.services.feedback_service import (
    get_disposition_audit_trail,
    set_alert_disposition,
    update_poll_tier,
)

# ---------------------------------------------------------------------------
# Valid-set constants (mirrored from feedback_service to keep tests self-contained)
# ---------------------------------------------------------------------------

_VALID_DISPOSITIONS = frozenset(
    {"confirmed_threat", "false_positive", "needs_review", "escalated"}
)
_VALID_TIERS = frozenset({"HIGH", "MEDIUM", "LOW"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    return db


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


# ---------------------------------------------------------------------------
# P1 – set_alert_disposition always raises ValueError for unknown dispositions
# **Validates: Requirements 6.1**
# ---------------------------------------------------------------------------

@given(st.text())
@h_settings(max_examples=200)
def test_invalid_disposition_always_raises(disposition: str):
    """
    **Validates: Requirements 6.1**

    For any string not in the valid disposition set, set_alert_disposition
    must raise ValueError before touching the database.
    """
    assume(disposition not in _VALID_DISPOSITIONS)

    db = _make_db()
    with pytest.raises(ValueError):
        asyncio.run(
            set_alert_disposition(
                db,
                alert_id=1,
                disposition=disposition,
                notes="",
                changed_by="analyst",
            )
        )
    # DB must NOT have been called — the guard fires before any I/O
    db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# P2 – update_poll_tier always raises ValueError for unknown tiers
# **Validates: Requirements 7.1**
# ---------------------------------------------------------------------------

@given(st.text())
@h_settings(max_examples=200)
def test_invalid_tier_always_raises(tier: str):
    """
    **Validates: Requirements 7.1**

    For any string not in {"HIGH", "MEDIUM", "LOW"}, update_poll_tier must
    raise ValueError before touching the database.
    """
    assume(tier not in _VALID_TIERS)

    db = _make_db()
    with pytest.raises(ValueError):
        asyncio.run(
            update_poll_tier(db, channel_id=1, new_tier=tier)
        )
    db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# P3 – Valid dispositions never raise ValueError (mocked DB)
# **Validates: Requirements 6.1**
# ---------------------------------------------------------------------------

@given(st.sampled_from(sorted(_VALID_DISPOSITIONS)))
@h_settings(max_examples=50)
def test_valid_disposition_never_raises(disposition: str):
    """
    **Validates: Requirements 6.1**

    Every member of the valid disposition set must be accepted without raising
    ValueError, regardless of which value is chosen.
    """
    db = _make_db()
    alert = MagicMock()
    alert.disposition = "needs_review"
    db.execute.return_value = _scalar_result(alert)

    with patch(
        "app.services.feedback_service.record_disposition_change",
        new_callable=AsyncMock,
    ):
        # Must not raise
        result = asyncio.run(
            set_alert_disposition(
                db,
                alert_id=1,
                disposition=disposition,
                notes="",
                changed_by="analyst",
            )
        )
    assert result is alert


# ---------------------------------------------------------------------------
# P4 – get_disposition_audit_trail always returns a list (Requirement 6.3)
# **Validates: Requirements 6.3**
# ---------------------------------------------------------------------------

@given(st.integers(), st.integers())
@h_settings(max_examples=200)
def test_audit_trail_always_returns_list(target_id: int, dummy: int):
    """
    **Validates: Requirements 6.3**

    get_disposition_audit_trail must return a list (possibly empty) for any
    target_id, never raising an exception.
    """
    db = _make_db()

    with patch(
        "app.services.feedback_service.get_disposition_history",
        new_callable=AsyncMock,
        return_value=[],
    ):
        result = asyncio.run(
            get_disposition_audit_trail(db, "alert", target_id)
        )

    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# P5 – Audit trail changed_at is always an ISO 8601 string
# **Validates: Requirements 6.3**
# ---------------------------------------------------------------------------

@given(
    st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2099, 12, 31)),
    st.integers(min_value=1, max_value=10_000),
)
@h_settings(max_examples=200)
def test_audit_trail_changed_at_is_iso_string(ts: datetime, entry_id: int):
    """
    **Validates: Requirements 6.3**

    For any datetime value stored on a disposition-history entry, the
    serialised changed_at field must be an ISO 8601 string containing both
    "-" (date separator) and either "T" or ":" (time separator).
    """
    db = _make_db()

    entry = MagicMock()
    entry.id = entry_id
    entry.previous_disposition = "needs_review"
    entry.new_disposition = "confirmed_threat"
    entry.changed_by = "analyst"
    entry.changed_at = ts
    entry.notes = "note"

    with patch(
        "app.services.feedback_service.get_disposition_history",
        new_callable=AsyncMock,
        return_value=[entry],
    ):
        trail = asyncio.run(
            get_disposition_audit_trail(db, "alert", entry_id)
        )

    assert len(trail) == 1
    changed_at = trail[0]["changed_at"]
    assert isinstance(changed_at, str), f"changed_at should be str, got {type(changed_at)}"
    # ISO 8601 date portion always contains "-" (e.g. "2024-06-01")
    assert "-" in changed_at, f"ISO string missing '-': {changed_at!r}"
    # ISO 8601 time portion contains "T" or ":" separator
    assert "T" in changed_at or ":" in changed_at, (
        f"ISO string missing time separator: {changed_at!r}"
    )
