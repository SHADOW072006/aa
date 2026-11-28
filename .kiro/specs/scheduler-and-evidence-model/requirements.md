# Requirements Document

## Introduction

TeleMonitor currently polls Telegram channels through a sequential loop that sleeps between each channel for the full tier-interval. With 50 LOW-tier channels this creates a 15,000-second cycle, so channels are never actually polled on schedule. Additionally, the `scan_evidence` table uses a single upsert keyed on `(channel_username, telegram_message_id)`, which means re-scanning a message overwrites disposition data and breaks the audit trail. The continuous collector does not write to `scan_evidence` at all, so there is no link between continuous monitoring and the forensic evidence record.

This spec covers two related rebuilds:

1. **Scheduler rebuild** — replace the sequential sleep-per-channel loop with a priority scheduler that queries due channels every 10 seconds and runs up to 3 channels concurrently.
2. **Evidence model rebuild** — split `scan_evidence` into a canonical `evidence_messages` table (one row per real Telegram message, never deleted or overwritten) and an `evidence_observations` table (one row per classification event, always inserted). Both the collector and scanner write to this two-level model. Existing `scan_evidence` rows are migrated during `init_db()`.

All existing functionality (alerts, messages, channels, graph, PDFs, import, search) must continue working. The database layer uses the existing `_migrate_sqlite_columns` pattern — no Alembic.

## Glossary

- **Scheduler**: The component in `telegram_collector.py` that decides when to poll each channel and dispatches poll tasks.
- **Poll tier**: A three-value enum (`HIGH` / `MEDIUM` / `LOW`) already on the `Channel` model, controlling how frequently a channel is polled.
- **next_poll_at**: A new `DATETIME` column on `channels` recording the earliest wall-clock time the Scheduler may next poll that channel.
- **channel_status**: A string enum on `channels`: `active` | `inaccessible` | `paused` | `error_state`.
- **FloodWaitError**: A Telethon exception indicating the Telegram API has rate-limited the client. Carries a `seconds` field.
- **Exponential backoff**: A delay strategy where each retry waits at least double the previous wait, capped at a configured maximum.
- **EvidenceMessage**: A row in `evidence_messages` — the canonical, immutable record for one real Telegram message, identified by `(channel_username, telegram_message_id)`.
- **EvidenceObservation**: A row in `evidence_observations` — one classification event that references an `EvidenceMessage`. Never overwritten; a new row is always inserted.
- **Disposition**: An analyst verdict (`confirmed_threat` / `false_positive` / `under_review` / `archived`) attached to an `EvidenceMessage`. Once set, it survives re-scans.
- **source_type**: An enum on `EvidenceObservation` indicating which pipeline created it: `scheduled_scan` | `discovery` | `pivot` | `manual` | `continuous_monitor`.
- **Migration**: The one-time operation inside `init_db()` that moves existing `scan_evidence` rows into `evidence_messages` and `evidence_observations`.
- **Collector**: `TelegramCollector` in `app/collectors/telegram_collector.py`.
- **Scanner**: `app/scanners/scanner.py` or equivalent module that runs scan jobs.
- **Settings**: The Pydantic `Settings` class in `app/core/config.py`.
- **COLLECTOR_MAX_CONCURRENT**: New setting controlling how many channels the Scheduler polls simultaneously (default 3).
- **COLLECTOR_SCHEDULER_INTERVAL**: New setting for how often the Scheduler loop wakes to check for due channels, in seconds (default 10).
- **ERROR_BACKOFF_SECONDS**: New setting for how long a channel in `error_state` waits before the Scheduler retries it (default 3600).

---

## Requirements

### Requirement 1: Priority Scheduler Loop

**User Story:** As a monitoring operator, I want channels to be polled on their configured tier schedule regardless of how many channels are monitored, so that HIGH-tier channels are never delayed by a backlog of LOW-tier channels.

#### Acceptance Criteria

1. THE Scheduler SHALL wake every `COLLECTOR_SCHEDULER_INTERVAL` seconds (default 10) to check for due channels.
2. WHEN the Scheduler wakes, THE Scheduler SHALL query channels where `is_active = TRUE AND channel_status != 'suspended' AND next_poll_at <= now()`.
3. WHEN multiple channels are due simultaneously, THE Scheduler SHALL prioritise channels with `poll_tier = 'HIGH'` above `poll_tier = 'MEDIUM'` above `poll_tier = 'LOW'`.
4. THE Scheduler SHALL dispatch at most `COLLECTOR_MAX_CONCURRENT` channel-poll tasks concurrently (default 3).
5. WHEN a channel-poll task completes successfully, THE Scheduler SHALL set `next_poll_at = now() + tier_interval` for that channel, where `tier_interval` is `POLL_INTERVAL_HIGH`, `POLL_INTERVAL_MEDIUM`, or `POLL_INTERVAL_LOW` depending on the channel's `poll_tier`.
6. WHEN no channels are due, THE Scheduler SHALL sleep until the next wake interval without polling any channel.
7. THE Settings SHALL include `COLLECTOR_MAX_CONCURRENT: int = 3` and `COLLECTOR_SCHEDULER_INTERVAL: int = 10`.
8. THE legacy `POLL_INTERVAL_SECONDS` setting SHALL be retained in Settings for backwards compatibility but SHALL NOT be used by the new Scheduler loop.

---

### Requirement 2: next_poll_at Column

**User Story:** As a monitoring operator, I want each channel to record when it should next be polled, so that the Scheduler can efficiently query only due channels without scanning all rows on every wake cycle.

#### Acceptance Criteria

1. THE Database SHALL add a nullable `next_poll_at DATETIME` column to the `channels` table.
2. WHEN a new channel is created with no `next_poll_at` value, THE Scheduler SHALL treat `next_poll_at = NULL` as immediately due (equivalent to `next_poll_at <= now()`).
3. WHEN a channel-poll task completes successfully, THE Scheduler SHALL update `next_poll_at` to `now() + tier_interval` for that channel.
4. WHEN a `PATCH /channels/{id}/poll-tier` request updates a channel's poll tier, THE API SHALL also reset `next_poll_at` to `NULL` so the channel is polled on its next Scheduler wake.
5. THE `GET /channels/` response SHALL include `next_poll_at` and `channel_status` for every channel.

---

### Requirement 3: FloodWait Backoff

**User Story:** As a monitoring operator, I want Telegram rate-limit errors to defer the affected channel with exponential backoff, so that the Scheduler can keep polling other channels without being blocked.

#### Acceptance Criteria

1. WHEN a `FloodWaitError` is received for a channel, THE Scheduler SHALL set `next_poll_at = now() + max(flood_wait_seconds, current_backoff)` for that channel rather than blocking the main Scheduler loop.
2. WHEN a `FloodWaitError` is received for a channel, THE Scheduler SHALL record a `flood_wait` health event in `channel_health_events`.
3. WHEN a `FloodWaitError` is received and the calculated backoff would exceed `MAX_BACKOFF_SECONDS` (default 300), THE Scheduler SHALL cap `next_poll_at` at `now() + MAX_BACKOFF_SECONDS`.
4. WHEN a channel-poll task succeeds after a previous `FloodWaitError`, THE Scheduler SHALL reset the channel's backoff counter to the initial value.

---

### Requirement 4: Error State Management

**User Story:** As a monitoring operator, I want channels that repeatedly fail to be automatically suspended from active polling, so that transient infrastructure errors do not flood health event logs or block healthy channels.

#### Acceptance Criteria

1. WHEN a channel-poll task fails with a non-FloodWait error, THE Scheduler SHALL increment `consecutive_error_count` for that channel.
2. WHEN `consecutive_error_count` reaches `ERROR_STATE_THRESHOLD` (default 3) or above, THE Scheduler SHALL set `channel_status = 'error_state'` for that channel.
3. WHEN `channel_status = 'error_state'`, THE Scheduler SHALL set `next_poll_at = now() + ERROR_BACKOFF_SECONDS` (new setting, default 3600) rather than the normal tier interval.
4. WHEN a channel-poll task succeeds, THE Scheduler SHALL reset `consecutive_error_count` to 0 and set `channel_status = 'active'`.
5. WHEN a `ChannelPrivateError`, `UsernameInvalidError`, or `UsernameNotOccupiedError` is received, THE Scheduler SHALL set `channel_status = 'inaccessible'` and record a health event.
6. THE Settings SHALL include `ERROR_BACKOFF_SECONDS: int = 3600`.

---

### Requirement 5: Concurrency Isolation

**User Story:** As a monitoring operator, I want discovery runs, manual scans, and pivot evaluations to run in separate async tasks from the monitoring loop, so that a long-running scan cannot delay scheduled channel polls.

#### Acceptance Criteria

1. THE Scheduler loop SHALL run in its own `asyncio.Task` and SHALL NOT await discovery, scanner, or pivot coroutines directly.
2. WHEN a discovery or manual scan is triggered via the API, THE System SHALL launch it as a separate `asyncio.Task` that does not block the Scheduler loop.
3. WHEN the Scheduler's concurrent-task limit is reached, THE Scheduler SHALL defer remaining due channels to the next wake interval rather than queuing them inside the current iteration.

---

### Requirement 6: evidence_messages Table (Canonical Level)

**User Story:** As a forensic analyst, I want a single authoritative record per Telegram message that is never deleted or overwritten, so that disposition decisions and original message content are always preserved regardless of how many times a message is re-scanned.

#### Acceptance Criteria

1. THE Database SHALL create an `evidence_messages` table with a unique constraint on `(channel_username, telegram_message_id)`.
2. THE `evidence_messages` table SHALL store: `channel_username`, `telegram_message_id`, `message_timestamp`, `raw_text`, `caption_text`, `ocr_text`, `normalised_text`, `extracted_identifiers` (JSON text), `media_path`, `media_hash`, `ocr_outcome` (enum values: `not_applicable` / `skipped` / `success` / `failed`), `ocr_skip_reason`, `first_seen_at`, `last_seen_at`.
3. THE `evidence_messages` table SHALL store disposition fields: `disposition`, `disposition_notes`, `disposition_by`, `disposition_at`.
4. WHEN the System receives a message already present in `evidence_messages`, THE System SHALL update `last_seen_at` and SHALL NOT modify `first_seen_at`, `disposition`, `disposition_notes`, `disposition_by`, or `disposition_at`.
5. THE System SHALL NOT delete rows from `evidence_messages`.

---

### Requirement 7: evidence_observations Table (Per-Processing-Event Level)

**User Story:** As a forensic analyst, I want every time a message is classified or processed to produce a new audit row, so that I can reconstruct the full classification history and attribution for any message.

#### Acceptance Criteria

1. THE Database SHALL create an `evidence_observations` table with a foreign key `evidence_message_id` referencing `evidence_messages.id`.
2. THE `evidence_observations` table SHALL store: `scan_job_id` (nullable FK to `scan_jobs.id`), `channel_scan_result_id` (nullable FK to `channel_scan_results.id`), `seed_profile_id` (nullable FK to `seed_profiles.id`), `query_variant_id` (nullable FK to `query_variants.id`), `source_type` (enum: `scheduled_scan` / `discovery` / `pivot` / `manual` / `continuous_monitor`), `classifier_version` (string), `score` (float), `risk_level` (string), `severity_tier` (string), `categories` (JSON text), `matched_terms` (JSON text), `classified_at` (datetime).
3. WHEN the System processes a message, THE System SHALL INSERT a new row into `evidence_observations` rather than updating an existing one.
4. WHEN the System needs the current classification of a message, THE System SHALL use the `evidence_observations` row with the latest `classified_at` for that `evidence_message_id`.

---

### Requirement 8: Collector Writes to Evidence Tables

**User Story:** As a forensic analyst, I want messages detected by the continuous monitoring collector to appear in the evidence audit trail, so that there is a single query path for all message classifications regardless of source.

#### Acceptance Criteria

1. WHEN the Collector processes a message and generates an alert, THE Collector SHALL upsert a row into `evidence_messages` for that `(channel_username, telegram_message_id)` pair.
2. WHEN the Collector creates or updates an `evidence_messages` row, THE Collector SHALL insert a new row into `evidence_observations` with `source_type = 'continuous_monitor'`.
3. WHEN the Collector creates an `evidence_observations` row, THE Collector SHALL populate `score`, `risk_level`, `categories`, and `matched_terms` from the classifier result.
4. WHEN the Collector creates an `evidence_observations` row, THE Collector SHALL leave `scan_job_id`, `channel_scan_result_id`, `seed_profile_id`, and `query_variant_id` as NULL.

---

### Requirement 9: Scanner Writes to Evidence Tables

**User Story:** As a forensic analyst, I want scan job results to appear in the evidence audit trail with full attribution to the scan job, query variant, and seed profile, so that I can filter evidence by investigation context.

#### Acceptance Criteria

1. WHEN the Scanner processes a message during a scan job, THE Scanner SHALL upsert a row into `evidence_messages` for that `(channel_username, telegram_message_id)` pair.
2. WHEN the Scanner creates or updates an `evidence_messages` row, THE Scanner SHALL insert a new row into `evidence_observations` with `source_type = 'scheduled_scan'` and the correct `scan_job_id`, `query_variant_id`, and `seed_profile_id`.
3. WHEN the Scanner creates an `evidence_observations` row, THE Scanner SHALL populate `score`, `risk_level`, `severity_tier`, `categories`, and `matched_terms` from the classifier result.
4. WHEN a scan job re-processes a message that already has an `evidence_messages` row, THE Scanner SHALL NOT modify the `disposition`, `disposition_notes`, `disposition_by`, or `disposition_at` fields on the existing `evidence_messages` row.

---

### Requirement 10: Disposition Preservation

**User Story:** As a forensic analyst, I want analyst disposition decisions to survive re-scans and re-classifications, so that I do not lose investigation context when the system re-processes messages it has already reviewed.

#### Acceptance Criteria

1. WHEN a disposition is set on an `evidence_messages` row via `POST /evidence/messages/{id}/disposition`, THE System SHALL record the disposition on the `evidence_messages` row and insert a row into `disposition_history` with `target_type = 'evidence_message'`.
2. WHEN any pipeline (Collector or Scanner) processes a message with an existing `evidence_messages` row that has a non-null `disposition`, THE System SHALL NOT overwrite the `disposition`, `disposition_notes`, `disposition_by`, or `disposition_at` fields.
3. WHEN a disposition is updated, THE System SHALL record the previous disposition value in `disposition_history`.

---

### Requirement 11: Evidence API

**User Story:** As a forensic analyst, I want API endpoints to query canonical evidence messages and their observation history, so that I can review all classifications for a message in one place.

#### Acceptance Criteria

1. THE API SHALL expose `GET /evidence/messages/` with optional query parameters: `channel` (string), `date_from` (ISO datetime), `date_to` (ISO datetime), `disposition` (string), `risk_level` (string).
2. THE `GET /evidence/messages/` response SHALL return a paginated list of `evidence_messages` rows with the latest `risk_level` from the most recent `evidence_observations` row.
3. THE API SHALL expose `GET /evidence/messages/{id}` returning the full `evidence_messages` row plus the most recent `evidence_observations` row.
4. THE API SHALL expose `GET /evidence/messages/{id}/observations` returning all `evidence_observations` rows for the given `evidence_message_id`, ordered by `classified_at` descending.
5. THE API SHALL expose `POST /evidence/messages/{id}/disposition` accepting a JSON body with `disposition`, `disposition_notes`, and `disposition_by`, and writing the values to `evidence_messages` and `disposition_history`.
6. IF an `evidence_messages` row with the given `{id}` does not exist, THEN THE API SHALL return HTTP 404.

---

### Requirement 12: Migration of Existing scan_evidence Rows

**User Story:** As a monitoring operator, I want existing `scan_evidence` rows to be automatically migrated into the new evidence tables on first startup, so that historical evidence data is not lost and the system works without manual intervention.

#### Acceptance Criteria

1. WHEN `init_db()` runs, THE Database SHALL create `evidence_messages` and `evidence_observations` tables if they do not exist.
2. WHEN `init_db()` runs, THE Database SHALL migrate each existing `scan_evidence` row that has no matching row in `evidence_messages` into `evidence_messages` (mapping `channel_username`, `telegram_message_id`, `message_timestamp`, `raw_text`, `caption_text`, `ocr_text`, `normalised_text`, `extracted_identifiers`, `media_path`, `media_hash`, `ocr_skip_reason`, `disposition`, `disposition_notes`, `disposition_by`, `disposition_at`).
3. WHEN migrating a `scan_evidence` row, THE Database SHALL set `first_seen_at = last_classified_at` and `last_seen_at = last_classified_at` on the new `evidence_messages` row.
4. WHEN migrating a `scan_evidence` row, THE Database SHALL insert a corresponding `evidence_observations` row with `source_type = 'scheduled_scan'`, `scan_job_id`, `channel_scan_result_id`, `query_variant_id`, `score = classifier_score`, `risk_level`, `severity_tier`, `categories`, `matched_terms`, `classified_at = last_classified_at`.
5. THE Migration SHALL be idempotent — running `init_db()` multiple times SHALL NOT create duplicate rows in `evidence_messages` or `evidence_observations`.
6. THE `scan_evidence` table SHALL be retained in the database during transition and SHALL NOT be dropped by `init_db()`.
7. THE Migration SHALL NOT modify or delete existing rows in `channels`, `messages`, `alerts`, or `identifiers`.

---

### Requirement 13: Schema Migration (No Alembic)

**User Story:** As a backend developer, I want all schema changes applied automatically on startup using the existing `_migrate_sqlite_columns` pattern, so that upgrading a running instance requires no manual SQL execution.

#### Acceptance Criteria

1. THE `_migrate_sqlite_columns` function SHALL add `next_poll_at DATETIME` to the `channels` table if not present.
2. THE `_migrate_sqlite_columns` function SHALL add `ERROR_BACKOFF_SECONDS`-related schema changes to `channels` as needed.
3. THE `init_db()` function SHALL create `evidence_messages` and `evidence_observations` using `CREATE TABLE IF NOT EXISTS` semantics (via `Base.metadata.create_all`).
4. ALL schema changes SHALL be compatible with both SQLite (via aiosqlite) and PostgreSQL.
5. WHEN any `ALTER TABLE` statement fails because the column already exists, THE System SHALL log a warning and continue without raising an exception.

