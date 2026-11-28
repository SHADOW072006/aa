# Requirements Document

## Introduction

TeleMonitor is an operational Telegram OSINT dashboard used by law enforcement to monitor public Telegram channels for criminal activity. The system collects messages via Telethon MTProto, classifies them against lexicon-based and ML classifiers, extracts identifiers (phone, UPI, crypto wallet, handle), and renders intelligence through a React dashboard with PDF export.

This feature — the TeleMonitor Intelligence Platform — upgrades nine tightly coupled areas: structured seed management, evidence-first pivot queuing, message-level scan evidence persistence, composite channel scoring, a reusable text/OCR normalisation pipeline, an analyst feedback loop, expanded APIs and UI panels, operational reliability improvements, and automated testing with updated documentation.

The upgrade must leave every existing API route, database table, and UI page fully functional. All new capabilities operate exclusively on public Telegram channels; private chats, invite-only groups, and DMs are out of scope.

---

## Glossary

- **System**: The TeleMonitor Intelligence Platform as a whole (backend + frontend + database).
- **Backend**: The FastAPI async Python application.
- **Frontend**: The React 18 + TypeScript + Tailwind web application.
- **Collector**: The `TelegramCollector` background service that polls watchlisted channels via Telethon MTProto.
- **Scanner**: The `trigger_scan` / `_run_scan_job` pipeline that proactively searches Telegram for new channels using seed terms.
- **Classifier**: The two-stage lexicon + ML scoring component (`classifier.py`).
- **Normaliser**: The new reusable text and OCR preprocessing module introduced by this feature.
- **Seed_Profile**: A database record representing one search seed with metadata: seed text, threat category, language/region, intent type, priority, active status, precision/yield metrics, and created_source.
- **Query_Variant**: A derived search string generated from a Seed_Profile — e.g. a transliteration, hyphen variant, or spacing variant of the seed text.
- **Pivot_Candidate**: A public Telegram channel link, handle, forwarded-channel reference, or recurring identifier extracted from confirmed or high-risk channel messages and queued for analyst evaluation.
- **Pivot_Queue**: The database table and UI panel that holds Pivot_Candidates with statuses: pending, evaluated, promoted, rejected, or inaccessible.
- **Scan_Evidence**: An individual flagged message persisted from a scan job, stored in the `scan_evidence` table with full classifier output and extracted identifiers.
- **Composite_Score**: The multi-component channel risk score that replaces the existing simple average score.
- **Score_Components**: The set of individually stored numeric sub-scores that sum to a Composite_Score.
- **Disposition**: An analyst verdict on an alert, Scan_Evidence item, or Pivot_Candidate: confirmed, benign, uncertain, duplicate, or inaccessible.
- **Feedback_Metrics**: Aggregated per-Seed_Profile statistics: candidates_found, messages_processed, alerts_raised, confirmed_count, false_positive_count, precision, yield.
- **OCR_Result**: The output of EasyOCR on a media attachment, stored separately from caption text.
- **Poll_Tier**: One of three adaptive polling intervals assigned to a watchlisted channel based on its current risk level: HIGH (30 s), MEDIUM (60 s), LOW/inactive (300 s or more).
- **Watchlist**: The `channels` table — the set of channels the Collector actively monitors.
- **ChannelScanResult**: The existing per-channel summary record produced by the Scanner.
- **ScanJob**: The existing scan-run record in the `scan_jobs` table.
- **Analyst**: An authenticated law-enforcement user interacting with the Frontend.

---

## Requirements

### Requirement 1: Seed Profile Management

**User Story:** As an Analyst, I want to manage search seeds as structured profiles so that I can track which seeds are productive, adjust their priority, and understand which seed discovered each channel.

#### Acceptance Criteria

1. THE System SHALL store each Seed_Profile as a database record containing: seed text (string, max 120 characters), threat_category (string referencing a lexicon category), language_region (string, e.g. "hi-IN"), intent_type (string, e.g. "drug_sale"), priority (integer 1–5), is_active (boolean), created_source (one of: manual, analyst_promoted, entity_pivot), created_at (timestamp), and updated_at (timestamp).
2. THE System SHALL enforce a unique constraint on the normalised seed text so that duplicate seed strings cannot be stored regardless of case or leading/trailing whitespace.
3. WHEN a Seed_Profile is created or updated, THE System SHALL generate all Query_Variants for that profile and store each variant in a linked `query_variants` table with a foreign key to the Seed_Profile.
4. THE System SHALL generate at minimum three classes of Query_Variant per Seed_Profile: (a) normalised spacing/punctuation variants, (b) hyphen-separated and space-separated interchanges where the seed contains two or more tokens, and (c) Devanagari-to-Latin transliteration variants and Latin-to-Devanagari back-transliteration variants for seeds in the "hi-IN" language_region.
5. WHEN generating Query_Variants, THE System SHALL enforce a maximum length of two whitespace-separated tokens per variant so that generated queries remain broad enough for Telegram's global search API.
6. THE System SHALL deduplicate Query_Variants across all Seed_Profiles and all prior scan runs: if an identical variant text already exists in `query_variants`, THE System SHALL record a reference to the existing record rather than creating a duplicate.
7. WHEN the Scanner or Discovery engine executes a query, THE System SHALL record the Query_Variant identifier (and therefore the parent Seed_Profile identifier) on every ChannelScanResult and Scan_Evidence row produced by that query execution.
8. THE Backend SHALL expose REST endpoints to create, read, update (seed text, priority, is_active, intent_type), and list Seed_Profiles and their Query_Variants.
9. WHEN an Analyst sets is_active to false on a Seed_Profile, THE System SHALL cease including that profile's Query_Variants in future scan and discovery runs without deleting any historical data.
10. THE System SHALL NOT automatically disable or modify a Seed_Profile based on performance metrics alone; only an Analyst action SHALL change is_active.

---

### Requirement 2: Query Variant Deduplication and Provenance

**User Story:** As an Analyst, I want every discovered channel traced back to the exact seed and variant that found it so that I can evaluate which seeds are productive without duplicating scan effort.

#### Acceptance Criteria

1. THE System SHALL maintain a `query_variant_executions` table recording: query_variant_id, scan_job_id (nullable), execution_timestamp, channels_found count, and channels_added count per execution.
2. WHEN the Scanner searches Telegram using a Query_Variant and discovers a channel, THE System SHALL write the query_variant_id to the resulting ChannelScanResult row in a `discovered_by_variant_id` column.
3. WHEN the same channel username is discovered in multiple scan runs, THE System SHALL record all discovery variant references and SHALL NOT overwrite the original discovering variant.
4. WHEN the Discovery engine auto-adds a channel to the Watchlist, THE System SHALL record the Query_Variant that triggered the addition in the Channel record's `discovery_variant_id` column.
5. THE Backend SHALL expose a read endpoint `GET /seeds/profiles/{profile_id}/provenance` that returns the list of channels discovered by all variants of that Seed_Profile, including scan job identifiers and timestamps.

---

### Requirement 3: Evidence-First Pivot Candidate Extraction

**User Story:** As an Analyst, I want the system to automatically surface public pivot candidates from high-risk channel messages so that I can review and promote credible leads without manually reading every message.

#### Acceptance Criteria

1. WHEN the Scanner processes a message whose classifier risk_level is HIGH or whose avg_score meets or exceeds the MEDIUM_RISK_THRESHOLD, THE System SHALL extract the following pivot candidate types from that message: t.me channel links, @handles, forwarded-public-channel source identifiers, and recurring payment/contact identifiers (phone, UPI, crypto wallet) that appear in two or more distinct messages within the same channel during the same scan job.
2. THE System SHALL store each extracted pivot as a Pivot_Candidate record containing: source_channel_username, source_scan_result_id (FK), candidate_type (channel_link, handle, payment_identifier, forwarded_source), candidate_value (string), status (default: pending), created_at, evaluated_at (nullable), evaluated_by (nullable), and notes (nullable).
3. THE System SHALL NOT create a Pivot_Candidate for any link or handle that resolves to a private channel, invite-only group, or any URL scheme other than `https://t.me/{username}` with a valid public username pattern.
4. THE System SHALL NOT auto-join, auto-fetch, or auto-score a Pivot_Candidate channel; it SHALL only queue the candidate for Analyst review.
5. WHEN an Analyst sets the status of a Pivot_Candidate to promoted, THE System SHALL create or upsert a Channel record for the candidate value and add it to the Watchlist with `is_active = true`.
6. WHEN an Analyst sets the status of a Pivot_Candidate to rejected, THE System SHALL record the rejection with reviewer and timestamp and SHALL NOT create a Watchlist entry for that candidate.
7. WHEN a Pivot_Candidate references a channel that is already in the Watchlist, THE System SHALL set its status to already_monitored and SHALL NOT create a duplicate Watchlist entry.
8. THE System SHALL deduplicate Pivot_Candidates by (candidate_value, source_channel_username) so that the same pivot appearing in multiple messages from the same channel produces exactly one Pivot_Candidate record.
9. WHEN a Pivot_Candidate originates from an entity_pivot (identifier shared across channels), THE System SHALL automatically set the created_source of any resulting Seed_Profile promotion to entity_pivot.
10. THE Backend SHALL expose REST endpoints: `GET /pivots/` (list with filters), `GET /pivots/{id}`, `PATCH /pivots/{id}` (update status and notes), and `GET /channels/{username}/pivots` (candidates sourced from a given channel).

---

### Requirement 4: Message-Level Scan Evidence Persistence

**User Story:** As an Analyst, I want individual flagged messages from scan jobs persisted in full so that I can review raw evidence, re-classify after lexicon updates, and produce message-level forensic exports.

#### Acceptance Criteria

1. THE System SHALL create a `scan_evidence` table with the following columns: id, scan_job_id (FK to scan_jobs), channel_scan_result_id (FK to channel_scan_results), channel_username (string), telegram_message_id (bigint), message_timestamp (datetime), raw_text (text, nullable), caption_text (text, nullable), ocr_text (text, nullable), normalised_text (text, nullable), classifier_score (float), risk_level (string), severity_tier (string), categories (text, JSON array), matched_terms (text, JSON array), extracted_identifiers (text, JSON array), seed_term (string), query_variant_id (FK nullable), media_path (text, nullable), media_hash (string, nullable), ocr_success (boolean, nullable), ocr_confidence (float, nullable), last_classified_at (datetime), disposition (string, nullable), disposition_notes (text, nullable), disposition_by (string, nullable), disposition_at (datetime, nullable).
2. THE System SHALL create a unique index on (channel_username, telegram_message_id) in `scan_evidence` so that the same Telegram message is never stored more than once regardless of how many scan jobs encounter it.
3. WHEN the Scanner processes a message whose risk_level is HIGH or MEDIUM, THE System SHALL write a Scan_Evidence record immediately after the ChannelScanResult summary is committed to the database.
4. WHEN a Scan_Evidence record already exists for a (channel_username, telegram_message_id) pair, THE System SHALL update the last_classified_at timestamp but SHALL NOT overwrite the original raw_text, caption_text, or ocr_text fields.
5. THE System SHALL store raw_text, caption_text, and ocr_text independently in Scan_Evidence; it SHALL NOT merge them before writing to the evidence record (merging is permitted only for Classifier input and Normaliser input).
6. THE System SHALL expose a re-classification endpoint `POST /scan/evidence/reclassify` that re-runs the Classifier on the normalised_text of all Scan_Evidence rows whose last_classified_at is older than a caller-supplied cutoff datetime, and updates classifier_score, risk_level, severity_tier, categories, and matched_terms in place.
7. THE Backend SHALL expose REST endpoints: `GET /scan/jobs/{job_id}/evidence` (paginated, with filters for risk_level, category, disposition), `GET /scan/evidence/{id}`, and `GET /channels/{username}/evidence` (all evidence rows for a channel across all scan jobs).
8. THE Backend SHALL include Scan_Evidence message counts (total, HIGH, MEDIUM, by category) in the response of `GET /scan/jobs/{job_id}`.
9. THE System SHALL create database indexes on scan_evidence: (scan_job_id), (channel_username), (risk_level), (last_classified_at), and (disposition).

---

### Requirement 5: Composite Channel Scoring

**User Story:** As an Analyst, I want an explainable multi-component channel risk score so that I can understand why a channel was ranked as high risk and audit the scoring decision.

#### Acceptance Criteria

1. THE System SHALL compute a Composite_Score for each channel processed during a scan job, replacing the existing simple `avg_score` field as the primary risk ranking signal.
2. THE System SHALL compute the following Score_Components and store each as an individual float value in a `channel_score_components` table linked to the ChannelScanResult: (a) max_message_score — the highest single-message classifier score from the scan window; (b) high_confidence_message_count — count of messages with classifier_score >= HIGH_RISK_THRESHOLD; (c) distinct_incident_count — count of distinct threat categories appearing in flagged messages; (d) recency_weight — a factor between 0.0 and 1.0 derived from the timestamp of the most recent high-risk message relative to the scan window; (e) identifier_density — ratio of messages containing at least one extracted identifier to total messages scanned; (f) valid_pivot_count — count of Pivot_Candidates extracted from this channel in the same scan job; (g) analyst_confirmation_signal — +1.0 if the channel has at least one Scan_Evidence row with disposition confirmed, -1.0 if all dispositions are benign, 0.0 otherwise.
3. THE System SHALL weight the Score_Components using the formula: Composite_Score = 0.30 * max_message_score + 0.20 * normalised(high_confidence_message_count) + 0.15 * normalised(distinct_incident_count) + 0.10 * recency_weight + 0.10 * identifier_density + 0.10 * normalised(valid_pivot_count) + 0.05 * analyst_confirmation_signal, where normalised() maps a count to [0.0, 1.0] using a configurable saturation cap per component.
4. THE System SHALL NOT promote a channel's risk_level to HIGH based on the Composite_Score when high_confidence_message_count is 0 and the score is driven purely by identifier_density and valid_pivot_count.
5. THE System SHALL store Composite_Score alongside all Score_Components in `channel_score_components` with an audit timestamp so that historical scoring decisions are reproducible.
6. THE Backend SHALL include the Composite_Score and all Score_Components in the `GET /scan/results/{result_id}` response payload under a `score_breakdown` key.
7. THE Frontend SHALL render a score explanation panel on the channel detail view, showing each Score_Component label, numeric value, and weight contribution as a horizontal bar chart.
8. THE System SHALL continue to populate the existing `avg_score` column in `channel_scan_results` for backward compatibility with clients that read that field.

---

### Requirement 6: Text and OCR Normalisation Pipeline

**User Story:** As an Analyst, I want all text to pass through a consistent normalisation pipeline before classification so that look-alike character substitutions, zero-width characters, and obfuscated spacing do not evade detection.

#### Acceptance Criteria

1. THE System SHALL implement a Normaliser module that accepts a raw text string and returns a normalised text string, applying the following transformations in order: (a) Unicode NFC normalisation; (b) removal of zero-width and invisible characters (U+200B–U+200F, U+00AD, U+2060, U+FEFF); (c) replacement of visually confusable Latin/Cyrillic/Greek look-alike characters with their ASCII equivalents; (d) lowercase conversion; (e) repeated-punctuation compression (three or more consecutive identical punctuation characters collapsed to two); (f) repeated-whitespace normalisation (any run of whitespace collapsed to a single space); (g) hyphen/space interchange for token variants (e.g. "drug-sale" and "drug sale" treated equivalently).
2. THE Normaliser SHALL accept an optional transliteration hook parameter; WHEN the hook is provided, THE Normaliser SHALL apply it after step (d) in the pipeline.
3. THE Normaliser SHALL preserve the original input string unchanged and return normalised output as a separate value; it SHALL NOT mutate the caller's input.
4. WHEN the Collector or Scanner classifies a message, THE System SHALL pass the input text through the Normaliser before invoking the Classifier.
5. WHEN OCR text is extracted from a media attachment, THE System SHALL store the raw OCR output in the ocr_text column of the Scan_Evidence or Message record before normalisation, and SHALL store the normalised result separately for classification input.
6. WHEN processing a media attachment, THE System SHALL apply the following staged media workflow: (a) check that the file extension indicates an image type (jpg, jpeg, png, webp, bmp) or that the MIME type is image/*; (b) IF the channel's current risk_tier is LOW and no prior HIGH-risk message exists in the same scan session, THEN THE System SHALL skip OCR and record ocr_success as null; (c) ELSE THE System SHALL run OCR and record ocr_success as true or false and ocr_confidence as the mean EasyOCR confidence score across all detected text boxes.
7. WHEN OCR fails for any reason, THE System SHALL log the failure at DEBUG level, set ocr_success to false in the evidence record, and continue processing without raising an exception.
8. THE Normaliser SHALL be importable as a standalone function (`from app.extractors.normaliser import normalise`) with no dependency on the database layer.

---

### Requirement 7: Analyst Feedback Loop and Disposition System

**User Story:** As an Analyst, I want to record structured verdicts on alerts, scan evidence, and pivot candidates so that my feedback drives measurable improvements in seed performance metrics.

#### Acceptance Criteria

1. THE System SHALL support the following Disposition values on Alert, Scan_Evidence, and Pivot_Candidate records: confirmed, benign, uncertain, duplicate, inaccessible.
2. WHEN an Analyst submits a Disposition for an Alert record, THE System SHALL write the disposition value, disposition_notes (optional string), disposition_by (reviewer identifier), and disposition_at (server timestamp) to the Alert record and SHALL NOT require the existing is_reviewed/reviewed_by mechanism to be replaced — both SHALL coexist.
3. WHEN an Analyst submits a Disposition for a Scan_Evidence record, THE System SHALL write the same four fields to that record.
4. WHEN an Analyst submits a Disposition for a Pivot_Candidate record, THE System SHALL update the status and notes fields consistent with the Disposition semantics (confirmed → promoted, benign → rejected, inaccessible → inaccessible).
5. THE System SHALL compute Feedback_Metrics for each Seed_Profile by aggregating dispositions across all Scan_Evidence rows and Pivot_Candidates whose query_variant_id traces back to that profile. Feedback_Metrics SHALL include: candidates_found, messages_processed, alerts_raised, confirmed_count, false_positive_count, precision (confirmed_count / (confirmed_count + false_positive_count) where the denominator > 0), yield (confirmed_count / candidates_found where candidates_found > 0).
6. THE Backend SHALL expose a read endpoint `GET /seeds/profiles/{profile_id}/metrics` returning the current Feedback_Metrics for that profile.
7. THE Backend SHALL expose a read endpoint `GET /seeds/metrics` returning Feedback_Metrics for all active Seed_Profiles, sorted by precision descending, for use in the Seed Performance UI panel.
8. THE System SHALL NOT automatically change is_active on any Seed_Profile as a result of Feedback_Metrics values; deactivation requires an explicit Analyst PATCH request.
9. THE System SHALL record a disposition_history log entry for each disposition change, preserving the previous value, so that overwrites are auditable.

---

### Requirement 8: REST API Completeness and Backward Compatibility

**User Story:** As a developer integrating with TeleMonitor, I want all existing API routes to continue working unchanged while new routes follow the same conventions so that existing clients do not break during the upgrade.

#### Acceptance Criteria

1. THE System SHALL preserve the following existing route prefixes and their documented response schemas without modification: `/alerts/`, `/channels/`, `/scan/`, `/graph/`, `/search/`, `/import/`, `/discovery/`.
2. THE Backend SHALL add the following new route prefixes: `/seeds/` (Seed_Profiles and Query_Variants), `/pivots/` (Pivot_Candidates), `/scan/evidence/` (Scan_Evidence), `/dispositions/` (batch disposition submission).
3. THE Backend SHALL accept all new list endpoints with the following standard query parameters: skip (integer, default 0), limit (integer, default 50, max 500), and where applicable: risk_level (string), category (string), disposition (string), seed_profile_id (integer), date_from (ISO-8601 datetime), date_to (ISO-8601 datetime).
4. THE Backend SHALL return HTTP 400 with a descriptive JSON error body WHEN a request includes an unrecognised disposition value or an invalid Seed_Profile created_source value.
5. THE Backend SHALL return HTTP 409 WHEN a request attempts to create a Seed_Profile with a normalised seed text that already exists in the database.
6. THE Backend SHALL return HTTP 422 WHEN a Query_Variant generation request would produce a variant exceeding two whitespace-separated tokens.
7. WHEN a Pivot_Candidate promotion request references a channel username that is already in the Watchlist, THE Backend SHALL return HTTP 200 with the existing Channel record rather than HTTP 201, and SHALL set the Pivot_Candidate status to already_monitored.

---

### Requirement 9: Frontend — Seed Performance Panel

**User Story:** As an Analyst, I want a dedicated Seed Performance panel in the UI so that I can see which seeds are finding real threats and which are generating noise.

#### Acceptance Criteria

1. THE Frontend SHALL add a "Seed Performance" page accessible from the main navigation sidebar.
2. THE Seed_Performance_Page SHALL display a sortable, filterable table of all Seed_Profiles, with columns: seed text, threat_category, priority, is_active, candidates_found, messages_processed, confirmed_count, false_positive_count, precision, yield, created_source.
3. WHEN an Analyst clicks a row in the Seed_Performance_Page table, THE Frontend SHALL display an inline edit form allowing modification of: priority, intent_type, threat_category, and is_active.
4. THE Seed_Performance_Page SHALL provide a text input to create a new Seed_Profile with the required fields and shall display inline validation errors returned by the Backend.
5. THE Seed_Performance_Page SHALL update Feedback_Metrics displayed in the table without a full page reload when an Analyst submits a new Disposition via the Analyst Review panel.

---

### Requirement 10: Frontend — Candidate and Pivot Queue Panel

**User Story:** As an Analyst, I want a dedicated pivot queue panel so that I can review, promote, and reject discovery candidates without navigating away from the investigation workflow.

#### Acceptance Criteria

1. THE Frontend SHALL add a "Pivot Queue" page accessible from the main navigation sidebar.
2. THE Pivot_Queue_Page SHALL display Pivot_Candidates in a paginated list, defaulting to status = pending, with filter controls for: candidate_type, source_channel_username, status, and date range.
3. WHEN an Analyst clicks a Pivot_Candidate row, THE Frontend SHALL display: the full candidate_value, the source channel username and risk level, up to three sample messages from which the pivot was extracted (if available), and action buttons for Promote, Reject, and Mark Inaccessible.
4. WHEN an Analyst promotes a Pivot_Candidate, THE Frontend SHALL call the Backend promotion endpoint, optimistically update the row status to promoted in the UI, and display a toast notification confirming the channel was added to the Watchlist.
5. WHEN an Analyst rejects a Pivot_Candidate, THE Frontend SHALL update the row status to rejected in the UI without removing the row from the list (allowing the filter to be used to view rejected items later).

---

### Requirement 11: Frontend — Message-Level Scan Evidence Panel

**User Story:** As an Analyst, I want to view the individual flagged messages found during a scan job so that I can assess the evidence quality for each channel before promoting it to the watchlist.

#### Acceptance Criteria

1. THE Frontend SHALL add a "Evidence" tab or sub-panel within the existing scan results view for each ChannelScanResult row.
2. THE Scan_Evidence_Panel SHALL display: telegram_message_id, message_timestamp, normalised_text (truncated at 400 characters with expand control), classifier_score, risk_level, categories, matched_terms, and extracted identifiers, and disposition status.
3. THE Scan_Evidence_Panel SHALL provide per-row Disposition controls (confirmed, benign, uncertain, duplicate) that submit via the Backend disposition endpoint and update the row display immediately.
4. WHERE ocr_text is non-null for a Scan_Evidence row, THE Scan_Evidence_Panel SHALL show an "OCR" badge alongside the message and display the raw OCR text in a collapsible section.
5. THE Scan_Evidence_Panel SHALL support filtering by: risk_level, category, disposition, and free-text search across normalised_text.

---

### Requirement 12: Frontend — Analyst Review and Disposition Panel

**User Story:** As an Analyst, I want a consolidated disposition panel across alerts, scan evidence, and pivot candidates so that I can work through a review queue efficiently.

#### Acceptance Criteria

1. THE Frontend SHALL update the existing Alerts page to include Disposition controls (confirmed, benign, uncertain, duplicate, inaccessible) alongside the existing "Mark Reviewed" action.
2. THE Frontend SHALL add a Disposition filter to the Alerts page allowing Analysts to view only unreviewed, confirmed, benign, or uncertain items.
3. THE Frontend SHALL display a Disposition summary badge on each Alert and Scan_Evidence row showing the current disposition value.
4. WHEN an Analyst submits a Disposition, THE Frontend SHALL send the disposition, notes, and reviewer fields to the Backend and SHALL reflect the change in the UI without requiring a page reload.

---

### Requirement 13: Frontend — Channel Score Explanation Panel

**User Story:** As an Analyst, I want to see a visual breakdown of how a channel's Composite_Score was calculated so that I can explain the risk rating to a supervising officer.

#### Acceptance Criteria

1. THE Frontend SHALL display a "Score Breakdown" section within the channel detail modal or page.
2. THE Score_Breakdown_Panel SHALL render each Score_Component as a labeled horizontal bar with the component's weighted contribution shown as a percentage of the total Composite_Score.
3. THE Score_Breakdown_Panel SHALL show a plain-language label for each component (e.g. "Highest single message score", "High-confidence message count", "Recent activity weight").
4. WHERE analyst_confirmation_signal is non-zero, THE Score_Breakdown_Panel SHALL display a note indicating that analyst feedback has influenced the score.

---

### Requirement 14: Adaptive Polling Tiers

**User Story:** As a system operator, I want channel polling frequency to adapt to risk level so that high-risk channels receive near-real-time coverage while low-risk channels do not exhaust Telegram rate limits.

#### Acceptance Criteria

1. THE Collector SHALL maintain three Poll_Tiers and assign each watchlisted channel to exactly one tier at the start of each poll cycle: HIGH_TIER (interval 30 seconds), MEDIUM_TIER (interval 60 seconds), LOW_TIER (interval 300 seconds or more as configured).
2. WHEN a channel's current risk_level is HIGH, THE Collector SHALL assign it to HIGH_TIER.
3. WHEN a channel's current risk_level is MEDIUM, THE Collector SHALL assign it to MEDIUM_TIER.
4. WHEN a channel's current risk_level is LOW or when is_active is false, THE Collector SHALL assign it to LOW_TIER.
5. THE System SHALL store the assigned poll_tier and last_poll_attempted_at on each Channel record so that the tier assignment is visible through the channels API.
6. WHEN re-evaluating a channel's risk_level, THE Collector SHALL use the channel's most recent Composite_Score (or ChannelScanResult risk_level if no Composite_Score is available) as the input.

---

### Requirement 15: FloodWait Handling and Error State Tracking

**User Story:** As a system operator, I want robust Telegram API error handling so that FloodWait bans do not silently halt collection for all channels.

#### Acceptance Criteria

1. WHEN the Collector or Scanner encounters a Telegram FloodWaitError, THE System SHALL pause only the affected channel or query and SHALL continue processing other channels or queries during the wait period.
2. THE System SHALL implement exponential backoff for FloodWaitErrors: the wait duration SHALL be max(fwe.seconds, minimum_backoff) * backoff_multiplier^retry_count, where minimum_backoff, backoff_multiplier, and max_retry_count are configurable via settings.
3. THE System SHALL record each FloodWaitError occurrence on the affected Channel record with an error_type, error_message, and occurred_at timestamp in a `channel_health_events` table.
4. WHEN a channel encounters three or more consecutive collection errors of any type within a 24-hour window, THE System SHALL set an error_state flag on the Channel record and reduce its polling frequency to LOW_TIER until an Analyst or the system clears the flag.
5. THE Backend SHALL expose a `GET /channels/{id}/health` endpoint returning: last_successful_collection_at, consecutive_error_count, error_state, and the most recent five health_events.
6. WHEN a channel is inaccessible (ChannelPrivateError, UsernameInvalidError, UsernameNotOccupiedError), THE System SHALL set is_active to false and SHALL record the inaccessibility reason in the channel_health_events table.
7. THE System SHALL track inaccessible channels separately from actively monitored channels in both the database and the channels list API endpoint, using a status field with values: active, paused, inaccessible, error.

---

### Requirement 16: OCR Gating and Media Workflow

**User Story:** As a system operator, I want OCR to run only when it is likely to yield useful intelligence so that system resources are not wasted on low-value media from low-risk channels.

#### Acceptance Criteria

1. THE Collector SHALL evaluate the following gate conditions before invoking EasyOCR on a media attachment: (a) the media file extension is one of jpg, jpeg, png, webp, or bmp, OR the MIME type begins with "image/"; (b) the channel's current poll_tier is HIGH_TIER or MEDIUM_TIER, OR the message text contains at least one matched lexicon term.
2. IF either gate condition in Requirement 16.1 is not met, THEN THE Collector SHALL skip OCR and set ocr_success to null on the evidence record without downloading the media file.
3. THE System SHALL record the reason for skipping OCR in a human-readable `ocr_skip_reason` column on the Scan_Evidence and Message records (values: not_image, low_risk_channel, no_text_signal, or null when OCR was attempted).
4. WHEN OCR is performed and succeeds, THE System SHALL retain the downloaded media file for channels in HIGH_TIER and SHALL delete it after classification for channels in MEDIUM_TIER and LOW_TIER unless the message risk_level is HIGH.

---

### Requirement 17: Database Indexing and PostgreSQL Migration Readiness

**User Story:** As a system operator, I want the database schema to perform efficiently at scale and to be preparable for PostgreSQL migration without data loss.

#### Acceptance Criteria

1. THE System SHALL create the following additional database indexes as part of the migration: `scan_evidence(scan_job_id)`, `scan_evidence(channel_username)`, `scan_evidence(risk_level)`, `scan_evidence(last_classified_at)`, `scan_evidence(disposition)`, `pivot_candidates(status)`, `pivot_candidates(source_channel_username)`, `seed_profiles(is_active)`, `query_variants(seed_profile_id)`, `channel_health_events(channel_id, occurred_at)`.
2. THE System SHALL continue supporting SQLite + aiosqlite as the default database configuration; all new tables and indexes SHALL be compatible with SQLite 3.35 or later.
3. THE System SHALL define all new ORM models using SQLAlchemy Core type declarations that are compatible with both SQLite and PostgreSQL without code changes — specifically: Boolean columns SHALL use SQLAlchemy Boolean type (not Integer), JSON columns SHALL use SQLAlchemy Text type with explicit JSON serialisation in application code, and all primary keys SHALL use Integer autoincrement.
4. THE System SHALL extend the existing `_migrate_sqlite_columns` function in `database.py` to add all new columns introduced by this feature to existing tables, applying them idempotently using `PRAGMA table_info` checks.
5. THE System SHALL provide a written migration note in the README documenting: the list of new tables, the new columns added to existing tables, the index additions, and any manual step required when migrating an existing SQLite database to a fresh PostgreSQL instance.

---

### Requirement 18: Unit and Integration Testing

**User Story:** As a developer, I want automated tests covering the core new logic so that regressions are caught before deployment.

#### Acceptance Criteria

1. THE System SHALL include unit tests for the Normaliser module covering: NFC normalisation of precomposed vs. decomposed Unicode, removal of each category of zero-width character, look-alike character replacement, repeated-punctuation compression, and hyphen/space interchange.
2. THE System SHALL include unit tests for Query_Variant generation covering: spacing variant generation, hyphen variant generation, transliteration round-trip (Latin → Devanagari → Latin) for a representative set of Hindi crime-domain terms, and the two-token maximum enforcement.
3. THE System SHALL include unit tests for the Composite_Score formula covering: a channel with zero high-confidence messages shall not receive a HIGH risk_level regardless of identifier_density or valid_pivot_count; a channel with analyst_confirmation_signal = -1.0 shall have a lower Composite_Score than an otherwise identical channel with signal = 0.0.
4. THE System SHALL include unit tests for the Pivot_Candidate eligibility filter covering: a t.me link with a valid public username is accepted; a t.me/joinchat/... invite link is rejected; a t.me link to a channel already in the Watchlist produces status already_monitored.
5. THE System SHALL include unit tests for Feedback_Metrics computation covering: precision returns 0.0 when confirmed_count and false_positive_count are both 0, and yield returns 0.0 when candidates_found is 0.
6. THE System SHALL include an integration test that runs a scan job against a mocked Telegram client, verifies that Scan_Evidence rows are created for HIGH and MEDIUM risk messages, and verifies that no Scan_Evidence row is created for LOW-risk messages.
7. FOR ALL valid normalised text strings, parsing then normalising then parsing SHALL produce an equivalent result (round-trip property).

---

### Requirement 19: Documentation Updates

**User Story:** As a developer onboarding to the project, I want updated documentation covering the new data model, configuration options, and operational workflow so that I can deploy and operate the system without reading source code.

#### Acceptance Criteria

1. THE System SHALL update the README to include a section describing the complete investigator workflow: seed profile creation → scan execution → evidence review → pivot promotion → watchlist monitoring → analyst disposition → feedback metrics.
2. THE System SHALL document all new configuration settings added to `Settings` (`.env`) with their types, defaults, valid ranges, and descriptions.
3. THE System SHALL include an updated data model diagram or table in the README listing all tables, their primary columns, and their foreign key relationships, including all tables introduced by this feature.
4. THE System SHALL include a section in the README documenting known operational constraints: Telegram rate limits, recommended maximum active seed profile count, OCR memory requirements, and the SQLite WAL mode recommendation for concurrent access.
5. THE System SHALL include a migration note section describing the exact steps to upgrade an existing deployment: which new tables to create, which columns to add to existing tables, and how to populate `query_variants` from the existing flat seed lists in `scanner.py` and `channel_discovery.py`.
