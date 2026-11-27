"""
Property-based tests for compute_composite_score using Hypothesis.

**Validates: Requirements 5.1, 5.5**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings as h_settings, assume
from hypothesis import strategies as st

from app.services.scoring_service import compute_composite_score

# ---------------------------------------------------------------------------
# Shared strategy
# ---------------------------------------------------------------------------

evidence_strategy = st.lists(
    st.fixed_dictionaries({
        "classifier_score": st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        "risk_level": st.sampled_from(["critical", "high", "medium", "low"]),
        "severity_tier": st.sampled_from(["P1", "P2", "P3", "P4"]),
        "message_timestamp": st.one_of(st.none(), st.datetimes()),
    }),
    max_size=20,
)

REQUIRED_KEYS = {
    "composite_score",
    "max_message_score",
    "high_confidence_message_count",
    "distinct_incident_count",
    "recency_weight",
    "identifier_density",
    "valid_pivot_count",
    "analyst_confirmation_signal",
}

# ---------------------------------------------------------------------------
# Property 1 – Score always in [0.0, 1.0]
#
# **Validates: Requirements 5.1**
# ---------------------------------------------------------------------------

@given(
    evidence=evidence_strategy,
    valid_pivot_count=st.integers(min_value=0, max_value=100),
    analyst_signal=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
@h_settings(max_examples=200)
def test_score_always_in_unit_interval(evidence, valid_pivot_count, analyst_signal):
    """composite_score must always be in [0.0, 1.0] for any valid input."""
    result = compute_composite_score(
        evidence,
        valid_pivot_count=valid_pivot_count,
        analyst_signal=analyst_signal,
    )
    assert 0.0 <= result["composite_score"] <= 1.0


# ---------------------------------------------------------------------------
# Property 2 – Monotonicity: adding a high-score message never lowers the score
#
# **Validates: Requirements 5.1**
# ---------------------------------------------------------------------------

@given(
    evidence=evidence_strategy,
    valid_pivot_count=st.integers(min_value=0, max_value=10),
    analyst_signal=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
@h_settings(max_examples=200)
def test_adding_high_score_message_does_not_decrease_score(
    evidence, valid_pivot_count, analyst_signal
):
    """Adding a message with classifier_score=1.0 must not decrease composite_score."""
    base_result = compute_composite_score(
        evidence,
        valid_pivot_count=valid_pivot_count,
        analyst_signal=analyst_signal,
    )
    extended_evidence = evidence + [
        {
            "classifier_score": 1.0,
            "risk_level": "critical",
            "severity_tier": "P1",
            "message_timestamp": None,
        }
    ]
    extended_result = compute_composite_score(
        extended_evidence,
        valid_pivot_count=valid_pivot_count,
        analyst_signal=analyst_signal,
    )
    assert extended_result["composite_score"] >= base_result["composite_score"] - 1e-9


# ---------------------------------------------------------------------------
# Property 3 – Monotonicity: higher analyst_signal never lowers the score
#
# **Validates: Requirements 5.5**
# ---------------------------------------------------------------------------

@given(
    evidence=evidence_strategy,
    valid_pivot_count=st.integers(min_value=0, max_value=10),
)
@h_settings(max_examples=200)
def test_higher_analyst_signal_gives_higher_or_equal_score(evidence, valid_pivot_count):
    """Score with analyst_signal=1.0 must be >= score with analyst_signal=0.0."""
    score_low = compute_composite_score(
        evidence, valid_pivot_count=valid_pivot_count, analyst_signal=0.0
    )["composite_score"]
    score_high = compute_composite_score(
        evidence, valid_pivot_count=valid_pivot_count, analyst_signal=1.0
    )["composite_score"]
    assert score_high >= score_low - 1e-9


# ---------------------------------------------------------------------------
# Property 4 – Monotonicity: more valid pivots never lower the score
#
# **Validates: Requirements 5.1**
# ---------------------------------------------------------------------------

@given(
    evidence=evidence_strategy,
    base_pivots=st.integers(min_value=0, max_value=50),
    analyst_signal=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
@h_settings(max_examples=200)
def test_more_valid_pivots_does_not_decrease_score(
    evidence, base_pivots, analyst_signal
):
    """compute_composite_score with pivot_count+1 must be >= pivot_count."""
    score_base = compute_composite_score(
        evidence, valid_pivot_count=base_pivots, analyst_signal=analyst_signal
    )["composite_score"]
    score_more = compute_composite_score(
        evidence, valid_pivot_count=base_pivots + 1, analyst_signal=analyst_signal
    )["composite_score"]
    assert score_more >= score_base - 1e-9


# ---------------------------------------------------------------------------
# Property 5 – All required keys always present
#
# **Validates: Requirements 5.1**
# ---------------------------------------------------------------------------

@given(
    evidence=evidence_strategy,
    valid_pivot_count=st.integers(min_value=0, max_value=100),
    analyst_signal=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
@h_settings(max_examples=200)
def test_all_required_keys_always_present(evidence, valid_pivot_count, analyst_signal):
    """The returned dict must always contain all 8 required keys."""
    result = compute_composite_score(
        evidence,
        valid_pivot_count=valid_pivot_count,
        analyst_signal=analyst_signal,
    )
    assert REQUIRED_KEYS.issubset(set(result.keys()))
