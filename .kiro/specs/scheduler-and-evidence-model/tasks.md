# Implementation Plan: Scheduler Rebuild and Evidence Model

## Overview

Twenty-three ordered tasks that convert the sequential sleep-per-channel collector loop into a priority scheduler, replace the single-upsert `scan_evidence` table with a two-level `evidence_messages` / `evidence_observations` model, migrate existing data, and expose a new `/evidence/v2/` API. Each task touches one file or one tightly scoped change. The existing `scan_evidence` table, all alerts/channels/messages tables, and the existing `/evidence/` router are left intact.

---

## Tasks

- [x] 1. Add new settings to `app/core/config.py`
  - Add four fields to the `Settings` class: `COLLECTOR_MAX_CONCURRENT: int = 3`, `COLLECTOR_SCHEDULER_INTERVAL: int = 10`, `MAX_BACKOFF_SECONDS: int = 3600`, `ERROR_BACKOFF_SECONDS: int = 3600`.
  - Confirm that existing fields (`POLL_INTERVAL_SECONDS`, `MIN_BACKOFF`, `ERROR_STATE_THRESHOLD`, etc.) are untouched.
  - _Requirements: 1.7, 4.6, 13.2_

- [x] 2. Add `EvidenceMessage` and `EvidenceObservation` ORM models to `app/db/models.py`
  - Add `EvidenceMessage` class with all columns from the design table (including `first_seen_at`, `last_seen_at`, disposition fields), a `UNIQUE(channel_username, telegram_message_id)` constraint, and indexes on `channel_username`, `disposition`, and `first_seen_at`.
  - Add `EvidenceObservation` class with all columns from the design table, FK to `evidence_messages.id`, and indexes on `evidence_message_id` and `classified_at`.
  - Do NOT remove `ScanEvidence`.
  - _Requirements: 6.1, 6.2, 6.3, 7.1, 7.2_

- [x] 3. Add `next_poll_at` column migration to `app/db/database.py`
  - In `_migrate_sqlite_columns`, add `("next_poll_at", "DATETIME")` to the `new_channel_cols_v2` list (or equivalent guard block), following the same `PRAGMA table_info` / `ALTER TABLE` pattern already used for the other channel columns.
  - _Requirements: 2.1, 13.1_

- [x] 4. Add evidence table migration SQL to `app/db/database.py`
  - After `Base.metadata.create_all(conn)` in `init_db()`, run the two idempotent `INSERT … WHERE NOT EXISTS` statements from the design to migrate `scan_evidence` rows into `evidence_messages` and `evidence_observations`.
  - Wrap each statement in a try/except that logs a WARNING on failure and continues — do not abort startup.
  - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 13.3_

- [x] 5. Add `get_due_channels` CRUD function to `app/db/crud.py`
  - Implement `async def get_due_channels(db: AsyncSession, now: datetime, limit: int) -> Sequence[Channel]` using the SQL query from the design: `is_active = True`, `channel_status NOT IN ('inaccessible', 'paused', 'suspended')`, `(next_poll_at IS NULL OR next_poll_at <= now)`, ordered by tier priority then `next_poll_at ASC NULLS FIRST`, limited to `limit` rows.
  - _Requirements: 1.2, 1.3, 2.2_

- [x] 6. Add `upsert_evidence_message` CRUD function to `app/db/crud.py`
  - Implement `async def upsert_evidence_message(db, channel_username, telegram_message_id, **fields) -> EvidenceMessage`.
  - On create: set `first_seen_at = now`, `last_seen_at = now`, persist all supplied fields.
  - On update: set `last_seen_at = now`; update mutable content fields; never overwrite `first_seen_at` or any disposition field (`disposition`, `disposition_notes`, `disposition_by`, `disposition_at`) unless the caller explicitly passes that kwarg.
  - _Requirements: 6.4, 10.2_

- [x] 7. Add `insert_evidence_observation` and read CRUD functions to `app/db/crud.py`
  - Implement `async def insert_evidence_observation(db, evidence_message_id, **fields) -> EvidenceObservation` — always INSERT, never update.
  - Implement `async def get_evidence_message(db, evidence_message_id: int) -> EvidenceMessage | None`.
  - Implement `async def get_observations_for_message(db, evidence_message_id: int) -> Sequence[EvidenceObservation]` ordered by `classified_at DESC`.
  - _Requirements: 7.3, 7.4, 11.3, 11.4_

- [x] 8. Add `list_evidence_messages` CRUD function to `app/db/crud.py`
  - Implement `async def list_evidence_messages(db, channel_username=None, risk_level=None, disposition=None, date_from=None, date_to=None, skip=0, limit=100) -> Sequence[EvidenceMessage]`.
  - Apply each filter only when its argument is not None.
  - For `risk_level` filtering, join with the latest `evidence_observations` row per message (subquery on max `classified_at`).
  - _Requirements: 11.1, 11.2_

- [x] 9. Add `set_evidence_message_disposition` CRUD function to `app/db/crud.py`
  - Implement `async def set_evidence_message_disposition(db, evidence_message_id, disposition, notes, changed_by) -> EvidenceMessage | None`.
  - Update `disposition`, `disposition_notes`, `disposition_by`, `disposition_at` on the `evidence_messages` row.
  - Insert a row into `disposition_history` with `target_type='evidence_message'` and the previous disposition value.
  - Return the updated `EvidenceMessage`, or `None` if the row does not exist.
  - _Requirements: 10.1, 10.3, 11.5_

- [x] 10. Create `app/collectors/scheduler.py` with `ChannelScheduler` class
  - Implement `ChannelScheduler.__init__(self, client: TelegramClient)`: store client, create `asyncio.Semaphore(settings.COLLECTOR_MAX_CONCURRENT)`, initialise `self._running_ids: set[int] = set()`.
  - Implement `run_forever()`: loop calling `_tick()` then `asyncio.sleep(settings.COLLECTOR_SCHEDULER_INTERVAL)`, with broad exception logging so a single tick failure does not terminate the loop.
  - Implement `_tick()`: compute available slots, call `get_due_channels`, skip channels in `self._running_ids`, dispatch up to `slots` tasks via `asyncio.create_task(self._collect_one(ch))`.
  - _Requirements: 1.1, 1.4, 1.6, 5.1, 5.3_

- [x] 11. Implement `ChannelScheduler._collect_one` in `app/collectors/scheduler.py`
  - Import `TelegramCollector` or access via `get_collector()`. Call `collector._collect_channel(channel_row)`.
  - Wrap in `try/except` with `finally: self._running_ids.discard(channel_row.id)`.
  - On success: `async with get_session() as db:` update `channel.next_poll_at = now + tier_interval`, `channel.consecutive_error_count = 0`, `channel.channel_status = 'active'`.
  - On `FloodWaitError`: set `channel.next_poll_at = now + min(e.seconds, settings.MAX_BACKOFF_SECONDS)`, call `record_health_event(db, channel_row.id, event_type='flood_wait', ...)`.
  - On `ChannelPrivateError` / `UsernameInvalidError` / `UsernameNotOccupiedError`: set `channel.channel_status = 'inaccessible'`, `channel.next_poll_at = now + settings.ERROR_BACKOFF_SECONDS`, record health event.
  - On any other exception: increment `consecutive_error_count`; if count >= `settings.ERROR_STATE_THRESHOLD`, set `channel_status = 'error_state'` and `next_poll_at = now + settings.ERROR_BACKOFF_SECONDS`; record health event.
  - _Requirements: 1.5, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5_

- [x] 12. Remove `run_forever` from `TelegramCollector` in `app/collectors/telegram_collector.py`
  - Delete the `run_forever()` method and the `_poll_all_channels()` method from `TelegramCollector`. Keep `start()`, `stop()`, `client` property, `_collect_channel()`, `_collect_channel_with_backoff()`, and `_process_message()`.
  - `get_collector()` remains unchanged.
  - _Requirements: 1.1, 5.1_

- [x] 13. Add evidence writes to `_process_message` in `app/collectors/telegram_collector.py`
  - After `await save_alert(db, alert)` (and outside the `if result.is_flagged` guard — write for all messages that pass classification, not only flagged ones), add:
    - `upsert_evidence_message(db, channel_username=channel_row.username, telegram_message_id=tg_msg.id, message_timestamp=tg_msg.date, raw_text=text, ocr_text=ocr_text, normalised_text=combined, ocr_outcome=..., ocr_skip_reason=ocr_skip_reason)`
    - `insert_evidence_observation(db, evidence_message_id=ev_msg.id, source_type='continuous_monitor', score=result.score, risk_level=result.risk_level, severity_tier=getattr(result, 'severity_tier', 'LOW'), categories=json.dumps(result.categories), matched_terms=json.dumps(result.matched_terms))`
  - Import `upsert_evidence_message`, `insert_evidence_observation` from `app.db.crud`.
  - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [x] 14. Replace `upsert_scan_evidence` calls in `app/collectors/scanner.py`
  - In `_scan_one_channel`, replace each `upsert_scan_evidence(db, ...)` call with the two-step pattern:
    - `ev_msg = await upsert_evidence_message(db, channel_username=username, telegram_message_id=message_id, ...)`
    - `await insert_evidence_observation(db, evidence_message_id=ev_msg.id, source_type='scheduled_scan', scan_job_id=job_id, channel_scan_result_id=channel_scan_result_id, query_variant_id=query_variant_id, ...)`
  - Remove the import of `upsert_scan_evidence`. Import `upsert_evidence_message`, `insert_evidence_observation` from `app.db.crud`.
  - _Requirements: 9.1, 9.2, 9.3, 9.4_

- [x] 15. Update `app/main.py` to use `ChannelScheduler`
  - Import `ChannelScheduler` from `app.collectors.scheduler`.
  - In `lifespan`: replace `asyncio.create_task(collector.run_forever())` with `asyncio.create_task(ChannelScheduler(collector.client).run_forever())`.
  - Ensure `collector.start()` is awaited before creating the scheduler task (move it before the `create_task` call if not already there).
  - Keep the discovery task unchanged.
  - _Requirements: 1.1, 5.1, 5.2_

- [x] 16. Add `next_poll_at` and `channel_status` to `ChannelOut` schema and `PATCH poll-tier` reset in `app/api/channels.py`
  - Add `next_poll_at: Optional[datetime]` and `channel_status: Optional[str]` to the `ChannelOut` Pydantic model.
  - Add a `PATCH /channels/{id}/poll-tier` endpoint that accepts `{"poll_tier": "HIGH"|"MEDIUM"|"LOW"}` and sets `channel.poll_tier = new_tier`, `channel.next_poll_at = None` on the DB row.
  - _Requirements: 2.4, 2.5_

- [x] 17. Create `app/api/evidence_v2.py` with list and detail endpoints
  - Implement Pydantic response models `EvidenceMessageOut` and `EvidenceObservationOut` matching the ORM models.
  - `GET /evidence/v2/messages/`: call `list_evidence_messages(db, channel_username, risk_level, disposition, date_from, date_to, skip, limit)`, return list.
  - `GET /evidence/v2/messages/{id}`: call `get_evidence_message(db, id)`, raise HTTP 404 if None, return message + latest observation (first from `get_observations_for_message`).
  - `GET /evidence/v2/messages/{id}/observations`: call `get_observations_for_message(db, id)`, raise HTTP 404 if no message, return list.
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.6_

- [x] 18. Add disposition endpoint to `app/api/evidence_v2.py`
  - Implement `POST /evidence/v2/messages/{id}/disposition` accepting `DispositionBody(disposition, disposition_notes, disposition_by)`.
  - Call `set_evidence_message_disposition(db, id, ...)`.
  - Raise HTTP 404 if return is None.
  - Validate that `disposition` is one of `confirmed_threat`, `false_positive`, `under_review`, `archived`; return HTTP 422 otherwise.
  - _Requirements: 10.1, 10.3, 11.5, 11.6_

- [x] 19. Register `evidence_v2` router in `app/main.py`
  - Import `router as evidence_v2_router` from `app.api.evidence_v2`.
  - Add `app.include_router(evidence_v2_router)` after the existing `evidence_router` inclusion.
  - _Requirements: 11.1_

- [x] 20. Checkpoint — run tests and verify baseline
  - Run `pytest backend/tests/ -x -q` (without watch mode).
  - Confirm all previously passing tests still pass with no regressions in channels, alerts, scan, evidence, and discovery endpoints.
  - Fix any import errors introduced by the `run_forever` removal or model additions.
  - Ensure all tests pass before continuing. Ask the user if questions arise.

- [x] 21. Write property tests in `backend/tests/test_scheduler_evidence_properties.py`
  - [ ]* 21.1 Write property test for scheduler query filter correctness (Property 1)
    - Generate random sets of `Channel`-like objects varying `is_active`, `channel_status`, `next_poll_at`; call `get_due_channels`; verify only eligible rows are returned.
    - **Property 1: Scheduler query filters correctly**
    - **Validates: Requirements 1.2, 2.2**
  - [ ]* 21.2 Write property test for tier priority ordering (Property 2)
    - Generate random lists of due channels with mixed tiers; verify returned order is HIGH → MEDIUM → LOW.
    - **Property 2: Scheduler query respects tier priority**
    - **Validates: Requirements 1.3**
  - [ ]* 21.3 Write property test for FloodWait backoff cap (Property 3)
    - Generate random `flood_wait_seconds` integers (1 to 10000); verify computed `next_poll_at` offset <= `MAX_BACKOFF_SECONDS`.
    - **Property 3: FloodWait backoff is capped**
    - **Validates: Requirements 3.1, 3.3**
  - [ ]* 21.4 Write property test for error counter and error_state threshold (Property 4)
    - Generate random sequences of N failures; verify `consecutive_error_count == N` and `channel_status == 'error_state'` iff N >= threshold.
    - **Property 4: Error counter increments and threshold triggers error_state**
    - **Validates: Requirements 4.1, 4.2**
  - [ ]* 21.5 Write property test for success resetting error state (Property 5)
    - Generate channels with arbitrary `consecutive_error_count` and `channel_status = 'error_state'`; simulate a success; verify count is 0 and status is `'active'`.
    - **Property 5: Success resets error state**
    - **Validates: Requirements 4.4, 3.4**
  - [ ]* 21.6 Write property test for upsert_evidence_message preserving first_seen_at and disposition (Property 6)
    - Generate random evidence message field sets; call upsert twice with second call including updated content and a disposition; verify `first_seen_at` unchanged and disposition from first call (if set) is not overwritten.
    - **Property 6: upsert_evidence_message preserves first_seen_at and disposition**
    - **Validates: Requirements 6.4, 10.2**
  - [ ]* 21.7 Write property test for insert_evidence_observation always adds rows (Property 7)
    - Generate N random observation field sets for the same `evidence_message_id`; call `insert_evidence_observation` N times; verify row count equals N.
    - **Property 7: insert_evidence_observation always adds a new row**
    - **Validates: Requirements 7.3**
  - [ ]* 21.8 Write property test for list_evidence_messages filter correctness (Property 8)
    - Generate random databases of `EvidenceMessage` rows with varying channel, disposition, date, and risk_level; verify every returned row satisfies all active filters and no matching row is missing.
    - **Property 8: Evidence list filter correctness**
    - **Validates: Requirements 11.1, 11.2**
  - [ ]* 21.9 Write property test for observations ordering (Property 9)
    - Generate random lists of observations with arbitrary `classified_at` values; verify `get_observations_for_message` returns them in descending order.
    - **Property 9: Observations returned in descending order**
    - **Validates: Requirements 11.4**
  - [ ]* 21.10 Write property test for migration idempotency (Property 10)
    - Seed an in-memory SQLite database with N random `scan_evidence` rows; run migration SQL twice; verify `evidence_messages` and `evidence_observations` row counts are identical after both runs.
    - **Property 10: Migration idempotency**
    - **Validates: Requirements 12.5**

- [x] 22. Write example/unit tests in `backend/tests/test_scheduler_evidence_examples.py`
  - [ ]* 22.1 Test that `_migrate_sqlite_columns` adds `next_poll_at` to an existing in-memory SQLite `channels` table.
    - _Requirements: 2.1, 13.1_
  - [ ]* 22.2 Test that `GET /channels/` response includes `next_poll_at` and `channel_status` fields.
    - _Requirements: 2.5_
  - [ ]* 22.3 Test that `PATCH /channels/{id}/poll-tier` sets `next_poll_at = None`.
    - _Requirements: 2.4_
  - [ ]* 22.4 Test that `ChannelScheduler._tick()` creates no tasks when `get_due_channels` returns empty.
    - _Requirements: 1.6_
  - [ ]* 22.5 Test that a `FloodWaitError` during `_collect_one` records a `flood_wait` health event.
    - _Requirements: 3.2_
  - [ ]* 22.6 Test that a `ChannelPrivateError` during `_collect_one` sets `channel_status = 'inaccessible'`.
    - _Requirements: 4.5_
  - [ ]* 22.7 Test that `GET /evidence/v2/messages/{id}` returns HTTP 404 for a non-existent id.
    - _Requirements: 11.6_
  - [ ]* 22.8 Test that `POST /evidence/v2/messages/{id}/disposition` inserts a row in `disposition_history`.
    - _Requirements: 10.1, 10.3_
  - [ ]* 22.9 Test that migration SQL populates `evidence_messages` from `scan_evidence` including disposition fields.
    - _Requirements: 12.2, 12.3_
  - [ ]* 22.10 Test that migration SQL does not migrate rows already present in `evidence_messages` (idempotency example).
    - _Requirements: 12.5_

- [x] 23. Final checkpoint — full test suite and import verification
  - Run `pytest backend/tests/ -q` and confirm all tests pass (or document any intentionally skipped tests).
  - Verify no circular imports by importing `app.main` in a one-liner: `python -c "import app.main"` from the `backend/` directory.
  - Ensure all tests pass before concluding. Ask the user if questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP.
- Each task references specific requirements for traceability.
- Checkpoints (tasks 20 and 23) ensure incremental validation.
- Property tests validate universal correctness properties; unit tests validate specific examples and edge cases.
- `scan_evidence` is NOT dropped — the existing `/evidence/` router continues to serve from it. The new `/evidence/v2/` router serves from `evidence_messages` / `evidence_observations`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2", "3"] },
    { "id": 2, "tasks": ["4", "5"] },
    { "id": 3, "tasks": ["6", "7"] },
    { "id": 4, "tasks": ["8", "9"] },
    { "id": 5, "tasks": ["10"] },
    { "id": 6, "tasks": ["11"] },
    { "id": 7, "tasks": ["12", "16"] },
    { "id": 8, "tasks": ["13", "14"] },
    { "id": 9, "tasks": ["17"] },
    { "id": 10, "tasks": ["18"] },
    { "id": 11, "tasks": ["15", "19"] },
    { "id": 12, "tasks": ["20"] },
    { "id": 13, "tasks": ["21.1", "21.2", "21.3", "21.4", "21.5", "21.6", "21.7", "21.8", "21.9", "21.10"] },
    { "id": 14, "tasks": ["22.1", "22.2", "22.3", "22.4", "22.5", "22.6", "22.7", "22.8", "22.9", "22.10"] },
    { "id": 15, "tasks": ["23"] }
  ]
}
```
