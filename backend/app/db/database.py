"""
Async SQLAlchemy engine + session factory.

Usage
-----
    from app.db.database import get_session, init_db

    # In FastAPI startup:
    await init_db()

    # In a route:
    async with get_session() as session:
        result = await session.execute(...)
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.models import Base

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    # SQLite-specific: allow use from multiple threads via same connection + 30s lock timeout
    connect_args={"check_same_thread": False, "timeout": 30} if "sqlite" in settings.DATABASE_URL else {},
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def _migrate_sqlite_columns(conn) -> None:
    """Safely add new columns to existing SQLite tables if not present."""
    try:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.exec_driver_sql("PRAGMA busy_timeout=30000")
    except Exception:
        pass
    try:
        res = await conn.exec_driver_sql("PRAGMA table_info(channels)")
        existing_channels_cols = {row[1] for row in res.fetchall()}
        new_channel_cols = [
            ("description", "TEXT"),
            ("member_count", "INTEGER"),
            ("is_verified", "BOOLEAN DEFAULT 0"),
            ("is_scam", "BOOLEAN DEFAULT 0"),
            ("invite_link", "VARCHAR(512)"),
        ]
        for col_name, col_type in new_channel_cols:
            if col_name not in existing_channels_cols:
                await conn.exec_driver_sql(f"ALTER TABLE channels ADD COLUMN {col_name} {col_type}")

        res = await conn.exec_driver_sql("PRAGMA table_info(channel_scan_results)")
        existing_scan_cols = {row[1] for row in res.fetchall()}
        new_scan_cols = [
            ("channel_description", "TEXT"),
            ("connected_nodes", "TEXT"),
            ("is_verified", "BOOLEAN DEFAULT 0"),
            ("is_scam", "BOOLEAN DEFAULT 0"),
            ("invite_link", "VARCHAR(512)"),
            ("severity_tier", "VARCHAR(16) DEFAULT 'LOW'"),
            ("is_serious", "BOOLEAN DEFAULT 0"),
            # Req 17.4 — new columns
            ("discovered_by_variant_id", "INTEGER"),
            ("composite_score", "REAL"),
        ]
        for col_name, col_type in new_scan_cols:
            if col_name not in existing_scan_cols:
                await conn.exec_driver_sql(f"ALTER TABLE channel_scan_results ADD COLUMN {col_name} {col_type}")

        # --- channels new columns (Req 17.4) ---
        new_channel_cols_v2 = [
            ("poll_tier", "TEXT DEFAULT 'LOW'"),
            ("last_poll_attempted_at", "DATETIME"),
            ("consecutive_error_count", "INTEGER DEFAULT 0"),
            ("error_state", "BOOLEAN DEFAULT 0"),
            ("channel_status", "TEXT DEFAULT 'active'"),
            ("discovery_variant_id", "INTEGER"),
            ("next_poll_at", "DATETIME"),
        ]
        for col_name, col_type in new_channel_cols_v2:
            if col_name not in existing_channels_cols:
                await conn.exec_driver_sql(f"ALTER TABLE channels ADD COLUMN {col_name} {col_type}")

        # --- alerts new columns (Req 17.4) ---
        res = await conn.exec_driver_sql("PRAGMA table_info(alerts)")
        existing_alerts_cols = {row[1] for row in res.fetchall()}
        new_alert_cols = [
            ("disposition", "TEXT"),
            ("disposition_notes", "TEXT"),
            ("disposition_by", "TEXT"),
            ("disposition_at", "DATETIME"),
            ("lifecycle_state", "VARCHAR(32) NOT NULL DEFAULT 'active'"),
            ("resolved_at", "DATETIME"),
            ("resolved_by", "VARCHAR(128)"),
            ("resolution_reason", "TEXT"),
            ("latest_scoring_version", "VARCHAR(32)"),
            ("legacy_categories", "VARCHAR(512)"),
        ]
        for col_name, col_type in new_alert_cols:
            if col_name not in existing_alerts_cols:
                await conn.exec_driver_sql(f"ALTER TABLE alerts ADD COLUMN {col_name} {col_type}")

        # --- seed_profiles new columns (Stage 2) ---
        res = await conn.exec_driver_sql("PRAGMA table_info(seed_profiles)")
        existing_sp_cols = {row[1] for row in res.fetchall()}
        new_sp_cols = [
            ("profile", "VARCHAR(32) NOT NULL DEFAULT 'illegal_trade'"),
            ("seed_role", "VARCHAR(32) NOT NULL DEFAULT 'indicator'"),
            ("status", "VARCHAR(16) NOT NULL DEFAULT 'active'"),
            ("rationale", "TEXT"),
            ("catalogue_version", "VARCHAR(32)"),
            ("alert_count", "INTEGER NOT NULL DEFAULT 0"),
            ("reviewed_fp_count", "INTEGER NOT NULL DEFAULT 0"),
            ("reviewed_total_count", "INTEGER NOT NULL DEFAULT 0"),
        ]
        for col_name, col_type in new_sp_cols:
            if col_name not in existing_sp_cols:
                await conn.exec_driver_sql(f"ALTER TABLE seed_profiles ADD COLUMN {col_name} {col_type}")

        # --- messages Stage 4 columns ---
        res = await conn.exec_driver_sql("PRAGMA table_info(messages)")
        existing_msg_cols = {row[1] for row in res.fetchall()}
        for col_name, col_type in [
            ("original_text_hash", "VARCHAR(64)"),
            ("evidence_hash", "VARCHAR(64)"),
            ("media_hash", "VARCHAR(64)"),
            ("provenance_status", "VARCHAR(32)"),
            ("ocr_text", "TEXT"),
            ("ocr_status", "VARCHAR(24)"),
            ("ocr_skip_reason", "VARCHAR(32)"),
            ("image_phash", "VARCHAR(64)"),
            ("forwarded_from", "VARCHAR(256)"),
        ]:
            if col_name not in existing_msg_cols:
                await conn.exec_driver_sql(f"ALTER TABLE messages ADD COLUMN {col_name} {col_type}")

        # --- scan_evidence Stage 4 provenance columns ---
        # Existing databases predate these nullable fields.  create_all() does
        # not alter an already-created SQLite table, so migrate them explicitly.
        res = await conn.exec_driver_sql("PRAGMA table_info(scan_evidence)")
        existing_se_cols = {row[1] for row in res.fetchall()}
        for col_name, col_type in [
            ("original_text_hash", "VARCHAR(64)"),
            ("evidence_hash", "VARCHAR(64)"),
        ]:
            if col_name not in existing_se_cols:
                await conn.exec_driver_sql(
                    f"ALTER TABLE scan_evidence ADD COLUMN {col_name} {col_type}"
                )
        await conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_scan_evidence_evidence_hash "
            "ON scan_evidence (evidence_hash)"
        )

        # --- evidence_messages & evidence_observations Stage 4 columns ---
        res = await conn.exec_driver_sql("PRAGMA table_info(evidence_messages)")
        existing_em_cols = {row[1] for row in res.fetchall()}
        for col_name, col_type in [
            ("original_text_hash", "VARCHAR(64)"),
            ("evidence_hash", "VARCHAR(64)"),
            ("provenance_status", "VARCHAR(32)"),
        ]:
            if col_name not in existing_em_cols:
                await conn.exec_driver_sql(f"ALTER TABLE evidence_messages ADD COLUMN {col_name} {col_type}")

        res = await conn.exec_driver_sql("PRAGMA table_info(evidence_observations)")
        existing_eo_cols = {row[1] for row in res.fetchall()}
        for col_name, col_type in [
            ("observation_hash", "VARCHAR(64)"),
            ("import_batch_id", "INTEGER"),
        ]:
            if col_name not in existing_eo_cols:
                await conn.exec_driver_sql(f"ALTER TABLE evidence_observations ADD COLUMN {col_name} {col_type}")

        await conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS import_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename VARCHAR(255) NOT NULL,
                source_type VARCHAR(32) NOT NULL,
                imported_count INTEGER NOT NULL DEFAULT 0,
                duplicate_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS reclassification_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scoring_version VARCHAR(32) NOT NULL,
                status VARCHAR(24) NOT NULL DEFAULT 'pending',
                dry_run BOOLEAN NOT NULL DEFAULT 0,
                last_processed_message_id INTEGER NOT NULL DEFAULT 0,
                total_messages INTEGER NOT NULL DEFAULT 0,
                processed_count INTEGER NOT NULL DEFAULT 0,
                changed_risk_count INTEGER NOT NULL DEFAULT 0,
                changed_category_count INTEGER NOT NULL DEFAULT 0,
                newly_flagged_count INTEGER NOT NULL DEFAULT 0,
                no_longer_flagged_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                started_by VARCHAR(128) NOT NULL,
                worker_id VARCHAR(128),
                started_at DATETIME NOT NULL DEFAULT (datetime('now')),
                heartbeat_at DATETIME,
                updated_at DATETIME,
                finished_at DATETIME,
                error TEXT
            )
        """)
        res = await conn.exec_driver_sql("PRAGMA table_info(reclassification_jobs)")
        existing_rj_cols = {row[1] for row in res.fetchall()}
        for col_name, col_type in [
            ("worker_id", "VARCHAR(128)"),
            ("heartbeat_at", "DATETIME"),
            ("updated_at", "DATETIME"),
        ]:
            if col_name not in existing_rj_cols:
                await conn.exec_driver_sql(f"ALTER TABLE reclassification_jobs ADD COLUMN {col_name} {col_type}")

        # DB-backed uniqueness: at most 1 live non-dry-run running job; 1 reclassification obs per (em, version)
        # Note: if an older stale running job exists before operator recovery, index creation is skipped safely until recovered.
        try:
            await conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_reclass_one_active_live "
                "ON reclassification_jobs (status) WHERE status = 'running' AND dry_run = 0"
            )
        except Exception:
            pass
        try:
            await conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_obs_reclass_msg_ver "
                "ON evidence_observations (evidence_message_id, classifier_version) "
                "WHERE source_type = 'reclassification'"
            )
        except Exception:
            pass

    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("SQLite auto-migration warning: %s", exc)
    # ── analyst_reviews table ──────────────────────────────────────────────────
    try:
        await conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS analyst_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_type VARCHAR(32) NOT NULL,
                target_id INTEGER NOT NULL,
                label VARCHAR(32) NOT NULL,
                category VARCHAR(32),
                intent VARCHAR(32),
                reviewed_by VARCHAR(128) NOT NULL,
                reviewed_at DATETIME NOT NULL DEFAULT (datetime('now')),
                note TEXT,
                classifier_score REAL,
                classifier_risk_level VARCHAR(16),
                sampling_stratum VARCHAR(128),
                UNIQUE (target_type, target_id)
            )
        """)
        res = await conn.exec_driver_sql("PRAGMA table_info(analyst_reviews)")
        existing_ar_cols = {row[1] for row in res.fetchall()}
        if "sampling_stratum" not in existing_ar_cols:
            await conn.exec_driver_sql("ALTER TABLE analyst_reviews ADD COLUMN sampling_stratum VARCHAR(128)")

        await conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS analyst_review_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_id INTEGER,
                target_type VARCHAR(32) NOT NULL,
                target_id INTEGER NOT NULL,
                label VARCHAR(32) NOT NULL,
                category VARCHAR(32),
                intent VARCHAR(32),
                reviewed_by VARCHAR(128) NOT NULL,
                reviewed_at DATETIME NOT NULL DEFAULT (datetime('now')),
                note TEXT,
                sampling_stratum VARCHAR(128),
                classifier_score REAL,
                classifier_risk_level VARCHAR(16)
            )
        """)
        await conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor VARCHAR(128) NOT NULL,
                action VARCHAR(64) NOT NULL,
                target_type VARCHAR(32),
                target_id INTEGER,
                record_hash VARCHAR(64),
                details TEXT,
                created_at DATETIME NOT NULL DEFAULT (datetime('now'))
            )
        """)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("analyst_reviews migration warning: %s", exc)


    # ── Create evidence_messages and evidence_observations if not present ──────
    try:
        await conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS evidence_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_username VARCHAR(255) NOT NULL,
                telegram_message_id BIGINT NOT NULL,
                message_timestamp DATETIME,
                raw_text TEXT,
                caption_text TEXT,
                ocr_text TEXT,
                normalised_text TEXT,
                extracted_identifiers TEXT,
                media_path TEXT,
                media_hash VARCHAR(64),
                ocr_outcome VARCHAR(16),
                ocr_skip_reason VARCHAR(32),
                first_seen_at DATETIME NOT NULL DEFAULT (datetime('now')),
                last_seen_at DATETIME NOT NULL DEFAULT (datetime('now')),
                disposition VARCHAR(32),
                disposition_notes TEXT,
                disposition_by VARCHAR(128),
                disposition_at DATETIME,
                UNIQUE (channel_username, telegram_message_id)
            )
        """)

        await conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS evidence_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                evidence_message_id INTEGER NOT NULL REFERENCES evidence_messages(id),
                scan_job_id INTEGER REFERENCES scan_jobs(id),
                channel_scan_result_id INTEGER REFERENCES channel_scan_results(id),
                seed_profile_id INTEGER REFERENCES seed_profiles(id),
                query_variant_id INTEGER REFERENCES query_variants(id),
                source_type VARCHAR(32) NOT NULL,
                classifier_version VARCHAR(32) NOT NULL DEFAULT 'lexicon_v1',
                score REAL NOT NULL,
                risk_level VARCHAR(16) NOT NULL,
                severity_tier VARCHAR(16) NOT NULL,
                categories TEXT,
                matched_terms TEXT,
                classified_at DATETIME NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # ── Migrate scan_evidence rows into new tables (idempotent) ──────────
        # Check if scan_evidence table exists first
        se_check = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='scan_evidence'"
        )
        if se_check.fetchone():
            # Insert canonical message rows — only those not already migrated
            await conn.exec_driver_sql("""
                INSERT OR IGNORE INTO evidence_messages (
                    channel_username, telegram_message_id, message_timestamp,
                    raw_text, ocr_text, normalised_text,
                    media_path, media_hash, ocr_outcome, ocr_skip_reason,
                    first_seen_at, last_seen_at,
                    disposition, disposition_notes, disposition_by, disposition_at
                )
                SELECT
                    channel_username,
                    telegram_message_id,
                    message_timestamp,
                    raw_text,
                    ocr_text,
                    normalised_text,
                    media_path,
                    media_hash,
                    CASE WHEN ocr_success = 1 THEN 'success'
                         WHEN ocr_skip_reason IS NOT NULL THEN 'skipped'
                         WHEN ocr_text IS NOT NULL THEN 'success'
                         ELSE 'not_applicable' END,
                    ocr_skip_reason,
                    last_classified_at,
                    last_classified_at,
                    disposition,
                    disposition_notes,
                    disposition_by,
                    disposition_at
                FROM scan_evidence
            """)

            # Insert observation rows — only for messages already in evidence_messages
            # and not already migrated (evidence_observations.scan_job_id + evidence_message_id combo)
            await conn.exec_driver_sql("""
                INSERT INTO evidence_observations (
                    evidence_message_id, scan_job_id, channel_scan_result_id,
                    query_variant_id, source_type, score, risk_level, severity_tier,
                    categories, matched_terms, classified_at
                )
                SELECT
                    em.id,
                    se.scan_job_id,
                    se.channel_scan_result_id,
                    se.query_variant_id,
                    'scheduled_scan',
                    se.classifier_score,
                    se.risk_level,
                    se.severity_tier,
                    se.categories,
                    se.matched_terms,
                    se.last_classified_at
                FROM scan_evidence se
                JOIN evidence_messages em
                    ON em.channel_username = se.channel_username
                    AND em.telegram_message_id = se.telegram_message_id
                WHERE NOT EXISTS (
                    SELECT 1 FROM evidence_observations eo
                    WHERE eo.evidence_message_id = em.id
                      AND eo.scan_job_id = se.scan_job_id
                )
            """)

    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Evidence table migration warning: %s", exc)


async def init_db() -> None:
    """Create all tables (idempotent) and migrate columns."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if "sqlite" in settings.DATABASE_URL:
            await _migrate_sqlite_columns(conn)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
