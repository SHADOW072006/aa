#!/usr/bin/env python
"""
Pre-demo preparation script for TeleMonitor (PS02 demo DB).

1. Syncs the seed catalogue (including profile="discovery") into ps02_demo.db.
2. If the stored Telegram session is authorised (never prompts for OTP), runs
   ONE small discovery scan using 2 neutral seeds ("jobs rajasthan", "trading")
   so Scan History is non-empty for the live demo.
3. Runs offline network expansion (persist=True, verify=False) from the
   reseller hub ("All Services 24x7 💯") so expanded seller channels are
   recorded in channel_scan_results.

Safe to re-run; never touches backend/tele_monitor.db.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
DEMO_DB_PATH = (ROOT / "data" / "local" / "ps02_demo" / "ps02_demo.db").resolve()

os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{DEMO_DB_PATH.as_posix()}")
os.environ.setdefault("TESTING", "1")
os.environ.setdefault("DISABLE_BACKGROUND_TASKS", "1")
os.environ.setdefault("DISCOVERY_ENABLED", "false")
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import delete, select  # noqa: E402

from app.classifiers.lexicon_loader import init_lexicons  # noqa: E402
from app.collectors import scanner  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.database import AsyncSessionLocal, init_db  # noqa: E402
from app.db.models import Channel, ChannelScanResult, ScanJob  # noqa: E402
from app.services.network_expansion import expand_channel_network  # noqa: E402
from app.services.seed_service import sync_seed_catalogue  # noqa: E402

NEUTRAL_DEMO_SEEDS = ["jobs rajasthan", "trading"]


async def _run_neutral_live_scan() -> None:
    try:
        from app.collectors.telegram_collector import get_collector

        collector = get_collector()
        client = collector.client
        if not client.is_connected():
            await asyncio.wait_for(client.connect(), timeout=20)
        authorised = await asyncio.wait_for(client.is_user_authorized(), timeout=20)
    except Exception as exc:
        print(f"[live-scan] Skipping live discovery scan (session check failed: {exc})")
        return

    if not authorised:
        print("[live-scan] Telegram session is not authorised; skipping without OTP prompt.")
        return

    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(
                select(ScanJob)
                .where(
                    ScanJob.status == "done",
                    ScanJob.seed_terms == json.dumps(NEUTRAL_DEMO_SEEDS),
                    ScanJob.total_messages_scanned > 0,
                )
                .order_by(ScanJob.id.desc())
            )
        ).scalars().first()
        if existing:
            print(
                f"[live-scan] Reusing existing completed ScanJob #{existing.id} "
                f"(found={existing.total_channels_found}, scanned={existing.total_channels_scanned}, "
                f"msgs={existing.total_messages_scanned}, flagged={existing.total_flagged})"
            )
            return
        # Clean up any empty previous attempt where lexicons weren't loaded
        empty_jobs = (
            await db.execute(
                select(ScanJob.id).where(
                    ScanJob.seed_terms == json.dumps(NEUTRAL_DEMO_SEEDS),
                    ScanJob.total_messages_scanned == 0,
                )
            )
        ).scalars().all()
        if empty_jobs:
            await db.execute(delete(ChannelScanResult).where(ChannelScanResult.scan_job_id.in_(empty_jobs)))
            await db.execute(delete(ScanJob).where(ScanJob.id.in_(empty_jobs)))
            await db.commit()

        job = ScanJob(seed_terms=json.dumps(NEUTRAL_DEMO_SEEDS), status="pending")
        db.add(job)
        await db.commit()
        await db.refresh(job)
        job_id = job.id

    print(f"[live-scan] Running neutral discovery ScanJob #{job_id} with seeds={NEUTRAL_DEMO_SEEDS} ...")
    await scanner._run_scan_job(
        job_id,
        NEUTRAL_DEMO_SEEDS,
        mode="review",
        profile="discovery",
        is_custom=True,
    )

    async with AsyncSessionLocal() as db:
        done_job = (await db.execute(select(ScanJob).where(ScanJob.id == job_id))).scalar_one_or_none()
        if done_job:
            print(
                f"[live-scan] ScanJob #{done_job.id} status={done_job.status} "
                f"found={done_job.total_channels_found} scanned={done_job.total_channels_scanned} "
                f"flagged={done_job.total_flagged}"
            )


async def _run_offline_expansion() -> None:
    async with AsyncSessionLocal() as db:
        hub = (
            await db.execute(select(Channel).where(Channel.username.ilike("%All Services 24x7%")))
        ).scalar_one_or_none()
        if not hub:
            print("[offline-expand] Reseller hub not found in demo DB; skipping.")
            return
        res = await expand_channel_network(
            db,
            hub.username,
            max_hops=2,
            limit=25,
            persist=True,
            verify=False,
        )
        print(
            f"[offline-expand] root={res['root_username']!r} frontier={res['frontier_count']} "
            f"persisted={res['persisted_count']}"
        )
        for item in res["frontier"][:8]:
            print(
                f"  - hop={item['hop']} {item['username']} "
                f"reasons={item['reasons']} evidence={item['evidence'][:2]}"
            )


async def main() -> None:
    init_lexicons(
        drug_path=settings.DRUG_LEXICON_PATH,
        financial_path=settings.FINANCIAL_LEXICON_PATH,
        arms_path=settings.ARMS_LEXICON_PATH,
        scam_path=settings.SCAM_LEXICON_PATH,
        extended_path=settings.EXTENDED_LEXICON_PATH,
    )
    await init_db()
    async with AsyncSessionLocal() as db:
        sync_res = await sync_seed_catalogue(db)
        await db.commit()
        print(f"[seeds] synced catalogue v{sync_res['catalogue_version']} (created={sync_res['created']}, updated={sync_res['updated']})")

    await _run_neutral_live_scan()
    await _run_offline_expansion()


if __name__ == "__main__":
    asyncio.run(main())
