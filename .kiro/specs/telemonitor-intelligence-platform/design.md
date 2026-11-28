# Design Document — TeleMonitor Intelligence Platform

## Overview

This document specifies the technical design for upgrading the TeleMonitor OSINT dashboard across nine tightly coupled areas: structured seed management, pivot candidate queuing, message-level scan evidence persistence, composite channel scoring, a reusable text/OCR normalisation pipeline, an analyst feedback loop, expanded APIs and UI panels, operational reliability improvements, and automated testing.

The upgrade must leave every existing API route, database table, and UI page fully functional. All new capabilities operate exclusively on public Telegram channels.

**Key design principles:**
- Existing tables are extended with new columns via the existing `_migrate_sqlite_columns()` idempotent pattern; no existing columns are dropped or renamed.
- All new logic is introduced in new modules or clearly delimited new functions in existing modules.
- The normaliser is a pure function with no database dependency.
- Composite scoring is computed at scan-time and stored for auditability; it does not replace `avg_score` for existing clients.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Frontend (React 18 + TypeScript + Vite)                        │
│  New pages: SeedPerformancePage, PivotQueuePage                 │
│  Modified: ScanPage (evidence tab), AlertsPage (dispositions),  │
│            ChannelDetailModal (score breakdown tab)             │
└────────────────────────┬────────────────────────────────────────┘
                         │ HTTP / REST
┌────────────────────────▼────────────────────────────────────────┐
│  FastAPI (app/main.py)                                          │
│  New routers: seeds, pivots, scan.evidence, dispositions        │
│  Modified routers: scan (evidence sub-routes), channels (health)│
└──┬──────────┬──────────┬──────────┬──────────┬─────────────────┘
   │          │          │          │          │
┌──▼──┐  ┌───▼───┐  ┌───▼───┐  ┌───▼────┐  ┌──▼──────────────┐
│Seeds│  │Pivots │  │Scan   │  │Dispos- │  │Channels + Health│
│API  │  │API    │  │Evid.  │  │itions  │  │API              │
└──┬──┘  └───┬───┘  └───┬───┘  └───┬────┘  └──┬──────────────┘
   │          │          │          │           │
┌──▼──────────▼──────────▼──────────▼───────────▼──────────────┐
│  Service / Business Logic Layer                               │
│  app/services/seed_service.py     — variant generation, dedup │
│  app/services/pivot_service.py    — eligibility, dedup        │
│  app/services/scoring_service.py  — composite score formula   │
│  app/services/feedback_service.py — metrics aggregation       │
└──┬────────────────────────────────────────────────────────────┘
   │
┌──▼─────────────────────────────────────────────────────────────┐
│  Extractors / Classifiers                                      │
│  app/extractors/normaliser.py  (NEW — pure function)           │
│  app/classifiers/classifier.py (MODIFIED — use normaliser)     │
│  app/extractors/identifier_extractor.py (unchanged)            │
│  app/extractors/ocr.py (unchanged)                             │
└──┬─────────────────────────────────────────────────────────────┘
   │
┌──▼─────────────────────────────────────────────────────────────┐
│  Collectors                                                    │
│  app/collectors/scanner.py         (MODIFIED — evidence, pivots│
│                                     scoring, seed profiles)    │
│  app/collectors/telegram_collector.py (MODIFIED — polling tiers│
│                                        OCR gating, FloodWait)  │
│  app/collectors/channel_discovery.py (MODIFIED — seed profiles)│
└──┬─────────────────────────────────────────────────────────────┘
   │
┌──▼─────────────────────────────────────────────────────────────┐
│  Database Layer (SQLAlchemy 2.x async + aiosqlite)             │
│  app/db/models.py     (MODIFIED — new ORM models + columns)    │
│  app/db/crud.py       (MODIFIED — new CRUD helpers)            │
│  app/db/database.py   (MODIFIED — extended migration)          │
└────────────────────────────────────────────────────────────────┘
```

---

## Components and Interfaces

### New Python Modules

| Path | Purpose |
|---|---|
| `app/extractors/normaliser.py` | Standalone 7-step text normalisation pipeline |
| `app/services/seed_service.py` | Seed profile CRUD, variant generation, dedup |
| `app/services/pivot_service.py` | Pivot candidate eligibility, extraction, dedup |
| `app/services/scoring_service.py` | Composite score computation and storage |
| `app/services/feedback_service.py` | Disposition recording, feedback metrics aggregation |
| `app/api/seeds.py` | REST router for `/seeds/` prefix |
| `app/api/pivots.py` | REST router for `/pivots/` prefix |
| `app/api/evidence.py` | REST router for `/scan/evidence/` |
| `app/api/dispositions.py` | REST router for `/dispositions/` |

### Modified Python Modules

| Path | Changes |
|---|---|
| `app/db/models.py` | 9 new ORM models; new columns on Channel, ChannelScanResult, Alert |
| `app/db/crud.py` | New CRUD helpers for all new tables |
| `app/db/database.py` | Extended `_migrate_sqlite_columns()` |
| `app/classifiers/classifier.py` | Replace inline `normalise_text()` with import from normaliser |
| `app/collectors/scanner.py` | Seed profile integration, evidence writing, pivot extraction, scoring |
| `app/collectors/telegram_collector.py` | Poll tier scheduling, FloodWait tracking, OCR gating |
| `app/collectors/channel_discovery.py` | Use SeedProfile/QueryVariant instead of flat seed list |
| `app/main.py` | Register new routers |
| `app/core/config.py` | New settings fields |

### New Frontend Files

| Path | Purpose |
|---|---|
| `frontend/src/pages/SeedPerformancePage.tsx` | Seed profile table + inline edit + create form |
| `frontend/src/pages/PivotQueuePage.tsx` | Pivot candidate list + promote/reject actions |
| `frontend/src/components/ScanEvidencePanel.tsx` | Evidence tab within scan results |
| `frontend/src/components/ScoreBreakdownPanel.tsx` | Composite score bar chart |
| `frontend/src/components/DispositionControls.tsx` | Reusable disposition button group |
| `frontend/src/api/seeds.ts` | Typed API calls for `/seeds/` |
| `frontend/src/api/pivots.ts` | Typed API calls for `/pivots/` |
| `frontend/src/api/evidence.ts` | Typed API calls for `/scan/evidence/` |

### Modified Frontend Files

| Path | Changes |
|---|---|
| `frontend/src/App.tsx` | Add nav entries for Seed Performance and Pivot Queue |
| `frontend/src/pages/ScanPage.tsx` | Add Evidence sub-panel per channel result |
| `frontend/src/pages/AlertsPage.tsx` | Add DispositionControls + disposition filter |
| `frontend/src/components/ChannelDetailModal.tsx` | Add Score Breakdown tab |
| `frontend/src/api/client.ts` | Add new type interfaces and API calls |

---

## Data Models

### New Tables

#### `seed_profiles` — SQLAlchemy model: `SeedProfile`

| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK, autoincrement |
| seed_text | String(120) | NOT NULL |
| seed_text_normalised | String(120) | NOT NULL, UNIQUE |
| threat_category | String(64) | NOT NULL |
| language_region | String(16) | NOT NULL, default "en" |
| intent_type | String(64) | NOT NULL |
| priority | Integer | NOT NULL, CHECK 1–5, default 3 |
| is_active | Boolean | NOT NULL, default True |
| created_source | String(32) | NOT NULL — one of: manual, analyst_promoted, entity_pivot |
| created_at | DateTime | NOT NULL, server_default now() |
| updated_at | DateTime | NOT NULL, server_default now(), onupdate now() |

Indexes: `ix_seed_profiles_is_active (is_active)`

#### `query_variants` — SQLAlchemy model: `QueryVariant`

| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK, autoincrement |
| seed_profile_id | Integer | FK → seed_profiles.id, NOT NULL |
| variant_text | String(120) | NOT NULL |
| variant_type | String(32) | NOT NULL — spacing, hyphen, transliteration_to_latin, transliteration_to_devanagari |
| is_canonical | Boolean | NOT NULL, default False |
| created_at | DateTime | NOT NULL, server_default now() |

Constraints: UniqueConstraint(`variant_text`) across the entire table (global dedup).  
Indexes: `ix_query_variants_seed_profile_id (seed_profile_id)`

#### `query_variant_executions` — SQLAlchemy model: `QueryVariantExecution`

| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK, autoincrement |
| query_variant_id | Integer | FK → query_variants.id, NOT NULL |
| scan_job_id | Integer | FK → scan_jobs.id, nullable |
| execution_timestamp | DateTime | NOT NULL, server_default now() |
| channels_found | Integer | NOT NULL, default 0 |
| channels_added | Integer | NOT NULL, default 0 |

Indexes: `ix_qve_variant_id (query_variant_id)`, `ix_qve_scan_job_id (scan_job_id)`

#### `scan_evidence` — SQLAlchemy model: `ScanEvidence`

| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK, autoincrement |
| scan_job_id | Integer | FK → scan_jobs.id, NOT NULL |
| channel_scan_result_id | Integer | FK → channel_scan_results.id, nullable |
| channel_username | String(255) | NOT NULL |
| telegram_message_id | BigInteger | NOT NULL |
| message_timestamp | DateTime | nullable |
| raw_text | Text | nullable |
| caption_text | Text | nullable |
| ocr_text | Text | nullable |
| normalised_text | Text | nullable |
| classifier_score | Float | NOT NULL |
| risk_level | String(16) | NOT NULL |
| severity_tier | String(16) | NOT NULL |
| categories | Text | nullable — JSON array |
| matched_terms | Text | nullable — JSON array |
| extracted_identifiers | Text | nullable — JSON array |
| seed_term | String(255) | nullable |
| query_variant_id | Integer | FK → query_variants.id, nullable |
| media_path | Text | nullable |
| media_hash | String(64) | nullable |
| ocr_success | Boolean | nullable |
| ocr_confidence | Float | nullable |
| ocr_skip_reason | String(32) | nullable — not_image, low_risk_channel, no_text_signal |
| last_classified_at | DateTime | NOT NULL, server_default now() |
| disposition | String(32) | nullable |
| disposition_notes | Text | nullable |
| disposition_by | String(128) | nullable |
| disposition_at | DateTime | nullable |

Constraints: UniqueConstraint(`channel_username`, `telegram_message_id`)  
Indexes: `ix_scan_evidence_scan_job_id`, `ix_scan_evidence_channel_username`, `ix_scan_evidence_risk_level`, `ix_scan_evidence_last_classified_at`, `ix_scan_evidence_disposition`

#### `pivot_candidates` — SQLAlchemy model: `PivotCandidate`

| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK, autoincrement |
| source_channel_username | String(255) | NOT NULL |
| source_scan_result_id | Integer | FK → channel_scan_results.id, nullable |
| candidate_type | String(32) | NOT NULL — channel_link, handle, payment_identifier, forwarded_source |
| candidate_value | String(512) | NOT NULL |
| status | String(32) | NOT NULL, default pending — pending, evaluated, promoted, rejected, inaccessible, already_monitored |
| created_at | DateTime | NOT NULL, server_default now() |
| evaluated_at | DateTime | nullable |
| evaluated_by | String(128) | nullable |
| notes | Text | nullable |

Constraints: UniqueConstraint(`candidate_value`, `source_channel_username`)  
Indexes: `ix_pivot_candidates_status (status)`, `ix_pivot_candidates_source_channel (source_channel_username)`

#### `channel_score_components` — SQLAlchemy model: `ChannelScoreComponents`

| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK, autoincrement |
| channel_scan_result_id | Integer | FK → channel_scan_results.id, NOT NULL, UNIQUE |
| composite_score | Float | NOT NULL |
| max_message_score | Float | NOT NULL |
| high_confidence_message_count | Integer | NOT NULL |
| distinct_incident_count | Integer | NOT NULL |
| recency_weight | Float | NOT NULL |
| identifier_density | Float | NOT NULL |
| valid_pivot_count | Integer | NOT NULL |
| analyst_confirmation_signal | Float | NOT NULL, default 0.0 |
| scored_at | DateTime | NOT NULL, server_default now() |

Indexes: `ix_channel_score_components_result_id (channel_scan_result_id)`

#### `channel_health_events` — SQLAlchemy model: `ChannelHealthEvent`

| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK, autoincrement |
| channel_id | Integer | FK → channels.id, NOT NULL |
| event_type | String(32) | NOT NULL — flood_wait, private_error, username_invalid, collection_error, inaccessible |
| error_message | Text | nullable |
| occurred_at | DateTime | NOT NULL, server_default now() |

Indexes: `ix_channel_health_channel_id_occurred_at (channel_id, occurred_at)`

#### `disposition_history` — SQLAlchemy model: `DispositionHistory`

| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK, autoincrement |
| target_type | String(32) | NOT NULL — alert, scan_evidence, pivot_candidate |
| target_id | Integer | NOT NULL |
| previous_disposition | String(32) | nullable |
| new_disposition | String(32) | NOT NULL |
| changed_by | String(128) | NOT NULL |
| changed_at | DateTime | NOT NULL, server_default now() |
| notes | Text | nullable |

Indexes: `ix_disposition_history_target (target_type, target_id)`

### Modified Existing Tables

#### `channels` — new columns

| Column | Type | Default | Purpose |
|---|---|---|---|
| poll_tier | String(16) | "LOW" | HIGH / MEDIUM / LOW |
| last_poll_attempted_at | DateTime | null | Timestamp of last poll attempt |
| consecutive_error_count | Integer | 0 | Resets on success |
| error_state | Boolean | False | True when 3+ consecutive errors in 24h |
| channel_status | String(16) | "active" | active / paused / inaccessible / error |
| discovery_variant_id | Integer (FK nullable) | null | FK → query_variants.id |

#### `channel_scan_results` — new columns

| Column | Type | Default | Purpose |
|---|---|---|---|
| discovered_by_variant_id | Integer (FK nullable) | null | FK → query_variants.id |
| composite_score | Float | null | Filled after scoring |

#### `alerts` — new columns

| Column | Type | Default | Purpose |
|---|---|---|---|
| disposition | String(32) | null | confirmed / benign / uncertain / duplicate / inaccessible |
| disposition_notes | Text | null | |
| disposition_by | String(128) | null | |
| disposition_at | DateTime | null | |

---

## Normaliser Module Design

**File:** `app/extractors/normaliser.py`

### Public Interface

```python
def normalise(text: str, transliteration_hook=None) -> str:
    """
    Apply the 7-step normalisation pipeline to text.

    Parameters
    ----------
    text : str
        Raw input string. Never mutated.
    transliteration_hook : callable[[str], str] | None
        Optional function applied after step 4 (lowercase).
        Receives the lowercased string, returns a string.

    Returns
    -------
    str
        Normalised output. The original text is not modified.
    """
```

### 7-Step Pipeline

```
Step 1 — Unicode NFC normalisation
    unicodedata.normalize("NFC", text)
    Converts decomposed characters (e.g. "a" + combining accent) to
    precomposed equivalents so subsequent string matching works correctly.

Step 2 — Zero-width and invisible character removal
    Remove codepoints: U+200B ZERO WIDTH SPACE, U+200C ZWNJ, U+200D ZWJ,
    U+200E LRM, U+200F RLM, U+00AD SOFT HYPHEN, U+2060 WORD JOINER,
    U+FEFF BOM/ZWNBSP.
    Pattern: re.compile(r"[\u200b-\u200f\u00ad\u2060\ufeff]")

Step 3 — Look-alike character replacement
    Apply the CONFUSABLE_MAP (see below) using str.translate() with a
    precomputed translation table (computed once at module load).
    Covers Cyrillic, Greek, and mathematical alphanumerics.

Step 4 — Lowercase conversion
    text.lower()
    Applied AFTER look-alike replacement so both upper and lower Cyrillic
    lookalikes are caught.

    [transliteration_hook applied here if provided]

Step 5 — Repeated-punctuation compression
    re.sub(r"([!?.,:;@#$%^&*\-_=+|~`])\1{2,}", r"\1\1", text)
    Three or more consecutive identical punctuation characters collapsed to two.
    Two are kept (not one) to preserve intentional emphasis markers.

Step 6 — Repeated-whitespace normalisation
    re.sub(r"\s+", " ", text).strip()
    Any run of whitespace (space, tab, newline, NBSP) collapsed to one space.

Step 7 — Hyphen/space interchange normalisation
    text.replace("-", " ")
    Treats "drug-sale" and "drug sale" as equivalent at the token level.
    Applied last so the hyphen→space doesn't interfere with punctuation compression.
```

### Look-alike Character Map (CONFUSABLE_MAP)

Minimum 24 entries covering the most common Cyrillic and Greek substitution attacks seen in Telegram criminal channels:

```python
CONFUSABLE_MAP = {
    # Cyrillic → ASCII
    "а": "a",  "е": "e",  "о": "o",  "р": "p",  "с": "c",
    "х": "x",  "у": "y",  "В": "B",  "Н": "H",  "К": "K",
    "М": "M",  "Т": "T",  "А": "A",  "Е": "E",  "О": "O",
    "Р": "P",  "С": "C",  "Х": "X",
    # Greek → ASCII
    "α": "a",  "ο": "o",  "ρ": "p",  "ν": "v",  "ε": "e",
    "Α": "A",  "Β": "B",  "Ε": "E",  "Ζ": "Z",  "Η": "H",
    "Ι": "I",  "Κ": "K",  "Μ": "M",  "Ν": "N",  "Ο": "O",
    "Ρ": "P",  "Τ": "T",  "Υ": "Y",  "Χ": "X",
    # Mathematical bold/italic ASCII lookalikes (U+1D400–U+1D7FF range)
    # handled via unicodedata NFC + explicit spot replacements for common ones
    "\u0430": "a", "\u0435": "e", "\u043e": "o",
}
_TRANS_TABLE = str.maketrans(CONFUSABLE_MAP)
```

### Integration with Classifier

```python
# classifier.py — BEFORE (remove inline normalise_text())
# classifier.py — AFTER
from app.extractors.normaliser import normalise as _normalise_text

def classify(text: str) -> ClassificationResult:
    if not text or not text.strip():
        return ClassificationResult(0.0, "LOW", "LOW", False, [], [], None)
    norm = _normalise_text(text)   # was: norm = normalise_text(text)
    store = get_lexicon_store()
    lex_s, matched_terms, categories, severity = lexicon_score(norm, store)
    ...
```

The existing `normalise_text()` function in `classifier.py` is kept as a thin wrapper calling `normalise()` for one release cycle, then removed in a follow-up.

### Integration with Scanner and Collector

In `scanner.py` → `_scan_one_channel()`: call `normalise(text)` before passing to `classify()` and store the normalised result in `ScanEvidence.normalised_text`.

In `telegram_collector.py` → `_process_message()`: call `normalise(combined)` before `classify(combined)`.

---

## Seed Profile and Variant Engine Design

### ORM Models

```python
class SeedProfile(Base):
    __tablename__ = "seed_profiles"
    id, seed_text, seed_text_normalised, threat_category, language_region,
    intent_type, priority, is_active, created_source, created_at, updated_at
    # relationship: variants -> List[QueryVariant]

class QueryVariant(Base):
    __tablename__ = "query_variants"
    id, seed_profile_id, variant_text, variant_type, is_canonical, created_at
    # relationship: profile -> SeedProfile
```

### `generate_variants()` in `app/services/seed_service.py`

```python
def generate_variants(seed_text: str, language_region: str) -> List[str]:
    """
    Returns a deduplicated list of search query variants derived from seed_text.
    All returned variants have at most 2 whitespace-separated tokens.
    """
```

**Algorithm:**

```
1. Normalise the seed text (call normalise() without transliteration hook).
2. Spacing variants:
   tokens = normalised.split()
   For each adjacent pair of tokens: produce "token_i token_{i+1}" (2-token slice).
   If len(tokens) == 1: use the single token as-is.
3. Hyphen variants:
   hyphenated = "-".join(tokens[:2])  — joins first two tokens with a hyphen.
4. Transliteration variants (only when language_region == "hi-IN"):
   Use indic_transliteration.sanscript.transliterate():
     a. If seed is Latin: produce ITRANS → DEVANAGARI variant.
     b. If seed is Devanagari: produce DEVANAGARI → ITRANS (Latin) variant.
     Both are then sliced to two tokens.
5. Enforce two-token max:
   Filter: [v for v in candidates if len(v.split()) <= 2 and v.strip()]
6. Deduplicate within this generation (preserving order).
7. Return list (minimum 3 entries guaranteed by steps 2+3+4 or 2+3+fallback).
```

**Fallback when seed is a single token:** Step 3 produces the same string (no-op), so a third variant is generated by appending the most common contextual suffix for that seed's `threat_category` ("sale", "buy", or "order") — this ensures the three-class minimum from requirement 1.4.

### Two-Token Max Enforcement

```python
def _enforce_two_tokens(variant: str) -> bool:
    return len(variant.strip().split()) <= 2
```

Any variant failing this check is silently dropped before returning from `generate_variants()`. The API returns HTTP 422 if a caller-supplied custom variant text would exceed this limit (requirement 8.6).

### Global Dedup Strategy

Before writing any `QueryVariant` row, `seed_service.py` checks:

```python
existing = await db.execute(
    select(QueryVariant).where(QueryVariant.variant_text == candidate_text)
)
row = existing.scalar_one_or_none()
if row:
    # Record a reference to existing row; do not insert duplicate.
    return row.id
else:
    # Insert new row.
```

The UniqueConstraint on `variant_text` acts as a database-level guard.

### Scanner Integration

`scanner.py` replaces its `DEFAULT_SEEDS` list iteration with:

```python
async def _get_active_variants(db) -> List[Tuple[QueryVariant, SeedProfile]]:
    result = await db.execute(
        select(QueryVariant, SeedProfile)
        .join(SeedProfile, QueryVariant.seed_profile_id == SeedProfile.id)
        .where(SeedProfile.is_active == True)
    )
    return result.all()
```

Each `(variant, profile)` pair is used in `_search_channels(client, variant.variant_text)`. The resulting `ChannelScanResult` row gets `discovered_by_variant_id = variant.id`.

---

## Composite Scoring Design

### Formula

```
Composite_Score =
    0.30 * max_message_score
  + 0.20 * normalise_count(high_confidence_message_count, cap=10)
  + 0.15 * normalise_count(distinct_incident_count, cap=5)
  + 0.10 * recency_weight                      (already in [0.0, 1.0])
  + 0.10 * identifier_density                   (already in [0.0, 1.0])
  + 0.10 * normalise_count(valid_pivot_count, cap=5)
  + 0.05 * analyst_confirmation_signal_normalised

where normalise_count(x, cap) = min(x, cap) / cap
and analyst_confirmation_signal_normalised = (signal + 1.0) / 2.0
  maps {-1.0, 0.0, +1.0} → {0.0, 0.5, 1.0}
```

Weights sum to 1.0. All inputs are individually clamped to [0.0, 1.0] before the weighted sum. Result is therefore always in [0.0, 1.0].

### Saturation Caps (configurable in `Settings`)

```python
COMPOSITE_HIGH_MSG_CAP: int = 10       # high_confidence_message_count saturation
COMPOSITE_INCIDENT_CAP: int = 5        # distinct_incident_count saturation
COMPOSITE_PIVOT_CAP: int = 5           # valid_pivot_count saturation
```

### Component Computation

**Location:** `app/services/scoring_service.py`, called from `scanner.py` → `_scan_one_channel()` immediately after messages are processed.

```python
async def compute_and_store_composite_score(
    db: AsyncSession,
    scan_result_id: int,
    channel_username: str,
    scan_job_id: int,
    high_count: int,
    all_scores: List[float],
    categories_per_message: List[List[str]],
    most_recent_high_risk_ts: Optional[datetime],
    scan_window_end: datetime,
    identifier_counts: Dict[str, int],
    total_messages: int,
    pivot_count: int,
) -> ChannelScoreComponents:
```

**recency_weight computation:**

```
if most_recent_high_risk_ts is None:
    recency_weight = 0.0
else:
    age_hours = (scan_window_end - most_recent_high_risk_ts).total_seconds() / 3600
    recency_weight = max(0.0, 1.0 - (age_hours / 72.0))   # decays to 0 after 72h
```

**identifier_density:**

```
messages_with_identifier = count of messages where extracted_identifiers is non-empty
identifier_density = messages_with_identifier / total_messages  if total_messages > 0 else 0.0
```

**analyst_confirmation_signal:**

```
confirmed = count of ScanEvidence rows for this channel where disposition == "confirmed"
benign    = count of ScanEvidence rows for this channel where disposition == "benign"
if confirmed > 0:
    signal = +1.0
elif benign > 0 and confirmed == 0:
    signal = -1.0
else:
    signal = 0.0
```

### Anti-Spam Guard (Requirement 5.4)

After computing the weighted Composite_Score, the risk_level assignment applies an additional guard:

```python
def classify_composite_risk(score: float, high_confidence_count: int) -> str:
    if score >= HIGH_RISK_THRESHOLD:
        if high_confidence_count == 0:
            return "MEDIUM"   # anti-spam guard: cannot be HIGH with no high-confidence messages
        return "HIGH"
    elif score >= MEDIUM_RISK_THRESHOLD:
        return "MEDIUM"
    return "LOW"
```

### Storage

After `compute_and_store_composite_score()` returns, the ChannelScanResult row is updated:

```python
scan_result.composite_score = components.composite_score
# avg_score remains unchanged for backward compatibility
```

The `channel_score_components` row is inserted with all seven component values and a `scored_at` timestamp.

---

## Pivot Candidate Extraction Design

### Eligibility Rules

A candidate string is eligible if and only if all of the following are true:

1. For `channel_link` / `handle` types: matches `^https?://t\.me/([a-zA-Z0-9_]{5,32})$` or `^@([a-zA-Z0-9_]{5,32})$`.
2. Does NOT match `t.me/joinchat/`, `t.me/+`, or any invite hash pattern.
3. The resolved username is not identical to the source channel username (no self-reference).
4. The URL scheme is `https://t.me/{username}` only — no other domains.

### Extraction Patterns

```python
# In app/services/pivot_service.py

_TME_CHANNEL_RE = re.compile(
    r"https?://t\.me/([a-zA-Z0-9_]{5,32})(?:[/?]|$)", re.IGNORECASE
)
_HANDLE_RE = re.compile(r"@([a-zA-Z0-9_]{5,32})")
_INVITE_RE = re.compile(r"t\.me/(?:joinchat|\+)", re.IGNORECASE)

def extract_pivot_candidates(
    text: str,
    source_channel: str,
    fwd_source: Optional[str],
    identifiers: List[ExtractedIdentifier],
    identifier_frequency: Dict[str, int],  # value → count across messages in same scan session
) -> List[RawPivotCandidate]:
```

**Forwarded source:** If `msg.fwd_from` resolves to a named public channel, that channel name is added as a `forwarded_source` pivot.

**Payment identifier pivots:** A phone/UPI/wallet identifier is eligible as a `payment_identifier` pivot only if its `normalised` value appears in `identifier_frequency` with count >= 2 (recurring across two or more distinct messages in the same scan job for this channel).

### Dedup Logic

Before inserting a `PivotCandidate` row:

```python
existing = await db.execute(
    select(PivotCandidate).where(
        PivotCandidate.candidate_value == candidate_value,
        PivotCandidate.source_channel_username == source_channel,
    )
)
if existing.scalar_one_or_none():
    return  # already recorded — dedup by (value, source_channel)
```

If the candidate value matches a username already in the `channels` table (watchlist), status is set to `already_monitored` immediately on insert.

### Status State Machine

```
                    ┌─────────┐
                    │ pending │ ← default on creation
                    └────┬────┘
           ┌─────────────┼─────────────┬─────────────┐
           ▼             ▼             ▼             ▼
       ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐
       │ promoted │ │ rejected │ │inaccessible│ │already_monitored│
       └──────────┘ └──────────┘ └──────────┘ └───────────────┘
           │
           ▼
     Channel upserted
     into watchlist
     (is_active=True)
```

`evaluated` is an intermediate state set when an analyst opens the detail view but has not yet taken action. Transitions from `evaluated` follow the same arrows as from `pending`.

---

## Scan Evidence Persistence Design

### Insert-or-Update Logic

```python
async def upsert_scan_evidence(
    db: AsyncSession,
    channel_username: str,
    telegram_message_id: int,
    evidence_data: dict,
) -> ScanEvidence:
    existing = await db.execute(
        select(ScanEvidence).where(
            ScanEvidence.channel_username == channel_username,
            ScanEvidence.telegram_message_id == telegram_message_id,
        )
    )
    row = existing.scalar_one_or_none()
    if row:
        # Update classification fields; preserve raw text fields
        row.last_classified_at = datetime.utcnow()
        row.classifier_score = evidence_data["classifier_score"]
        row.risk_level = evidence_data["risk_level"]
        row.severity_tier = evidence_data["severity_tier"]
        row.categories = evidence_data["categories"]
        row.matched_terms = evidence_data["matched_terms"]
        # raw_text, caption_text, ocr_text NOT overwritten
        return row
    else:
        new_row = ScanEvidence(**evidence_data)
        db.add(new_row)
        return new_row
```

### Separate Text Storage

Three text fields are stored independently and never merged in the evidence table:

| Field | Source |
|---|---|
| `raw_text` | `tg_msg.message` (message body text) |
| `caption_text` | `tg_msg.message` when it accompanies a media object (caption) |
| `ocr_text` | Raw EasyOCR output before normalisation |
| `normalised_text` | `normalise(raw_text + " " + caption_text + " " + ocr_text)` |

The classifier is called on `normalised_text` only. Raw fields are for forensic review and re-classification.

### Re-classification Endpoint

`POST /scan/evidence/reclassify`

```python
class ReclassifyRequest(BaseModel):
    cutoff: datetime           # re-classify rows with last_classified_at < cutoff
    scan_job_id: Optional[int] # optional scope filter
    limit: int = 500           # max rows per call
```

Implementation: batch-reads `ScanEvidence` rows matching the filter, calls `classify(row.normalised_text)`, updates `classifier_score`, `risk_level`, `severity_tier`, `categories`, `matched_terms`, `last_classified_at`. Commits in batches of 100. Returns `{"updated": N}`.

### Relationship to ChannelScanResult

`ScanEvidence.channel_scan_result_id` is a nullable FK. It is set when the evidence row is created during a scan job. For evidence created during Collector polling (not scan jobs), it is null.

The `GET /scan/jobs/{job_id}` response includes evidence counts:

```json
{
  "id": 1,
  "...",
  "evidence_counts": {
    "total": 42,
    "HIGH": 8,
    "MEDIUM": 34,
    "by_category": {"drug_sale": 20, "hawala_money_laundering": 14}
  }
}
```

---

## Analyst Feedback and Disposition Design

### Disposition Enum

```python
class Disposition(str, Enum):
    confirmed    = "confirmed"
    benign       = "benign"
    uncertain    = "uncertain"
    duplicate    = "duplicate"
    inaccessible = "inaccessible"
```

### Tables with Disposition Columns

- `alerts`: `disposition`, `disposition_notes`, `disposition_by`, `disposition_at`
- `scan_evidence`: same four columns (already in `scan_evidence` table above)
- `pivot_candidates`: uses `status` and `notes` (semantically equivalent; mapped via `DispositionControls`)

### Disposition Submission Flow

```
PATCH /dispositions/  (batch)  or  PATCH /alerts/{id}/disposition
                                   PATCH /scan/evidence/{id}/disposition
                                   PATCH /pivots/{id}

1. Validate disposition value → HTTP 400 if unrecognised.
2. Read current disposition from target row.
3. Write DispositionHistory entry with (previous_value, new_value, changed_by, changed_at).
4. Write new disposition fields to target row.
5. If target is PivotCandidate and disposition == confirmed → trigger pivot promotion.
6. Return updated row.
```

### Feedback Metrics Computation

Computed on-the-fly by `GET /seeds/profiles/{id}/metrics` (not pre-aggregated):

```sql
SELECT
  COUNT(*) AS candidates_found,
  SUM(CASE WHEN se.risk_level IN ('HIGH','MEDIUM') THEN 1 ELSE 0 END) AS messages_processed,
  SUM(CASE WHEN a.id IS NOT NULL THEN 1 ELSE 0 END) AS alerts_raised,
  SUM(CASE WHEN se.disposition = 'confirmed' THEN 1 ELSE 0 END) AS confirmed_count,
  SUM(CASE WHEN se.disposition = 'benign' THEN 1 ELSE 0 END) AS false_positive_count
FROM scan_evidence se
JOIN query_variants qv ON se.query_variant_id = qv.id
LEFT JOIN alerts a ON ...  -- linked via message path
WHERE qv.seed_profile_id = :profile_id
```

Python then computes:

```python
precision = confirmed / (confirmed + false_positive) if (confirmed + false_positive) > 0 else 0.0
yield_val = confirmed / candidates_found if candidates_found > 0 else 0.0
```

---

## Adaptive Polling Design

### Three-Tier Scheduler

```python
POLL_TIERS = {
    "HIGH":   30,    # seconds
    "MEDIUM": 60,
    "LOW":    300,   # or settings.POLL_INTERVAL_SECONDS if larger
}
```

### Tier Assignment

```python
def assign_poll_tier(channel: Channel) -> str:
    if not channel.is_active or channel.channel_status != "active":
        return "LOW"
    # Use composite_score risk if available via most recent ChannelScanResult
    if channel.risk_level == "HIGH":
        return "HIGH"
    elif channel.risk_level == "MEDIUM":
        return "MEDIUM"
    return "LOW"
```

`channel.risk_level` is populated from the most recent `ChannelScanResult.risk_level` or `ChannelScanResult.composite_score`-derived level if available.

### Changes to `TelegramCollector.run_forever()`

The existing single-interval loop is replaced with a tier-aware scheduler:

```python
async def run_forever(self) -> None:
    self._running = True
    await self.start()
    while self._running:
        async with get_session() as db:
            channels = await get_active_channels(db)
        now = datetime.utcnow()
        due_channels = []
        for ch in channels:
            tier = assign_poll_tier(ch)
            interval = POLL_TIERS[tier]
            last = ch.last_poll_attempted_at or datetime.min
            if (now - last).total_seconds() >= interval:
                due_channels.append(ch)
        for ch in due_channels:
            await self._collect_channel_safe(ch)
        await asyncio.sleep(10)   # tight loop, actual gating is per-channel
```

`_collect_channel_safe()` wraps `_collect_channel()` with:
1. `last_poll_attempted_at` update before the poll attempt.
2. `poll_tier` update on the channel record.
3. FloodWait handling (see below).

### FloodWait Handling

```python
async def _collect_channel_safe(self, ch: Channel) -> None:
    try:
        await self._collect_channel(ch)
        await _reset_error_state(ch)
    except FloodWaitError as fwe:
        wait = max(fwe.seconds, settings.MIN_BACKOFF) * (settings.BACKOFF_MULTIPLIER ** ch.consecutive_error_count)
        await _record_health_event(ch, "flood_wait", str(fwe))
        await asyncio.sleep(wait)
    except (ChannelPrivateError, UsernameInvalidError, UsernameNotOccupiedError) as exc:
        await _record_health_event(ch, "inaccessible", str(exc))
        await _set_channel_inaccessible(ch)
    except Exception as exc:
        await _record_health_event(ch, "collection_error", str(exc))
        await _maybe_set_error_state(ch)
```

New `Settings` fields:
```
MIN_BACKOFF: int = 10          # seconds minimum backoff
BACKOFF_MULTIPLIER: float = 2.0
MAX_RETRY_COUNT: int = 5
ERROR_STATE_WINDOW_HOURS: int = 24
ERROR_STATE_THRESHOLD: int = 3  # consecutive errors to trigger error_state
```

---

## OCR Gating Design

### Gate Conditions

```python
def should_run_ocr(
    file_extension: str,
    mime_type: Optional[str],
    channel_poll_tier: str,
    message_has_lexicon_match: bool,
) -> Tuple[bool, Optional[str]]:
    """
    Returns (should_run: bool, skip_reason: Optional[str]).
    skip_reason is None when OCR will run, otherwise one of:
        'not_image', 'low_risk_channel', 'no_text_signal'
    """
    IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "bmp"}
    is_image = (
        file_extension.lower().lstrip(".") in IMAGE_EXTENSIONS
        or (mime_type or "").lower().startswith("image/")
    )
    if not is_image:
        return False, "not_image"

    high_tier = channel_poll_tier in ("HIGH", "MEDIUM")
    if not high_tier and not message_has_lexicon_match:
        if not high_tier:
            return False, "low_risk_channel"
        return False, "no_text_signal"

    return True, None
```

### Media Retention Logic

```python
after_ocr_classification_done:
    if risk_level == "HIGH":
        keep_media = True          # always retain HIGH evidence
    elif channel_poll_tier == "HIGH":
        keep_media = True          # retain for high-tier channels
    elif channel_poll_tier == "MEDIUM":
        keep_media = False         # delete after classification
    else:
        keep_media = False         # LOW tier: delete
    
    if not keep_media:
        Path(media_path).unlink(missing_ok=True)
        media_path = None
```

---

## API Design

### `/seeds/` — Seed Profile and Variant Management

| Method | Path | Body / Params | Response | Status |
|---|---|---|---|---|
| GET | `/seeds/profiles` | `skip`, `limit`, `is_active`, `threat_category` | List[SeedProfileResponse] | 200 |
| POST | `/seeds/profiles` | SeedProfileCreate | SeedProfileResponse | 201 |
| GET | `/seeds/profiles/{id}` | — | SeedProfileResponse + variants | 200, 404 |
| PATCH | `/seeds/profiles/{id}` | SeedProfileUpdate (priority, intent_type, threat_category, is_active) | SeedProfileResponse | 200, 404 |
| GET | `/seeds/profiles/{id}/provenance` | `skip`, `limit` | List[ProvenanceEntry] | 200, 404 |
| GET | `/seeds/profiles/{id}/metrics` | — | FeedbackMetrics | 200, 404 |
| GET | `/seeds/metrics` | — | List[FeedbackMetrics] sorted by precision desc | 200 |
| GET | `/seeds/variants` | `seed_profile_id`, `skip`, `limit` | List[QueryVariantResponse] | 200 |

Error responses: HTTP 400 for invalid `created_source`, HTTP 409 for duplicate normalised seed text, HTTP 422 for variant exceeding two tokens.

### `/pivots/` — Pivot Candidate Management

| Method | Path | Body / Params | Response | Status |
|---|---|---|---|---|
| GET | `/pivots/` | `status`, `candidate_type`, `source_channel_username`, `date_from`, `date_to`, `skip`, `limit` | List[PivotCandidateResponse] | 200 |
| GET | `/pivots/{id}` | — | PivotCandidateResponse | 200, 404 |
| PATCH | `/pivots/{id}` | PivotUpdate (status, notes, evaluated_by) | PivotCandidateResponse | 200, 404 |
| GET | `/channels/{username}/pivots` | `skip`, `limit` | List[PivotCandidateResponse] | 200 |

Promotion (status → promoted): returns HTTP 200 with existing Channel if already watchlisted; HTTP 201 with new Channel otherwise.

### `/scan/evidence/` — Scan Evidence

| Method | Path | Body / Params | Response | Status |
|---|---|---|---|---|
| GET | `/scan/jobs/{job_id}/evidence` | `risk_level`, `category`, `disposition`, `skip`, `limit` | List[ScanEvidenceResponse] | 200, 404 |
| GET | `/scan/evidence/{id}` | — | ScanEvidenceResponse | 200, 404 |
| GET | `/channels/{username}/evidence` | `risk_level`, `disposition`, `skip`, `limit` | List[ScanEvidenceResponse] | 200 |
| POST | `/scan/evidence/reclassify` | ReclassifyRequest | `{"updated": N}` | 200 |
| PATCH | `/scan/evidence/{id}/disposition` | DispositionUpdate | ScanEvidenceResponse | 200, 404 |

### `/dispositions/` — Batch Disposition

| Method | Path | Body | Response | Status |
|---|---|---|---|---|
| POST | `/dispositions/` | BatchDispositionRequest: `[{target_type, target_id, disposition, notes, reviewed_by}]` | `{"updated": N, "errors": [...]}` | 200 |

HTTP 400 for unrecognised disposition value.

### `/channels/` — New Channel Sub-Routes

| Method | Path | Body / Params | Response | Status |
|---|---|---|---|---|
| GET | `/channels/{id}/health` | — | ChannelHealthResponse | 200, 404 |

ChannelHealthResponse:
```json
{
  "last_successful_collection_at": "2024-01-15T12:00:00",
  "consecutive_error_count": 0,
  "error_state": false,
  "poll_tier": "HIGH",
  "channel_status": "active",
  "recent_events": [{...}, ...]   // last 5 ChannelHealthEvent records
}
```

### Modified Existing Routes

`GET /scan/jobs/{job_id}` — response extended with `evidence_counts` object (see Scan Evidence section).  
`GET /scan/results/{result_id}` — response extended with `score_breakdown` object containing all `ChannelScoreComponents` fields.

---

## Frontend Architecture

### Navigation Updates (`App.tsx`)

```typescript
import SeedPerformancePage from "./pages/SeedPerformancePage";
import PivotQueuePage from "./pages/PivotQueuePage";

const NAV = [
  ...existing entries...,
  { to: "/seeds", label: "Seed Performance", icon: Target },
  { to: "/pivots", label: "Pivot Queue", icon: GitMerge },
];

// New routes:
<Route path="/seeds" element={<SeedPerformancePage />} />
<Route path="/pivots" element={<PivotQueuePage />} />
```

### `SeedPerformancePage.tsx`

**State:** `profiles: SeedProfile[]`, `metrics: Record<number, FeedbackMetrics>`, `editingId: number | null`, `creating: boolean`

**Key API calls:**
- `GET /seeds/profiles` on mount
- `GET /seeds/metrics` on mount (merged into profile rows)
- `PATCH /seeds/profiles/{id}` on inline save
- `POST /seeds/profiles` on create form submit

**Component hierarchy:**
```
SeedPerformancePage
  └── SeedProfileTable
        ├── SeedProfileRow (×N)
        │     └── InlineEditForm (shown when editingId === row.id)
        └── CreateSeedForm (shown when creating === true)
```

Metrics in the table are refreshed (via `GET /seeds/profiles/{id}/metrics`) whenever a Disposition is submitted from any panel on the page (via a shared `onDispositionChange` callback prop).

### `PivotQueuePage.tsx`

**State:** `candidates: PivotCandidate[]`, `filters: PivotFilters`, `selectedId: number | null`

**Key API calls:**
- `GET /pivots/?status=pending` on mount and on filter change
- `PATCH /pivots/{id}` on promote/reject/mark-inaccessible
- Optimistic update: immediately set row status in local state before API response

**Component hierarchy:**
```
PivotQueuePage
  └── PivotCandidateList
        ├── PivotFilterBar
        └── PivotCandidateRow (×N)
              └── PivotDetailDrawer (expanded row)
                    ├── SampleMessagePreview (×3 max)
                    └── PivotActionButtons (Promote / Reject / Mark Inaccessible)
```

Toast notification on promote: "Channel @{username} added to watchlist."

### `ScanEvidencePanel.tsx`

Added as a new tab within `ScanPage.tsx` per `ChannelScanResult` row.

**Props:** `jobId: number, resultId: number, channelUsername: string`

**State:** `evidence: ScanEvidence[]`, `filters: EvidenceFilters`, `page: number`

**Key API calls:**
- `GET /scan/jobs/{jobId}/evidence?channel_username={username}&...` 
- `PATCH /scan/evidence/{id}/disposition` on disposition submission

Each evidence row renders:
- `telegram_message_id`, `message_timestamp`, `risk_level` badge
- `normalised_text` truncated to 400 chars with "Show more" toggle
- `classifier_score`, `categories` chips, `matched_terms`
- `extracted_identifiers` list
- OCR badge + collapsible `ocr_text` section (when `ocr_text` is non-null)
- `DispositionControls` component (confirmed / benign / uncertain / duplicate)

### `ScoreBreakdownPanel.tsx`

**Props:** `scoreBreakdown: ChannelScoreComponents`

Renders a horizontal bar chart (CSS flexbox, no chart library dependency) for each of the 7 components:

```
max_message_score         ████████░░  30% weight × 0.85 score = 25.5% contribution
high_confidence_count     ████░░░░░░  20% weight × 0.40 score = 8.0% contribution
...
analyst_confirmation_signal ██░░░░░░  5% weight × 0.50 signal = 2.5% contribution
```

When `analyst_confirmation_signal` is non-zero, a note below the chart reads:
> "Analyst feedback has influenced this score (signal: {+1.0 | -1.0})"

### `DispositionControls.tsx`

Reusable component used in `ScanEvidencePanel`, `AlertsPage`, and `PivotQueuePage`.

```typescript
interface DispositionControlsProps {
  currentDisposition: string | null;
  onSubmit: (disposition: string, notes?: string) => Promise<void>;
  options?: DispositionOption[];  // defaults to all 5 values
}
```

Renders a compact button group. On click, opens an inline notes textarea before submitting. Reflects the current disposition as a coloured badge.

### `AlertsPage.tsx` Modifications

1. Add `DispositionControls` to each `AlertCard` alongside the existing "Mark Reviewed" button.
2. Add a "Disposition" filter dropdown (all / confirmed / benign / uncertain / unreviewed) to the filter bar.
3. Add `GET /alerts/` parameter `disposition` on filter change.

---

## Database Migration Strategy

### New Tables to CREATE

```sql
CREATE TABLE seed_profiles (...)
CREATE TABLE query_variants (...)
CREATE TABLE query_variant_executions (...)
CREATE TABLE scan_evidence (...)
CREATE TABLE pivot_candidates (...)
CREATE TABLE channel_score_components (...)
CREATE TABLE channel_health_events (...)
CREATE TABLE disposition_history (...)
```

All created via `Base.metadata.create_all()` in `init_db()` — no manual SQL needed for fresh installs.

### Columns to ALTER TABLE ADD (existing tables)

#### `channels`
```sql
ALTER TABLE channels ADD COLUMN poll_tier VARCHAR(16) DEFAULT 'LOW';
ALTER TABLE channels ADD COLUMN last_poll_attempted_at DATETIME;
ALTER TABLE channels ADD COLUMN consecutive_error_count INTEGER DEFAULT 0;
ALTER TABLE channels ADD COLUMN error_state BOOLEAN DEFAULT 0;
ALTER TABLE channels ADD COLUMN channel_status VARCHAR(16) DEFAULT 'active';
ALTER TABLE channels ADD COLUMN discovery_variant_id INTEGER;
```

#### `channel_scan_results`
```sql
ALTER TABLE channel_scan_results ADD COLUMN discovered_by_variant_id INTEGER;
ALTER TABLE channel_scan_results ADD COLUMN composite_score FLOAT;
```

#### `alerts`
```sql
ALTER TABLE alerts ADD COLUMN disposition VARCHAR(32);
ALTER TABLE alerts ADD COLUMN disposition_notes TEXT;
ALTER TABLE alerts ADD COLUMN disposition_by VARCHAR(128);
ALTER TABLE alerts ADD COLUMN disposition_at DATETIME;
```

### Extension to `_migrate_sqlite_columns()`

```python
# In database.py _migrate_sqlite_columns():

# channels new columns
res = await conn.exec_driver_sql("PRAGMA table_info(channels)")
existing_channels_cols = {row[1] for row in res.fetchall()}
new_channel_cols = [
    *existing_new_channel_cols,   # already there
    ("poll_tier",                  "VARCHAR(16) DEFAULT 'LOW'"),
    ("last_poll_attempted_at",     "DATETIME"),
    ("consecutive_error_count",    "INTEGER DEFAULT 0"),
    ("error_state",                "BOOLEAN DEFAULT 0"),
    ("channel_status",             "VARCHAR(16) DEFAULT 'active'"),
    ("discovery_variant_id",       "INTEGER"),
]

# channel_scan_results new columns
new_scan_cols = [
    *existing_new_scan_cols,
    ("discovered_by_variant_id",   "INTEGER"),
    ("composite_score",            "FLOAT"),
]

# alerts new columns
res = await conn.exec_driver_sql("PRAGMA table_info(alerts)")
existing_alert_cols = {row[1] for row in res.fetchall()}
new_alert_cols = [
    ("disposition",        "VARCHAR(32)"),
    ("disposition_notes",  "TEXT"),
    ("disposition_by",     "VARCHAR(128)"),
    ("disposition_at",     "DATETIME"),
]
for col_name, col_type in new_alert_cols:
    if col_name not in existing_alert_cols:
        await conn.exec_driver_sql(f"ALTER TABLE alerts ADD COLUMN {col_name} {col_type}")
```

### Indexes to CREATE

All created via SQLAlchemy `Index` objects in `models.py` — `create_all()` handles them. For existing databases, they can be applied manually or via a one-time migration script:

```sql
CREATE INDEX IF NOT EXISTS ix_scan_evidence_scan_job_id ON scan_evidence(scan_job_id);
CREATE INDEX IF NOT EXISTS ix_scan_evidence_channel_username ON scan_evidence(channel_username);
CREATE INDEX IF NOT EXISTS ix_scan_evidence_risk_level ON scan_evidence(risk_level);
CREATE INDEX IF NOT EXISTS ix_scan_evidence_last_classified_at ON scan_evidence(last_classified_at);
CREATE INDEX IF NOT EXISTS ix_scan_evidence_disposition ON scan_evidence(disposition);
CREATE INDEX IF NOT EXISTS ix_pivot_candidates_status ON pivot_candidates(status);
CREATE INDEX IF NOT EXISTS ix_pivot_candidates_source_channel ON pivot_candidates(source_channel_username);
CREATE INDEX IF NOT EXISTS ix_seed_profiles_is_active ON seed_profiles(is_active);
CREATE INDEX IF NOT EXISTS ix_query_variants_seed_profile_id ON query_variants(seed_profile_id);
CREATE INDEX IF NOT EXISTS ix_channel_health_channel_id_occurred_at ON channel_health_events(channel_id, occurred_at);
```

---

## Testing Strategy

### Unit Test File Structure

```
backend/tests/
├── conftest.py                   # async pytest fixtures, in-memory SQLite DB, mock Telegram client
├── unit/
│   ├── test_normaliser.py        # Requirement 18.1
│   ├── test_seed_variants.py     # Requirement 18.2
│   ├── test_composite_scoring.py # Requirement 18.3
│   ├── test_pivot_eligibility.py # Requirement 18.4
│   ├── test_feedback_metrics.py  # Requirement 18.5
│   └── test_normaliser_pbt.py    # Property-based tests (Hypothesis)
└── integration/
    └── test_scan_evidence.py     # Requirement 18.6
```

### Key Test Cases

```python
# test_normaliser.py
def test_nfc_normalisation():
    # decomposed 'a' + combining acute → precomposed 'á'
    assert normalise("\u0061\u0301") == normalise("\u00e1")

def test_zero_width_removal():
    assert normalise("drug\u200bsale") == "drug sale"   # ZWS removed then space-normalised

def test_lookalike_replacement():
    assert normalise("сrасk") == "crack"   # Cyrillic с,а,с → c,a,c

def test_repeated_punctuation():
    assert normalise("buy now!!!!!!") == "buy now!!"

def test_hyphen_space_interchange():
    assert normalise("drug-sale") == normalise("drug sale")

def test_immutability():
    original = "test\u200bstring"
    _ = normalise(original)
    assert original == "test\u200bstring"

# test_seed_variants.py
def test_spacing_variants_two_token_max():
    for variant in generate_variants("wholesale cocaine supply chain", "en"):
        assert len(variant.split()) <= 2

def test_minimum_three_variants():
    variants = generate_variants("heroin", "hi-IN")
    assert len(variants) >= 3

def test_transliteration_roundtrip():
    # "नशा" (nasha) → Latin → back to Devanagari should be equivalent
    latin = transliterate_to_latin("नशा")
    back = transliterate_to_devanagari(latin)
    assert back == "नशा"

# test_composite_scoring.py
def test_zero_high_count_cannot_be_high_risk():
    components = make_components(high_confidence_message_count=0, identifier_density=1.0, valid_pivot_count=5)
    score, risk = compute_composite_risk(components)
    assert risk != "HIGH"

def test_negative_analyst_signal_lowers_score():
    base = make_components(analyst_confirmation_signal=0.0)
    neg  = make_components(analyst_confirmation_signal=-1.0)
    score_base, _ = compute_composite_risk(base)
    score_neg, _  = compute_composite_risk(neg)
    assert score_neg < score_base

# test_pivot_eligibility.py
def test_public_tme_link_eligible():
    assert is_eligible_pivot("https://t.me/drugchannel99") is True

def test_joinchat_rejected():
    assert is_eligible_pivot("https://t.me/joinchat/AAABBBCCC") is False

def test_plus_invite_rejected():
    assert is_eligible_pivot("https://t.me/+AbCdEfGhIjK") is False

def test_already_watchlisted_sets_already_monitored():
    # returns status=already_monitored, not creating duplicate
    ...

# test_feedback_metrics.py
def test_precision_zero_when_no_dispositions():
    assert compute_precision(confirmed=0, false_positive=0) == 0.0

def test_yield_zero_when_no_candidates():
    assert compute_yield(confirmed=5, candidates_found=0) == 0.0

# test_scan_evidence.py (integration)
async def test_evidence_created_for_high_medium(mock_telegram_client, test_db):
    job_id = await trigger_scan(["test_seed"], client=mock_telegram_client)
    await wait_for_job(job_id)
    evidence = await test_db.execute(select(ScanEvidence).where(ScanEvidence.scan_job_id == job_id))
    rows = evidence.scalars().all()
    assert all(r.risk_level in ("HIGH", "MEDIUM") for r in rows)

async def test_no_evidence_for_low_risk(mock_telegram_client, test_db):
    # mock returns only LOW-scoring messages
    job_id = await trigger_scan(["low_signal_seed"], client=mock_telegram_client)
    await wait_for_job(job_id)
    evidence = await test_db.execute(select(ScanEvidence).where(ScanEvidence.scan_job_id == job_id))
    assert evidence.scalars().first() is None
```

### Mock Strategy

`conftest.py` provides a `MockTelegramClient` with:
- `iter_messages(username, limit)` yields pre-constructed `FakeTelegramMessage` objects with controllable `.message`, `.id`, `.date`, `.media` attributes.
- `SearchRequest` returns a fixed list of `FakeChannel` objects.
- Messages are tagged `HIGH`, `MEDIUM`, or `LOW` via their text content (the real classifier runs on them).

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

The [Hypothesis](https://hypothesis.readthedocs.io/en/latest/) library (`pip install hypothesis`) is used for property-based testing, integrated with pytest. These tests are applicable here because the normaliser, variant generator, scoring formula, pivot eligibility filter, and feedback metric computations are pure functions with large input spaces. Each property test runs a minimum of 100 iterations.

Each test comment uses the format: `# Feature: telemonitor-intelligence-platform, Prop {N}: {property_text}`

### Property 1: Normaliser Idempotence

*For any* string `x`, applying `normalise()` twice produces the same result as applying it once: `normalise(normalise(x)) == normalise(x)`.

**Validates: Requirements 6.1, 18.7**

### Property 2: Normaliser Input Immutability

*For any* string `x`, the value of `x` is identical before and after a call to `normalise(x)`.

**Validates: Requirements 6.3**

### Property 3: Query Variant Two-Token Maximum

*For any* non-empty seed text string and language region, every string in the list returned by `generate_variants()` contains at most two whitespace-separated tokens.

**Validates: Requirements 1.5**

### Property 4: Query Variant Minimum Count

*For any* non-empty seed text string with a supported language region, `generate_variants()` returns at least three distinct variants.

**Validates: Requirements 1.4**

### Property 5: Composite Score Bounds

*For any* valid set of score component values (each individually clamped to `[0.0, 1.0]`), the computed Composite_Score is within `[0.0, 1.0]`.

**Validates: Requirements 5.3**

### Property 6: Anti-Spam Guard Invariant

*For any* set of score components where `high_confidence_message_count` equals zero, `classify_composite_risk()` does not return `"HIGH"` regardless of the values of `identifier_density` and `valid_pivot_count`.

**Validates: Requirements 5.4**

### Property 7: Pivot Eligibility joinchat Links Always Rejected

*For any* string matching the pattern `t.me/joinchat/*` or `t.me/+*`, `is_eligible_pivot()` returns `False`.

**Validates: Requirements 3.3**

### Property 8: Pivot Deduplication Invariant

*For any* list of raw pivot candidates (possibly containing duplicates on `(candidate_value, source_channel_username)`), the result of `deduplicate_pivots()` contains exactly one entry per unique `(candidate_value, source_channel_username)` pair.

**Validates: Requirements 3.8**

### Property 9: Feedback Metrics Safety with Zero Denominators

*For any* non-negative integers `confirmed`, `false_positive`, and `candidates_found`, `compute_precision()` and `compute_yield()` each return a value in `[0.0, 1.0]` and do not raise an exception even when denominators are zero.

**Validates: Requirements 7.5**

### Property 10: Poll Tier Assignment Totality

*For any* channel `risk_level` value in `{"HIGH", "MEDIUM", "LOW"}` with `is_active=True`, `assign_poll_tier()` returns exactly one of `{"HIGH", "MEDIUM", "LOW"}` and never raises an exception.

**Validates: Requirements 14.1, 14.2, 14.3, 14.4**

---

## Error Handling

### Scanner Error Handling

- `FloodWaitError` during seed search: sleep for `fwe.seconds + 5`, continue to next seed. Record in `channel_health_events` for the affected query.
- `ChannelPrivateError`, `UsernameInvalidError`, `UsernameNotOccupiedError` during channel scan: skip channel, log at DEBUG, do not write evidence. Set `channel_status = inaccessible`.
- Generic `Exception` during `_scan_one_channel`: log at WARNING with traceback, increment `consecutive_error_count`. Do not fail the entire scan job.

### Normaliser Error Handling

The normaliser is a pure function with no I/O. It should not raise exceptions for any string input. Callers are not required to wrap it in try/except. If `transliteration_hook` raises, the exception propagates to the caller (hook errors are the caller's responsibility).

### OCR Error Handling

```python
try:
    ocr_result = await extract_text_from_image(media_path)
    ocr_success = True
    ocr_confidence = mean([box[2] for box in raw_boxes]) if raw_boxes else 0.0
except Exception as exc:
    logger.debug("OCR failed for %s: %s", media_path, exc)
    ocr_success = False
    ocr_confidence = None
    ocr_text = None
```

### API Error Handling

All new routers follow the existing convention:
- HTTP 404: resource not found, `{"detail": "..."}`
- HTTP 400: bad request (invalid enum value, malformed JSON), `{"detail": "..."}`
- HTTP 409: conflict (duplicate seed text), `{"detail": "Seed profile with this normalised text already exists"}`
- HTTP 422: unprocessable (variant exceeds two tokens), `{"detail": "..."}`
- HTTP 500: unexpected server error — logs full traceback at ERROR level
