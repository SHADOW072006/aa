# Implementation Plan: TeleMonitor Intelligence Platform

## Overview

Nine coupled enhancements to the existing FastAPI + React OSINT dashboard: structured seed
profiles, pivot candidate queuing, message-level scan evidence, composite channel scoring, a
standalone normaliser module, analyst dispositions with feedback metrics, expanded REST APIs,
new frontend pages and components, and operational reliability improvements (adaptive polling,
FloodWait backoff, OCR gating). Every existing API route, database table, and UI page must
remain fully functional throughout.

---

## Tasks

- [x] 1. Extend DB models — new ORM models and columns on existing tables
  - In `app/db/models.py`, add eight new SQLAlchemy ORM models: `SeedProfile`,
    `QueryVariant`, `QueryVariantExecution`, `ScanEvidence`, `PivotCandidate`,
    `ChannelScoreComponents`, `ChannelHealthEvent`, `DispositionHistory`.
  - Add new columns to `Channel`: `poll_tier`, `last_poll_attempted_at`,
    `consecutive_error_count`, `error_state`, `channel_status`, `discovery_variant_id`.
  - Add new columns to `ChannelScanResult`: `discovered_by_variant_id`, `composite_score`.
  - Add new columns to `Alert`: `disposition`, `disposition_notes`, `disposition_by`,
    `disposition_at`.
  - Define all indexes and unique constraints as described in the design document
    (UniqueConstraint on `seed_profiles.seed_text_normalised`, `query_variants.variant_text`,
    `scan_evidence(channel_username, telegram_message_id)`,
    `pivot_candidates(candidate_value, source_channel_username)`,
    `channel_score_components.channel_scan_result_id`).
  - Use SQLAlchemy Boolean, Integer autoincrement, and Text types for SQLite + PostgreSQL
    compatibility per Requirement 17.3.
  - _Requirements: 1.1, 2.1, 3.2, 4.1, 5.2, 7.9, 14.5, 15.3, 17.1, 17.2, 17.3_

- [x] 2. Extend database migration — idempotent column additions and indexes
  - In `app/db/database.py`, extend `_migrate_sqlite_columns()` to cover all new columns on
    `channels`, `channel_scan_results`, and `alerts` using `PRAGMA table_info` checks exactly
    as the existing pattern does.
  - Ensure `init_db()` calls `Base.metadata.create_all()` so the eight new tables are created
    on a fresh database without manual SQL.
  - _Requirements: 17.4_

- [x] 3. Add new Settings fields to `app/core/config.py`
  - Add fields: `MIN_BACKOFF: int = 10`, `BACKOFF_MULTIPLIER: float = 2.0`,
    `MAX_RETRY_COUNT: int = 5`, `ERROR_STATE_WINDOW_HOURS: int = 24`,
    `ERROR_STATE_THRESHOLD: int = 3`, `POLL_INTERVAL_HIGH: int = 30`,
    `POLL_INTERVAL_MEDIUM: int = 60`, `POLL_INTERVAL_LOW: int = 300`,
    `COMPOSITE_HIGH_MSG_CAP: int = 10`, `COMPOSITE_INCIDENT_CAP: int = 5`,
    `COMPOSITE_PIVOT_CAP: int = 5`.
  - _Requirements: 15.2, 14.1, 5.3_

- [x] 4. Create the Normaliser module — `app/extractors/normaliser.py`
  - Implement the public function `normalise(text: str, transliteration_hook=None) -> str`
    applying the 7 steps in order: NFC normalisation, zero-width character removal
    (U+200B–U+200F, U+00AD, U+2060, U+FEFF), look-alike character replacement via
    `CONFUSABLE_MAP` and `str.maketrans()`, lowercase conversion, optional
    `transliteration_hook` applied after lowercase, repeated-punctuation compression
    (3+ consecutive punctuation collapsed to 2), repeated-whitespace normalisation,
    hyphen→space interchange.
  - Define `CONFUSABLE_MAP` with at minimum 24 Cyrillic/Greek→ASCII entries as listed in
    the design document. Build `_TRANS_TABLE` once at module load.
  - The function must never mutate its input and must be importable as a standalone module
    with no database dependency (`from app.extractors.normaliser import normalise`).
  - _Requirements: 6.1, 6.2, 6.3, 6.8_

- [x] 5. Update `app/classifiers/classifier.py` to use the Normaliser
  - Remove the inline `normalise_text()` function (or keep it as a thin wrapper for one
    release cycle, calling `normalise()` from the new module).
  - Import `from app.extractors.normaliser import normalise as _normalise_text`.
  - In `classify()`, call `_normalise_text(text)` before passing text to `lexicon_score()`.
  - In `lexicon_score()`, ensure the `norm` variable uses the imported normaliser result.
  - _Requirements: 6.4_

- [x] 6. Create CRUD helpers for new tables in `app/db/crud.py`
  - Add async CRUD helpers for: `SeedProfile` (create, get, list, update),
    `QueryVariant` (create or get-existing by variant_text, list by seed_profile_id),
    `QueryVariantExecution` (create), `ScanEvidence` (upsert by channel_username +
    telegram_message_id — update classifier fields only, never overwrite raw text),
    `PivotCandidate` (create or skip-duplicate by candidate_value + source_channel_username,
    list with filters), `ChannelScoreComponents` (create/update by channel_scan_result_id),
    `ChannelHealthEvent` (create, list last-N by channel_id), `DispositionHistory` (create).
  - The `upsert_scan_evidence()` helper must implement the insert-or-update logic from the
    design: on existing row, update `last_classified_at`, `classifier_score`, `risk_level`,
    `severity_tier`, `categories`, `matched_terms` only; never overwrite `raw_text`,
    `caption_text`, `ocr_text`.
  - _Requirements: 4.4, 4.9, 3.8, 5.5, 7.9, 15.3_

- [x] 7. Checkpoint — ensure DB layer compiles and existing tests still pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Create Seed Service — `app/services/seed_service.py`
  - Implement `generate_variants(seed_text: str, language_region: str) -> List[str]`:
    normalise the seed, produce spacing variants (2-token slices), hyphen variant of first
    two tokens, transliteration variants for `hi-IN` using `indic_transliteration`, enforce
    two-token max via `_enforce_two_tokens()`, deduplicate within the generated list, guarantee
    minimum three distinct variants with a contextual-suffix fallback for single-token seeds.
  - Implement `create_seed_profile()`, `update_seed_profile()`, `list_seed_profiles()`,
    `get_seed_profile()` calling the CRUD helpers.
  - On create/update, generate variants and persist via CRUD, using the global dedup logic:
    look up existing `QueryVariant` by `variant_text` before inserting; reuse the existing row
    id if found.
  - Implement `get_active_variants(db) -> List[Tuple[QueryVariant, SeedProfile]]` for scanner
    consumption.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.9, 2.1_

- [x] 9. Create Pivot Service — `app/services/pivot_service.py`
  - Implement eligibility regexes: `_TME_CHANNEL_RE`, `_HANDLE_RE`, `_INVITE_RE` as in the
    design.
  - Implement `is_eligible_pivot(candidate_value: str) -> bool` returning False for
    `t.me/joinchat/`, `t.me/+`, invite hashes, non-t.me URLs, and self-references.
  - Implement `extract_pivot_candidates(text, source_channel, fwd_source, identifiers,
    identifier_frequency) -> List[RawPivotCandidate]` covering channel links, @handles,
    forwarded sources, and recurring payment identifiers (frequency >= 2 within same scan
    session for a channel).
  - Implement `deduplicate_pivots(candidates) -> List[RawPivotCandidate]` returning one entry
    per unique `(candidate_value, source_channel_username)` pair.
  - Implement `promote_pivot(db, pivot_id, evaluated_by)` that upserts a `Channel` record
    with `is_active=True` when status is set to `promoted`; sets `already_monitored` when the
    channel is already in the watchlist.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9_

- [x] 10. Create Scoring Service — `app/services/scoring_service.py`
  - Implement `compute_and_store_composite_score(db, scan_result_id, channel_username,
    scan_job_id, high_count, all_scores, categories_per_message,
    most_recent_high_risk_ts, scan_window_end, identifier_counts, total_messages,
    pivot_count) -> ChannelScoreComponents` using the exact formula from the design.
  - Implement `normalise_count(x, cap) = min(x, cap) / cap`.
  - Implement `recency_weight` decay: `max(0.0, 1.0 - (age_hours / 72.0))`.
  - Implement `identifier_density = messages_with_identifier / total_messages`.
  - Implement `analyst_confirmation_signal` lookup from existing `ScanEvidence` dispositions.
  - Implement `classify_composite_risk(score, high_confidence_count) -> str` with the
    anti-spam guard: when `high_confidence_count == 0`, clamp result to `"MEDIUM"` even if
    score exceeds `HIGH_RISK_THRESHOLD`.
  - Persist `ChannelScoreComponents` row via CRUD and update `channel_scan_results.composite_score`.
  - Preserve `avg_score` unchanged.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.8_

- [x] 11. Create Feedback Service — `app/services/feedback_service.py`
  - Implement `record_disposition(db, target_type, target_id, disposition, notes, changed_by)`
    that writes a `DispositionHistory` row with the previous value then updates the target
    record's disposition fields (Alert, ScanEvidence, or PivotCandidate as appropriate).
  - Implement `compute_feedback_metrics(db, seed_profile_id) -> FeedbackMetrics` using the
    SQL aggregation query from the design (join `scan_evidence → query_variants` filtered by
    `seed_profile_id`).
  - Compute `precision = confirmed / (confirmed + false_positive) if denominator > 0 else 0.0`
    and `yield_val = confirmed / candidates_found if candidates_found > 0 else 0.0`.
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9_

- [x] 12. Checkpoint — ensure service layer is importable and unit-testable in isolation
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Create Seeds API router — `app/api/seeds.py`
  - Implement endpoints: `GET /seeds/profiles`, `POST /seeds/profiles`,
    `GET /seeds/profiles/{id}`, `PATCH /seeds/profiles/{id}`,
    `GET /seeds/profiles/{id}/provenance`, `GET /seeds/profiles/{id}/metrics`,
    `GET /seeds/metrics`, `GET /seeds/variants`.
  - `POST /seeds/profiles` returns HTTP 409 if normalised seed text already exists (Requirement 8.5).
  - `PATCH` accepts only `priority`, `intent_type`, `threat_category`, `is_active`.
  - Return HTTP 400 for invalid `created_source`; HTTP 422 if a variant text would exceed two
    tokens (Requirement 8.6).
  - `GET /seeds/metrics` returns all active profiles sorted by precision descending.
  - _Requirements: 1.8, 2.5, 7.6, 7.7, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 9.5_

- [x] 14. Create Pivots API router — `app/api/pivots.py`
  - Implement endpoints: `GET /pivots/`, `GET /pivots/{id}`, `PATCH /pivots/{id}`,
    `GET /channels/{username}/pivots`.
  - `GET /pivots/` accepts standard query params: `skip`, `limit`, `status`,
    `candidate_type`, `source_channel_username`, `date_from`, `date_to`.
  - `PATCH /pivots/{id}` triggers `pivot_service.promote_pivot()` when status becomes
    `promoted`. When the channel is already in the watchlist, return HTTP 200 with the
    existing Channel; otherwise return HTTP 201 with the new Channel (Requirement 8.7).
  - _Requirements: 3.10, 8.1, 8.2, 8.3, 8.7_

- [x] 15. Create Evidence API router — `app/api/evidence.py`
  - Implement endpoints: `GET /scan/jobs/{job_id}/evidence`,
    `GET /scan/evidence/{id}`, `GET /channels/{username}/evidence`,
    `POST /scan/evidence/reclassify`, `PATCH /scan/evidence/{id}/disposition`.
  - `GET /scan/jobs/{job_id}/evidence` accepts `risk_level`, `category`, `disposition`,
    `skip`, `limit`.
  - `POST /scan/evidence/reclassify` accepts `ReclassifyRequest(cutoff, scan_job_id,
    limit)`, re-runs `classify(row.normalised_text)` on matching rows, commits in batches of
    100, returns `{"updated": N}`.
  - Extend `GET /scan/jobs/{job_id}` response to include `evidence_counts` with `total`,
    `HIGH`, `MEDIUM`, `by_category`.
  - Extend `GET /scan/results/{result_id}` response to include `score_breakdown` containing
    all `ChannelScoreComponents` fields.
  - _Requirements: 4.6, 4.7, 4.8, 5.6, 8.2_

- [x] 16. Create Dispositions API router — `app/api/dispositions.py`
  - Implement `POST /dispositions/` accepting a list of
    `{target_type, target_id, disposition, notes, reviewed_by}`.
  - Validate disposition value against the enum; return HTTP 400 with descriptive error on
    unrecognised value.
  - Call `feedback_service.record_disposition()` for each item.
  - Return `{"updated": N, "errors": [...]}`.
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 8.4_

- [x] 17. Add channel health endpoint to `app/api/channels.py`
  - Add `GET /channels/{id}/health` returning `ChannelHealthResponse`: `last_successful_collection_at`,
    `consecutive_error_count`, `error_state`, `poll_tier`, `channel_status`, and the most
    recent five `ChannelHealthEvent` records.
  - _Requirements: 15.5_

- [x] 18. Register new routers in `app/main.py`
  - Import and register: `seeds_router` (prefix `/seeds`), `pivots_router` (prefix `/pivots`),
    `evidence_router` (no prefix — routes include full paths), `dispositions_router`
    (prefix `/dispositions`).
  - Ensure the existing routers (`channels`, `alerts`, `graph`, `import`, `search`,
    `discovery`, `scan`) are unchanged.
  - _Requirements: 8.1, 8.2_

- [x] 19. Checkpoint — verify all backend routes resolve and existing routes unchanged
  - Ensure all tests pass, ask the user if questions arise.

- [x] 20. Enhance `app/collectors/scanner.py` — seed profiles, evidence, pivots, and scoring
  - Replace `DEFAULT_SEEDS` iteration in `_run_scan_job()` with
    `seed_service.get_active_variants(db)` and iterate over `(variant, profile)` pairs.
  - Write `discovered_by_variant_id` and `seed_term` onto each `ChannelScanResult` row.
  - Record a `QueryVariantExecution` row per variant per scan run.
  - In `_scan_one_channel()`, after classifying each message:
    - If `risk_level` is HIGH or MEDIUM, call `crud.upsert_scan_evidence()` with separate
      `raw_text`, `caption_text`, `ocr_text` (do not merge before writing), and
      `normalised_text = normalise(raw_text + " " + caption_text)`.
    - Build an `identifier_frequency` counter per channel for the scan session.
    - After all messages are processed, call `pivot_service.extract_pivot_candidates()` and
      persist eligible, deduplicated `PivotCandidate` rows.
    - Call `scoring_service.compute_and_store_composite_score()` and update
      `channel_scan_results.composite_score`; leave `avg_score` unchanged.
  - Preserve all existing connected-nodes discovery and auto-add-to-watchlist logic.
  - _Requirements: 2.2, 2.7, 3.1, 4.3, 4.5, 5.1, 6.4_

- [x] 21. Enhance `app/collectors/telegram_collector.py` — poll tiers, FloodWait, OCR gating
  - Add `POLL_TIERS = {"HIGH": settings.POLL_INTERVAL_HIGH, "MEDIUM": settings.POLL_INTERVAL_MEDIUM,
    "LOW": settings.POLL_INTERVAL_LOW}`.
  - Implement `assign_poll_tier(channel) -> str` per design logic (uses `channel.risk_level`
    or Composite_Score-derived level if available).
  - Replace single-interval `run_forever()` loop with the tier-aware scheduler that checks
    `last_poll_attempted_at` per channel.
  - Wrap each channel poll in `_collect_channel_safe()` which: updates
    `last_poll_attempted_at` and `poll_tier` before polling; handles `FloodWaitError` with
    exponential backoff (`max(fwe.seconds, MIN_BACKOFF) * BACKOFF_MULTIPLIER**consecutive_error_count`);
    records a `ChannelHealthEvent` for each error type; calls `_reset_error_state()` on success;
    sets `channel_status = inaccessible` and `is_active = False` on
    `ChannelPrivateError/UsernameInvalidError/UsernameNotOccupiedError`; sets `error_state = True`
    after `ERROR_STATE_THRESHOLD` consecutive errors within `ERROR_STATE_WINDOW_HOURS`.
  - Add OCR gating in `_process_message()`: call `should_run_ocr(file_ext, mime_type,
    channel.poll_tier, message_has_lexicon_match)` before invoking EasyOCR; set
    `ocr_skip_reason` on the evidence/message record when skipping; apply media retention
    logic (keep HIGH evidence; delete MEDIUM/LOW unless risk_level is HIGH).
  - Pass message text through `normalise()` before `classify()`.
  - _Requirements: 6.4, 6.5, 6.6, 6.7, 14.1, 14.2, 14.3, 14.4, 14.5, 14.6,
    15.1, 15.2, 15.3, 15.4, 15.6, 15.7, 16.1, 16.2, 16.3, 16.4_

- [x] 22. Update `app/collectors/channel_discovery.py` — use SeedProfile/QueryVariant
  - Replace hardcoded seed list iteration with `seed_service.get_active_variants(db)`.
  - Write `discovery_variant_id` onto new Channel records added to the watchlist.
  - Write `discovered_by_variant_id` onto `ChannelScanResult` rows created by the discovery
    engine.
  - _Requirements: 2.4, 1.9_

- [x] 23. Checkpoint — verify collector changes run without errors against mock client
  - Ensure all tests pass, ask the user if questions arise.

- [x] 24. Create Seeds API client — `frontend/src/api/seeds.ts`
  - Define TypeScript interfaces: `SeedProfile`, `QueryVariant`, `FeedbackMetrics`,
    `SeedProfileCreate`, `SeedProfileUpdate`, `ProvenanceEntry`.
  - Implement typed functions: `fetchSeedProfiles()`, `createSeedProfile()`,
    `updateSeedProfile()`, `fetchSeedMetrics()`, `fetchProfileMetrics()`,
    `fetchProfileProvenance()`, `fetchQueryVariants()`.
  - _Requirements: 9.1, 9.4_

- [x] 25. Create Pivots API client — `frontend/src/api/pivots.ts`
  - Define TypeScript interfaces: `PivotCandidate`, `PivotUpdate`.
  - Implement typed functions: `fetchPivots()`, `fetchPivot()`, `updatePivot()`,
    `fetchChannelPivots()`.
  - _Requirements: 10.1, 10.4, 10.5_

- [x] 26. Create Evidence API client — `frontend/src/api/evidence.ts`
  - Define TypeScript interfaces: `ScanEvidence`, `EvidenceFilters`, `ReclassifyRequest`.
  - Implement typed functions: `fetchJobEvidence()`, `fetchEvidence()`,
    `fetchChannelEvidence()`, `reclassifyEvidence()`, `submitEvidenceDisposition()`.
  - _Requirements: 11.1, 11.3_

- [x] 27. Add new types and calls to `frontend/src/api/client.ts`
  - Add `ScoreBreakdown` / `ChannelScoreComponents` interface.
  - Add `DispositionUpdate` interface and `submitDisposition()`, `batchDisposition()` calls.
  - Add `fetchChannelHealth()` call for `GET /channels/{id}/health`.
  - Extend `ChannelScanResult` interface with `composite_score?: number` and
    `score_breakdown?: ChannelScoreComponents`.
  - Extend `Alert` interface with `disposition`, `disposition_notes`, `disposition_by`,
    `disposition_at` fields.
  - _Requirements: 5.6, 12.1, 13.1_

- [x] 28. Create `DispositionControls` component —
    `frontend/src/components/DispositionControls.tsx`
  - Implement the reusable component with props `currentDisposition`, `onSubmit`,
    `options` (defaults to all 5 disposition values).
  - Render a compact button group; on click open an inline notes textarea before submitting.
  - Display current disposition as a colour-coded badge.
  - _Requirements: 12.1, 12.3, 12.4_

- [x] 29. Create `ScoreBreakdownPanel` component —
    `frontend/src/components/ScoreBreakdownPanel.tsx`
  - Accept `scoreBreakdown: ChannelScoreComponents` as props.
  - Render a horizontal bar chart (CSS flexbox, no chart library) for each of the 7 score
    components showing the component label, weighted contribution as a percentage of
    Composite_Score, and the raw numeric value.
  - Use plain-language labels per design: "Highest single message score",
    "High-confidence message count", "Distinct threat categories", "Recent activity weight",
    "Identifier density", "Active pivots found", "Analyst feedback signal".
  - When `analyst_confirmation_signal` is non-zero, display the note:
    "Analyst feedback has influenced this score (signal: {+1.0 | -1.0})".
  - _Requirements: 13.1, 13.2, 13.3, 13.4_

- [x] 30. Create `ScanEvidencePanel` component —
    `frontend/src/components/ScanEvidencePanel.tsx`
  - Accept `jobId`, `resultId`, `channelUsername` as props.
  - Fetch evidence via `fetchJobEvidence()` on mount; support pagination.
  - For each evidence row display: `telegram_message_id`, `message_timestamp`, `risk_level`
    badge, `normalised_text` truncated at 400 chars with "Show more" toggle,
    `classifier_score`, `categories` chips, `matched_terms`, `extracted_identifiers`,
    disposition status.
  - Show "OCR" badge and collapsible raw `ocr_text` section when `ocr_text` is non-null.
  - Include filter bar for `risk_level`, `category`, `disposition`, and free-text search
    across `normalised_text`.
  - Embed `DispositionControls` per row; submit via `submitEvidenceDisposition()` and
    update row in local state immediately.
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

- [x] 31. Create `SeedPerformancePage` — `frontend/src/pages/SeedPerformancePage.tsx`
  - On mount, fetch seed profiles and merge metrics from `GET /seeds/metrics`.
  - Render sortable, filterable table with columns: seed text, threat_category, priority,
    is_active, candidates_found, messages_processed, confirmed_count, false_positive_count,
    precision, yield, created_source.
  - Row click reveals inline edit form for `priority`, `intent_type`, `threat_category`,
    `is_active`; on save call `updateSeedProfile()`.
  - Provide create form (`POST /seeds/profiles`) with inline validation errors from the
    backend.
  - Refresh metrics for the affected row without full page reload when a disposition is
    submitted elsewhere on the page.
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

- [x] 32. Create `PivotQueuePage` — `frontend/src/pages/PivotQueuePage.tsx`
  - On mount, fetch `GET /pivots/?status=pending`; re-fetch on filter change.
  - Render paginated pivot list with filter bar for `candidate_type`,
    `source_channel_username`, `status`, date range.
  - Row click expands `PivotDetailDrawer` showing: full `candidate_value`, source channel
    username + risk level, up to 3 sample messages, Promote / Reject / Mark Inaccessible
    buttons.
  - On Promote: call `updatePivot({status: "promoted"})`, optimistically set row status in
    local state, display toast "Channel @{username} added to watchlist."
  - On Reject: call `updatePivot({status: "rejected"})`, update row status in local state
    without removing the row.
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

- [x] 33. Update `frontend/src/pages/AlertsPage.tsx` — dispositions and filter
  - Add `DispositionControls` to each `AlertCard` alongside the existing "Mark Reviewed"
    button; submit via `submitDisposition()` and reflect change without page reload.
  - Add a Disposition filter dropdown (all / confirmed / benign / uncertain / unreviewed) to
    the filter bar; pass `disposition` query param to `fetchAlerts()`.
  - Add disposition summary badge to each `AlertCard` showing current disposition value.
  - _Requirements: 12.1, 12.2, 12.3, 12.4_

- [x] 34. Update `frontend/src/pages/ScanPage.tsx` — evidence sub-panel
  - For each `ChannelScanResult` row, add an "Evidence" tab or expandable sub-panel that
    renders `ScanEvidencePanel` with the row's `jobId`, `id` (resultId), and
    `channel_username`.
  - _Requirements: 11.1_

- [x] 35. Update `ChannelDetailModal` — score breakdown tab
  - In `frontend/src/components/ChannelDetailModal.tsx` (create file if it does not exist),
    add a "Score Breakdown" section/tab that renders `ScoreBreakdownPanel` using
    `score_breakdown` from the channel detail API response.
  - _Requirements: 13.1_

- [x] 36. Update `frontend/src/App.tsx` — new navigation entries and routes
  - Import `SeedPerformancePage` and `PivotQueuePage`.
  - Add nav entries: `{ to: "/seeds", label: "Seed Performance", icon: Target }` and
    `{ to: "/pivots", label: "Pivot Queue", icon: GitMerge }`.
  - Add `<Route path="/seeds" element={<SeedPerformancePage />} />` and
    `<Route path="/pivots" element={<PivotQueuePage />} />`.
  - _Requirements: 9.1, 10.1_

- [x] 37. Checkpoint — verify full app builds and existing pages render correctly
  - Ensure all tests pass, ask the user if questions arise.

- [x] 38. Write unit and property tests for the Normaliser
  - [x] 38.1 Write unit tests — `backend/tests/unit/test_normaliser.py`
    - Test NFC normalisation: decomposed `\u0061\u0301` and precomposed `\u00e1` normalise
      identically.
    - Test zero-width character removal for each category (ZWS U+200B, ZWNJ U+200C, ZWJ
      U+200D, LRM U+200E, RLM U+200F, soft hyphen U+00AD, word joiner U+2060, BOM U+FEFF).
    - Test look-alike character replacement for Cyrillic and Greek samples (e.g. `"сrасk"` →
      `"crack"`).
    - Test repeated-punctuation compression: 6 exclamation marks → 2.
    - Test hyphen/space interchange: `normalise("drug-sale") == normalise("drug sale")`.
    - Test input immutability: original string is unmodified after `normalise()`.
    - _Requirements: 6.3, 18.1_

  - [x]* 38.2 Write property tests — `backend/tests/unit/test_normaliser_pbt.py`
    - **Property 1: Normaliser Idempotence** — `normalise(normalise(x)) == normalise(x)` for
      any string.
    - **Property 2: Normaliser Input Immutability** — value of `x` is identical before and
      after `normalise(x)`.
    - Use `hypothesis.given(st.text())` with minimum 100 iterations.
    - **Validates: Requirements 6.1, 6.3, 18.7**

- [x] 39. Write unit and property tests for Query Variant generation
  - [x] 39.1 Write unit tests — `backend/tests/unit/test_seed_variants.py`
    - Test that every returned variant has at most two whitespace-separated tokens for a
      multi-token seed.
    - Test that `generate_variants()` returns at least three distinct variants for a
      single-token seed.
    - Test spacing variant generation, hyphen variant generation.
    - Test transliteration round-trip (Latin → Devanagari → Latin) for a representative Hindi
      crime-domain term with `language_region = "hi-IN"`.
    - _Requirements: 1.4, 1.5, 18.2_

  - [x]* 39.2 Write property tests for Query Variant generation
    - **Property 3: Query Variant Two-Token Maximum** — every string in `generate_variants()`
      result has at most two whitespace-separated tokens for any non-empty seed text and
      supported language region.
    - **Property 4: Query Variant Minimum Count** — `generate_variants()` returns at least
      three distinct variants for any non-empty seed text with a supported language region.
    - **Validates: Requirements 1.4, 1.5**

- [x] 40. Write unit and property tests for Composite Scoring
  - [x] 40.1 Write unit tests — `backend/tests/unit/test_composite_scoring.py`
    - Test that a channel with `high_confidence_message_count = 0` does not receive
      `risk_level = "HIGH"` regardless of `identifier_density` and `valid_pivot_count`.
    - Test that `analyst_confirmation_signal = -1.0` produces a strictly lower
      Composite_Score than the identical channel with `signal = 0.0`.
    - Test that all component weights sum to 1.0.
    - Test that Composite_Score is always within `[0.0, 1.0]` for boundary inputs.
    - _Requirements: 5.3, 5.4, 18.3_

  - [x]* 40.2 Write property tests for Composite Scoring
    - **Property 5: Composite Score Bounds** — for any valid set of score component values,
      Composite_Score is within `[0.0, 1.0]`.
    - **Property 6: Anti-Spam Guard Invariant** — for any components where
      `high_confidence_message_count == 0`, `classify_composite_risk()` never returns
      `"HIGH"`.
    - **Validates: Requirements 5.3, 5.4**

- [x] 41. Write unit and property tests for Pivot Eligibility
  - [x] 41.1 Write unit tests — `backend/tests/unit/test_pivot_eligibility.py`
    - Test that a valid `https://t.me/drugchannel99` URL is eligible.
    - Test that `https://t.me/joinchat/AAABBBCCC` is rejected.
    - Test that `https://t.me/+AbCdEfGhIjK` is rejected.
    - Test that a channel already in the watchlist produces `status = already_monitored`.
    - _Requirements: 3.3, 18.4_

  - [x]* 41.2 Write property tests for Pivot Eligibility
    - **Property 7: joinchat Links Always Rejected** — any string matching `t.me/joinchat/*`
      or `t.me/+*` returns False from `is_eligible_pivot()`.
    - **Property 8: Pivot Deduplication Invariant** — the result of `deduplicate_pivots()`
      contains exactly one entry per unique `(candidate_value, source_channel_username)` pair
      for any input list.
    - **Validates: Requirements 3.3, 3.8**

- [x] 42. Write unit and property tests for Feedback Metrics
  - [x] 42.1 Write unit tests — `backend/tests/unit/test_feedback_metrics.py`
    - Test that `compute_precision(confirmed=0, false_positive=0)` returns `0.0`.
    - Test that `compute_yield(confirmed=5, candidates_found=0)` returns `0.0`.
    - Test that precision returns a value in `[0.0, 1.0]` for valid inputs.
    - _Requirements: 7.5, 18.5_

  - [x]* 42.2 Write property tests for Feedback Metrics and Poll Tiers
    - **Property 9: Feedback Metrics Safety with Zero Denominators** — for any non-negative
      integers `confirmed`, `false_positive`, `candidates_found`, `compute_precision()` and
      `compute_yield()` each return a value in `[0.0, 1.0]` and never raise an exception.
    - **Property 10: Poll Tier Assignment Totality** — for any `risk_level` in
      `{"HIGH", "MEDIUM", "LOW"}` with `is_active=True`, `assign_poll_tier()` returns
      exactly one of `{"HIGH", "MEDIUM", "LOW"}` and never raises an exception.
    - **Validates: Requirements 7.5, 14.1**

- [x] 43. Write integration test for scan evidence persistence —
    `backend/tests/integration/test_scan_evidence.py`
  - Create `conftest.py` with an async pytest fixture providing an in-memory SQLite database
    and a `MockTelegramClient` whose `iter_messages()` yields pre-constructed
    `FakeTelegramMessage` objects with controllable `.message`, `.id`, `.date`, `.media`
    attributes; `SearchRequest` returns a fixed list of `FakeChannel` objects.
  - Test that after a mock scan job completes, `ScanEvidence` rows exist for every message
    whose `risk_level` is HIGH or MEDIUM (the real classifier runs on message text).
  - Test that no `ScanEvidence` row exists for messages that classify as LOW.
  - Test that re-running the scan on the same message updates `last_classified_at` but does
    not overwrite `raw_text`.
  - _Requirements: 18.6_

- [x] 44. Checkpoint — all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 45. Update README and write migration note
  - Add an "Investigator Workflow" section describing the end-to-end flow: seed profile
    creation → scan execution → evidence review → pivot promotion → watchlist monitoring →
    analyst disposition → feedback metrics.
  - Document all new `Settings` fields added in task 3 with types, defaults, valid ranges,
    and descriptions.
  - Add an updated data model section listing all tables (existing + new), their primary
    columns, and foreign-key relationships.
  - Add an operational constraints section: Telegram rate limits, recommended max active seed
    profile count, OCR memory requirements, SQLite WAL mode recommendation.
  - Add a migration note for existing deployments: list of new tables to `CREATE`, columns
    to `ALTER TABLE ADD` on `channels`, `channel_scan_results`, and `alerts`, index
    additions, and instructions for populating `seed_profiles` / `query_variants` from the
    existing flat seed lists in `scanner.py` and `channel_discovery.py`.
  - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5_

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP.
- Each task references specific requirements for traceability.
- Checkpoints ensure incremental validation at phase boundaries.
- Property tests use the [Hypothesis](https://hypothesis.readthedocs.io/en/latest/) library
  (`pip install hypothesis`), integrated with pytest, minimum 100 iterations per property.
- Unit tests complement property tests; both should be present for complete coverage.
- The normaliser (task 4) must be completed before classifier changes (task 5) and before any
  collector enhancements (tasks 20, 21).
- DB models (task 1) and migration (task 2) must be completed before all service and API
  tasks.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2", "3", "4"] },
    { "id": 2, "tasks": ["5", "6"] },
    { "id": 3, "tasks": ["7"] },
    { "id": 4, "tasks": ["8", "9", "10", "11"] },
    { "id": 5, "tasks": ["12"] },
    { "id": 6, "tasks": ["13", "14", "15", "16", "17"] },
    { "id": 7, "tasks": ["18"] },
    { "id": 8, "tasks": ["19"] },
    { "id": 9, "tasks": ["20", "21", "22"] },
    { "id": 10, "tasks": ["23"] },
    { "id": 11, "tasks": ["24", "25", "26", "27"] },
    { "id": 12, "tasks": ["28", "29", "30"] },
    { "id": 13, "tasks": ["31", "32", "33", "34", "35"] },
    { "id": 14, "tasks": ["36"] },
    { "id": 15, "tasks": ["37"] },
    { "id": 16, "tasks": ["38.1", "39.1", "40.1", "41.1", "42.1"] },
    { "id": 17, "tasks": ["38.2", "39.2", "40.2", "41.2", "42.2"] },
    { "id": 18, "tasks": ["43"] },
    { "id": 19, "tasks": ["44"] },
    { "id": 20, "tasks": ["45"] }
  ]
}
```
