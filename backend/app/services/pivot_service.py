"""
Pivot Service — extracts, persists, and manages pivot candidates.

Requirements: 4.1, 4.2, 4.3, 4.4
"""

from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.crud import (
    list_pivot_candidates,
    update_pivot_status,
    upsert_pivot_candidate,
)
from app.db.models import PivotCandidate

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_RE_PHONE = re.compile(r"(?<!\d)(\+?[0-9]{7,15})(?!\d)")
_RE_HANDLE = re.compile(r"@([A-Za-z][A-Za-z0-9_]{3,30})")
_RE_TGLINK = re.compile(r"t\.me/([A-Za-z0-9_]+)")
_RE_EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_RE_URL = re.compile(r"https?://[^\s]+")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_pivot_candidates(
    normalised_text: str,
    channel_username: str,  # noqa: ARG001  (kept for API symmetry)
) -> List[dict]:
    """
    Scan *normalised_text* and return a deduplicated list of pivot candidate
    dicts, each with keys ``candidate_type`` and ``candidate_value``.

    Extraction order:
    1. phone
    2. telegram_handle  (@handle)
    3. telegram_link    (t.me/slug)
    4. email
    5. url_domain       (bare domain from http[s] URLs)
    """
    seen: set[tuple[str, str]] = set()
    results: List[dict] = []

    def _add(candidate_type: str, candidate_value: str) -> None:
        key = (candidate_type, candidate_value)
        if key not in seen:
            seen.add(key)
            results.append(
                {"candidate_type": candidate_type, "candidate_value": candidate_value}
            )

    for m in _RE_PHONE.finditer(normalised_text):
        _add("phone", m.group(1))

    for m in _RE_HANDLE.finditer(normalised_text):
        _add("telegram_handle", m.group(1))

    for m in _RE_TGLINK.finditer(normalised_text):
        _add("telegram_link", m.group(1))

    for m in _RE_EMAIL.finditer(normalised_text):
        _add("email", m.group(0))

    for m in _RE_URL.finditer(normalised_text):
        parsed = urlparse(m.group(0))
        domain = parsed.netloc
        if domain:
            _add("url_domain", domain)

    return results


async def save_pivot_candidates(
    db: AsyncSession,
    candidates: List[dict],
    source_channel_username: str,
    source_scan_result_id: Optional[int] = None,
) -> List[PivotCandidate]:
    """
    Persist *candidates* (output of :func:`extract_pivot_candidates`) to the
    database, deduplicating via upsert, and return the resulting ORM objects.
    """
    objects: List[PivotCandidate] = []
    for c in candidates:
        obj = await upsert_pivot_candidate(
            db,
            source_channel_username=source_channel_username,
            candidate_type=c["candidate_type"],
            candidate_value=c["candidate_value"],
            source_scan_result_id=source_scan_result_id,
        )
        objects.append(obj)
    return objects


async def list_pending_pivots(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
) -> List[PivotCandidate]:
    """Return pivot candidates whose status is ``"pending"``."""
    return list(
        await list_pivot_candidates(db, status="pending", skip=skip, limit=limit)
    )


async def approve_pivot(
    db: AsyncSession,
    pivot_id: int,
    evaluated_by: str,
    notes: str = "",
) -> Optional[PivotCandidate]:
    """Set a pivot candidate's status to ``"approved"``."""
    return await update_pivot_status(
        db,
        pivot_id=pivot_id,
        status="approved",
        evaluated_by=evaluated_by,
        notes=notes,
    )


async def reject_pivot(
    db: AsyncSession,
    pivot_id: int,
    evaluated_by: str,
    notes: str = "",
) -> Optional[PivotCandidate]:
    """Set a pivot candidate's status to ``"rejected"``."""
    return await update_pivot_status(
        db,
        pivot_id=pivot_id,
        status="rejected",
        evaluated_by=evaluated_by,
        notes=notes,
    )
