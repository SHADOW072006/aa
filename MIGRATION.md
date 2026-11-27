# Migration Guide — v1 → v2

## Database Migration
The v2 release adds 8 new tables and several new columns to existing tables. Migration is **automatic** on startup via `init_db()` which calls:
1. `Base.metadata.create_all()` — creates all new tables
2. `_migrate_sqlite_columns()` — idempotently adds new columns to `channels`, `channel_scan_results`, and `alerts`

No manual SQL is required. The migration is safe to run on an existing v1 database.

## New columns on existing tables
- **channels**: `poll_tier`, `last_poll_attempted_at`, `consecutive_error_count`, `error_state`, `channel_status`, `discovery_variant_id`
- **channel_scan_results**: `discovered_by_variant_id`, `composite_score`
- **alerts**: `disposition`, `disposition_notes`, `disposition_by`, `disposition_at`

## Configuration
Add these settings to your `.env` file (all have sensible defaults):
```
POLL_INTERVAL_HIGH=30
POLL_INTERVAL_MEDIUM=60
POLL_INTERVAL_LOW=300
MIN_BACKOFF=10
BACKOFF_MULTIPLIER=2.0
MAX_RETRY_COUNT=5
ERROR_STATE_WINDOW_HOURS=24
ERROR_STATE_THRESHOLD=3
COMPOSITE_HIGH_MSG_CAP=10
COMPOSITE_INCIDENT_CAP=5
COMPOSITE_PIVOT_CAP=5
```

## New Dependencies
Backend (add to `requirements.txt` if not present):
- `unidecode` (optional — for transliteration variants)

Frontend: No new dependencies required.
