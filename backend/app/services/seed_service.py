"""
Seed Service — business logic for SeedProfile lifecycle and variant generation.

Public functions
----------------
generate_variants(seed_text, language_region) -> List[dict]
    Produce deduplicated query variants (at most 2 tokens each) from a seed.

create_seed(db, ...) -> SeedProfile
    Validate uniqueness, persist profile, generate and persist variants.

get_seed(db, profile_id) -> SeedProfile | None
update_seed(db, profile_id, **kwargs) -> SeedProfile | None
list_seeds(db, ...) -> list[SeedProfile]
deactivate_seed(db, profile_id) -> bool
get_seed_performance(db, profile_id) -> dict
get_active_variants(db) -> List[Tuple[QueryVariant, SeedProfile]]
"""

from __future__ import annotations

import logging
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.crud import (
    create_query_variant,
    create_seed_profile,
    deactivate_seed_profile,
    get_seed_profile_by_id,
    get_seed_profile_by_normalised,
    get_variant_by_text,
    get_variants_for_seed,
    list_seed_profiles,
    update_seed_profile,
)
from app.db.models import AuditLog, QueryVariant, QueryVariantExecution, SeedProfile
from app.extractors.normaliser import normalise as normalise_seed

logger = logging.getLogger(__name__)

VALID_SEED_STATUSES = frozenset({"proposed", "active", "paused", "retired"})
VALID_SEED_PROFILES = frozenset({"illegal_trade", "discovery", "finance_scam", "gambling_betting", "extended_legacy"})
VALID_SEED_ROLES = frozenset({"discovery", "indicator"})
_ALLOWED_TRANSITIONS = {
    "proposed": {"active", "retired"},
    "active": {"paused", "retired"},
    "paused": {"active", "retired"},
    "retired": set(),
}

# ---------------------------------------------------------------------------
# Contextual suffix fallback — guarantees ≥3 variants for single-token seeds.
# Maps threat_category to the most useful contextual suffix.
# ---------------------------------------------------------------------------
_CATEGORY_SUFFIXES: dict[str, str] = {
    "drugs": "sale",
    "narcotics": "sale",
    "weapons": "buy",
    "firearms": "buy",
    "fraud": "order",
    "scam": "order",
    "default": "sale",
}


def _get_suffix(threat_category: str) -> str:
    return _CATEGORY_SUFFIXES.get(threat_category.lower(), _CATEGORY_SUFFIXES["default"])


def _enforce_two_tokens(variant: str) -> bool:
    """Return True if the variant has at most 2 whitespace-separated tokens."""
    return len(variant.strip().split()) <= 2


def _dedup_ordered(variants: list[str]) -> list[str]:
    """Remove duplicates from a list while preserving insertion order."""
    seen: set[str] = set()
    result: list[str] = []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            result.append(v)
    return result


# ---------------------------------------------------------------------------
# generate_variants
# ---------------------------------------------------------------------------

def generate_variants(seed_text: str, language_region: str) -> List[dict]:
    """
    Return a deduplicated list of search query variant dicts derived from seed_text.

    Each dict has:
        "variant_text" : str  — the variant (at most 2 tokens)
        "variant_type" : str  — spacing | hyphen | transliteration_to_latin |
                                transliteration_to_devanagari | suffix_fallback

    At least 3 distinct variants are always returned.  A contextual-suffix
    fallback is applied for single-token seeds that would otherwise produce
    fewer than 3.

    Parameters
    ----------
    seed_text : str
        The raw seed string as supplied by the caller.
    language_region : str
        BCP-47 region code, e.g. ``"en"``, ``"hi-IN"``.

    Returns
    -------
    List[dict]
        Deduplicated variant dicts.
    """
    normalised = normalise_seed(seed_text)
    tokens = normalised.split()

    candidates: list[tuple[str, str]] = []  # (variant_text, variant_type)

    # Step 2 — spacing variants (adjacent 2-token slices)
    if len(tokens) >= 2:
        for i in range(len(tokens) - 1):
            candidates.append((f"{tokens[i]} {tokens[i + 1]}", "spacing"))
    else:
        # Single-token seed: use it as the spacing variant.
        candidates.append((tokens[0] if tokens else normalised, "spacing"))

    # Step 3 — hyphen variant (first two tokens joined with hyphen → then
    # normalised back to space by normalise_seed step 7).
    # We store the hyphenated string; it differs from the spacing variant
    # only before normalisation is re-applied, but we emit both for query
    # breadth since some channels use hyphenated terms.
    if len(tokens) >= 2:
        hyphen_raw = "-".join(tokens[:2])
        # After normalise, hyphens become spaces — but we keep the raw
        # hyphenated form as the variant_text so the collector can search it.
        candidates.append((hyphen_raw, "hyphen"))

    # Step 4 — transliteration variants (for hi, hi-IN, hinglish)
    if language_region in ("hi-IN", "hi", "hinglish"):
        try:
            from indic_transliteration import sanscript  # type: ignore[import]
            from indic_transliteration.sanscript import transliterate  # type: ignore[import]

            # Detect script: Devanagari codepoints are U+0900–U+097F
            is_devanagari = any("\u0900" <= ch <= "\u097f" for ch in normalised)
            if is_devanagari:
                latin = transliterate(normalised, sanscript.DEVANAGARI, sanscript.ITRANS)
                latin_tokens = latin.split()[:2]
                candidates.append((" ".join(latin_tokens), "transliteration_to_latin"))
            else:
                deva = transliterate(normalised, sanscript.ITRANS, sanscript.DEVANAGARI)
                deva_tokens = deva.split()[:2]
                candidates.append((" ".join(deva_tokens), "transliteration_to_devanagari"))
        except Exception:
            logger.debug("indic_transliteration unavailable; skipping hi-IN variants")

    # Step 5 — enforce two-token max
    filtered: list[tuple[str, str]] = [
        (v, t) for v, t in candidates if v.strip() and _enforce_two_tokens(v)
    ]

    # Step 6 — deduplicate within generated list (preserve order)
    seen_texts: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for v, t in filtered:
        if v not in seen_texts:
            seen_texts.add(v)
            deduped.append((v, t))

    # Step 7 — fallback for single-token seeds (guarantee ≥3 distinct variants)
    # At this point we may have only 1 variant (the token itself via spacing),
    # because the hyphen variant collapses to the same string when len(tokens)==1.
    # We append suffix variants until we reach at least 3.
    base = tokens[0] if tokens else normalised
    for suffix in ("sale", "buy", "order"):
        if len(deduped) >= 3:
            break
        candidate = f"{base} {suffix}"
        if candidate not in seen_texts and _enforce_two_tokens(candidate):
            seen_texts.add(candidate)
            deduped.append((candidate, "suffix_fallback"))

    return [{"variant_text": v, "variant_type": t} for v, t in deduped]


# ---------------------------------------------------------------------------
# Internal: persist variants for a profile, applying global dedup
# ---------------------------------------------------------------------------

async def _persist_variants(
    db: AsyncSession,
    profile: SeedProfile,
    normalised: str,
    language_region: str,
) -> None:
    """
    Generate variants from *normalised* text and write them to the database.

    The canonical variant (the normalised seed itself) is always written first
    with ``is_canonical=True``.  All generated variants follow.  For each
    candidate, an existing row with the same ``variant_text`` is reused via the
    global dedup lookup (``get_variant_by_text``); no duplicate rows are
    inserted.
    """
    # Canonical variant — the normalised seed text itself.
    existing_canonical = await get_variant_by_text(db, normalised)
    if existing_canonical is None:
        await create_query_variant(
            db,
            seed_profile_id=profile.id,
            variant_text=normalised,
            variant_type="canonical",
            is_canonical=True,
        )
    # Note: if the canonical variant_text already belongs to another seed we
    # still record it here tied to this seed's profile_id; the UniqueConstraint
    # will reject it.  Callers should deduplicate at the seed level first.

    # Generated variants.
    generated = generate_variants(profile.seed_text, language_region)
    for item in generated:
        v_text = item["variant_text"]
        v_type = item["variant_type"]
        if v_text == normalised:
            # Already covered by the canonical row above.
            continue
        existing = await get_variant_by_text(db, v_text)
        if existing is None:
            await create_query_variant(
                db,
                seed_profile_id=profile.id,
                variant_text=v_text,
                variant_type=v_type,
                is_canonical=False,
            )
        # else: global dedup — reuse the existing row; no new insert.


# ---------------------------------------------------------------------------
# create_seed
# ---------------------------------------------------------------------------

async def create_seed(
    db: AsyncSession,
    seed_text: str,
    threat_category: str,
    language_region: str,
    intent_type: str,
    priority: int,
    created_source: str,
    *,
    profile: str = "illegal_trade",
    seed_role: str = "indicator",
    status: Optional[str] = None,
    rationale: Optional[str] = None,
    approved_by: Optional[str] = None,
) -> SeedProfile:
    """
    Create a new SeedProfile together with its auto-generated QueryVariants.

    Broad/risky seeds (seed_role='discovery' or profile != 'illegal_trade')
    start in 'proposed' status unless approved_by is provided or status is
    explicitly set for default catalogue seeding.
    """
    if profile not in VALID_SEED_PROFILES:
        raise ValueError(f"Invalid profile {profile!r}")
    if seed_role not in VALID_SEED_ROLES:
        raise ValueError(f"Invalid seed_role {seed_role!r}")

    if status is None:
        if (seed_role == "discovery" or profile != "illegal_trade") and not approved_by:
            effective_status = "proposed"
        else:
            effective_status = "active"
    else:
        if status not in VALID_SEED_STATUSES:
            raise ValueError(f"Invalid status {status!r}")
        effective_status = status

    normalised = normalise_seed(seed_text)

    existing = await get_seed_profile_by_normalised(db, normalised)
    if existing is not None:
        raise ValueError("Seed already exists")

    sp = await create_seed_profile(
        db,
        seed_text=seed_text,
        threat_category=threat_category,
        language_region=language_region,
        intent_type=intent_type,
        priority=priority,
        created_source=created_source,
        profile=profile,
        seed_role=seed_role,
        status=effective_status,
        rationale=rationale,
        is_active=(effective_status == "active"),
    )

    if approved_by:
        db.add(AuditLog(
            actor=approved_by,
            action="seed_status_change",
            target_type="seed_profile",
            target_id=sp.id,
            details=f'{{"from": null, "to": "{effective_status}", "seed_role": "{seed_role}"}}',
        ))
        await db.flush()

    await _persist_variants(db, sp, normalised, language_region)

    return sp


# ---------------------------------------------------------------------------
# get_seed
# ---------------------------------------------------------------------------

async def get_seed(
    db: AsyncSession, profile_id: int
) -> Optional[SeedProfile]:
    """Return a SeedProfile by primary key, or None if not found."""
    return await get_seed_profile_by_id(db, profile_id)


# ---------------------------------------------------------------------------
# list_seeds
# ---------------------------------------------------------------------------

async def list_seeds(
    db: AsyncSession,
    is_active: Optional[bool] = None,
    threat_category: Optional[str] = None,
    profile: Optional[str] = None,
    status: Optional[str] = None,
    seed_role: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> Sequence[SeedProfile]:
    """Return a filtered, paginated list of SeedProfiles."""
    return await list_seed_profiles(
        db,
        is_active=is_active,
        threat_category=threat_category,
        profile=profile,
        status=status,
        seed_role=seed_role,
        skip=skip,
        limit=limit,
    )


async def transition_seed_status(
    db: AsyncSession,
    profile_id: int,
    new_status: str,
    *,
    actor: str,
    rationale: Optional[str] = None,
) -> Optional[SeedProfile]:
    """Transition a seed through proposed -> active -> paused -> retired with audit log."""
    if new_status not in VALID_SEED_STATUSES:
        raise ValueError(f"Invalid status {new_status!r}")
    sp = await get_seed_profile_by_id(db, profile_id)
    if sp is None:
        return None
    old_status = sp.status or ("active" if sp.is_active else "paused")
    if new_status != old_status and new_status not in _ALLOWED_TRANSITIONS.get(old_status, set()):
        raise ValueError(f"Transition {old_status!r} -> {new_status!r} is not allowed")
    if new_status == "active" and (sp.seed_role == "discovery" or sp.profile != "illegal_trade") and not actor.strip():
        raise ValueError("Analyst approval (actor) required to activate broad/risky seed")

    sp.status = new_status
    sp.is_active = (new_status == "active")
    if rationale is not None:
        sp.rationale = rationale
    await db.flush()

    import json
    db.add(AuditLog(
        actor=actor,
        action="seed_status_change",
        target_type="seed_profile",
        target_id=sp.id,
        details=json.dumps({"from": old_status, "to": new_status, "rationale": rationale}),
    ))
    await db.flush()
    return sp


async def get_seed_summary(db: AsyncSession) -> dict:
    """Return actual seed counts and distribution by category, profile, status, and role."""
    rows = (await db.execute(select(SeedProfile))).scalars().all()
    by_category: dict[str, int] = {}
    by_profile: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_role: dict[str, int] = {}
    for r in rows:
        by_category[r.threat_category] = by_category.get(r.threat_category, 0) + 1
        p = getattr(r, "profile", "illegal_trade") or "illegal_trade"
        by_profile[p] = by_profile.get(p, 0) + 1
        st = getattr(r, "status", "active") or "active"
        by_status[st] = by_status.get(st, 0) + 1
        rl = getattr(r, "seed_role", "indicator") or "indicator"
        by_role[rl] = by_role.get(rl, 0) + 1
    return {
        "total": len(rows),
        "by_category": by_category,
        "by_profile": by_profile,
        "by_status": by_status,
        "by_role": by_role,
    }


def _non_core_target_profile(threat_category: str) -> str:
    cat = (threat_category or "").lower()
    if cat in ("scam", "investment_fraud", "colour_trading_scam", "task_scam", "lottery_scam", "pig_butchering", "job_fraud"):
        return "finance_scam"
    if cat in ("gambling", "gambling_scam"):
        return "gambling_betting"
    return "extended_legacy"


async def sync_seed_catalogue(db: AsyncSession) -> dict:
    """
    Versioned, idempotent seed catalogue synchronization.
    - Never deletes existing seed records.
    - Moves/pauses any non-core seeds out of 'illegal_trade'.
    - Upserts DEFAULT_SEED_CATALOGUE (+ local overlay) and FINANCE_SCAM_SEED_CATALOGUE
      by normalised seed identity.
    """
    from app.services.seed_defaults import (
        CATALOGUE_VERSION,
        DEFAULT_SEED_CATALOGUE,
        DISCOVERY_SEED_CATALOGUE,
        FINANCE_SCAM_SEED_CATALOGUE,
        ILLEGAL_TRADE_CATEGORIES,
        load_local_seeds_overlay,
    )

    core_set = set(ILLEGAL_TRADE_CATEGORIES)
    created = 0
    updated = 0
    moved_non_core = 0

    # 1. Move/pause any non-core seeds currently in illegal_trade
    existing_rows = (await db.execute(select(SeedProfile))).scalars().all()
    for sp in existing_rows:
        if (sp.profile or "illegal_trade") == "illegal_trade" and sp.threat_category not in core_set:
            sp.profile = _non_core_target_profile(sp.threat_category)
            sp.status = "paused"
            sp.is_active = False
            if not sp.rationale:
                sp.rationale = "Moved out of default illegal_trade profile during catalogue sync"
            moved_non_core += 1

    await db.flush()

    # 2. Upsert core illegal_trade + overlay + discovery + separated finance/gambling catalogues
    all_entries = [
        *DEFAULT_SEED_CATALOGUE,
        *load_local_seeds_overlay(),
        *DISCOVERY_SEED_CATALOGUE,
        *FINANCE_SCAM_SEED_CATALOGUE,
    ]
    for entry in all_entries:
        seed_text = entry["seed_text"]
        norm = normalise_seed(seed_text)
        target_profile = entry.get("profile", "illegal_trade")
        target_status = entry.get("status", "active" if target_profile == "illegal_trade" else "paused")
        target_role = entry.get("seed_role", "indicator")
        target_active = (target_status == "active")

        sp = await get_seed_profile_by_normalised(db, norm)
        if sp is None:
            sp = await create_seed_profile(
                db,
                seed_text=seed_text,
                threat_category=entry["threat_category"],
                language_region=entry.get("language_region", "en"),
                intent_type=entry["intent_type"],
                priority=entry.get("priority", 3),
                created_source="default",
                profile=target_profile,
                seed_role=target_role,
                status=target_status,
                rationale=entry.get("rationale"),
                is_active=target_active,
            )
            sp.catalogue_version = CATALOGUE_VERSION
            await db.flush()
            await _persist_variants(db, sp, norm, sp.language_region)
            created += 1
        else:
            changed = (
                sp.seed_text != seed_text
                or sp.threat_category != entry["threat_category"]
                or sp.language_region != entry.get("language_region", "en")
                or sp.intent_type != entry["intent_type"]
                or sp.priority != entry.get("priority", 3)
                or sp.profile != target_profile
                or sp.seed_role != target_role
                or sp.status != target_status
                or sp.is_active != target_active
                or sp.rationale != entry.get("rationale")
                or sp.catalogue_version != CATALOGUE_VERSION
            )
            if changed:
                sp.seed_text = seed_text
                sp.threat_category = entry["threat_category"]
                sp.language_region = entry.get("language_region", "en")
                sp.intent_type = entry["intent_type"]
                sp.priority = entry.get("priority", 3)
                sp.profile = target_profile
                sp.seed_role = target_role
                sp.status = target_status
                sp.is_active = target_active
                sp.rationale = entry.get("rationale")
                sp.catalogue_version = CATALOGUE_VERSION
                await db.flush()
                updated += 1
            existing_vars = await get_variants_for_seed(db, sp.id)
            if not existing_vars:
                await _persist_variants(db, sp, norm, sp.language_region)

    await db.flush()
    active_core = (
        await db.execute(
            select(func.count(SeedProfile.id)).where(
                SeedProfile.profile == "illegal_trade",
                SeedProfile.status == "active",
                SeedProfile.is_active == True,  # noqa: E712
            )
        )
    ).scalar_one()

    return {
        "catalogue_version": CATALOGUE_VERSION,
        "created": created,
        "updated": updated,
        "moved_non_core": moved_non_core,
        "active_illegal_trade_count": active_core,
    }


# ---------------------------------------------------------------------------
# update_seed
# ---------------------------------------------------------------------------

async def update_seed(
    db: AsyncSession, profile_id: int, **kwargs
) -> Optional[SeedProfile]:
    """
    Update a SeedProfile by primary key.

    If *seed_text* is supplied in ``kwargs``, it is re-normalised and
    ``seed_text_normalised`` is updated automatically before delegating to
    ``update_seed_profile``.

    Returns None if the profile is not found.
    """
    if "seed_text" in kwargs:
        new_seed_text = kwargs["seed_text"]
        kwargs["seed_text_normalised"] = normalise_seed(new_seed_text)

    return await update_seed_profile(db, profile_id, **kwargs)


# ---------------------------------------------------------------------------
# deactivate_seed
# ---------------------------------------------------------------------------

async def deactivate_seed(db: AsyncSession, profile_id: int) -> bool:
    """
    Set ``is_active=False`` on the specified SeedProfile.

    Returns True if the profile was found and deactivated, False otherwise.
    """
    return await deactivate_seed_profile(db, profile_id)


# ---------------------------------------------------------------------------
# get_seed_performance
# ---------------------------------------------------------------------------

async def get_seed_performance(db: AsyncSession, profile_id: int) -> dict:
    """
    Return a performance summary for the given SeedProfile.

    The returned dict has the shape::

        {
            "seed_profile_id": <int>,
            "total_variants": <int>,
            "total_executions": <int>,   # sum of channels_found across all executions
            "total_channels_added": <int>,
            "variants": [
                {
                    "variant_text": <str>,
                    "variant_type": <str>,
                    "executions": <int>,  # count of execution rows
                },
                ...
            ],
        }
    """
    # Fetch all variants for this seed.
    variants: Sequence[QueryVariant] = await get_variants_for_seed(db, profile_id)

    variant_ids = [v.id for v in variants]
    total_variants = len(variants)

    # Aggregate execution stats across all variants in one query.
    total_executions = 0
    total_channels_added = 0
    exec_counts: dict[int, int] = {}  # variant_id → execution row count

    if variant_ids:
        # Sum channels_found and channels_added per variant.
        agg_result = await db.execute(
            select(
                QueryVariantExecution.query_variant_id,
                func.count(QueryVariantExecution.id).label("exec_count"),
                func.coalesce(
                    func.sum(QueryVariantExecution.channels_found), 0
                ).label("sum_found"),
                func.coalesce(
                    func.sum(QueryVariantExecution.channels_added), 0
                ).label("sum_added"),
            )
            .where(QueryVariantExecution.query_variant_id.in_(variant_ids))
            .group_by(QueryVariantExecution.query_variant_id)
        )
        for row in agg_result:
            v_id = row.query_variant_id
            exec_counts[v_id] = row.exec_count
            total_executions += row.sum_found
            total_channels_added += row.sum_added

    variant_summaries = [
        {
            "variant_text": v.variant_text,
            "variant_type": v.variant_type,
            "executions": exec_counts.get(v.id, 0),
        }
        for v in variants
    ]

    sp = await get_seed_profile_by_id(db, profile_id)
    alert_count = sp.alert_count if sp else 0
    fp_count = sp.reviewed_fp_count if sp else 0
    rev_total = sp.reviewed_total_count if sp else 0
    fp_rate = round(fp_count / rev_total, 3) if rev_total > 0 else None

    return {
        "seed_profile_id": profile_id,
        "total_variants": total_variants,
        "total_executions": total_executions,
        "total_channels_added": total_channels_added,
        "alert_count": alert_count,
        "reviewed_fp_count": fp_count,
        "reviewed_total_count": rev_total,
        "reviewed_fp_rate": fp_rate,
        "variants": variant_summaries,
    }


# ---------------------------------------------------------------------------
# get_active_variants — scanner integration
# ---------------------------------------------------------------------------

async def get_active_variants(
    db: AsyncSession,
    profile: Optional[str] = "illegal_trade",
) -> List[Tuple[QueryVariant, SeedProfile]]:
    """
    Return all (QueryVariant, SeedProfile) pairs where the parent SeedProfile
    is active and matches the requested profile (default: 'illegal_trade').
    """
    q = (
        select(QueryVariant, SeedProfile)
        .join(SeedProfile, QueryVariant.seed_profile_id == SeedProfile.id)
        .where(SeedProfile.is_active == True)  # noqa: E712
    )
    if profile is not None:
        q = q.where(SeedProfile.profile == profile)
    result = await db.execute(q)
    return list(result.all())
