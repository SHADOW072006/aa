import asyncio, logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.alerts import router as alerts_router
from app.api.channels import router as channels_router
from app.api.discovery import router as discovery_router
from app.api.evidence import router as evidence_router
from app.api.evidence_v2 import router as evidence_v2_router
from app.api.governance import router as governance_router
from app.api.graph import router as graph_router
from app.api.import_routes import router as import_router
from app.api.pivots import router as pivots_router
from app.api.scan import router as scan_router
from app.api.search import router as search_router
from app.api.dispositions import router as dispositions_router
from app.api.seeds import router as seeds_router
from app.api.reviews import router as reviews_router
from app.classifiers.lexicon_loader import init_lexicons
from app.collectors.channel_discovery import get_discovery_engine
from app.collectors.scheduler import get_scheduler
from app.collectors.telegram_collector import get_collector
from app.core.config import settings
from app.db.database import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s")
logger = logging.getLogger(__name__)

_collector_task = None
_discovery_task = None

async def _ensure_default_seeds() -> None:
    """Run versioned, idempotent seed catalogue synchronization at startup."""
    try:
        from app.db.database import get_session
        from app.services.seed_service import sync_seed_catalogue
        async with get_session() as db:
            stats = await sync_seed_catalogue(db)
        logger.info("Seed catalogue synced: %s", stats)
    except Exception as exc:
        logger.warning("Default seed sync failed (non-fatal): %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initialising database...")
    await init_db()
    try:
        from app.db.database import get_session
        from sqlalchemy import text
        async with get_session() as db:
            await db.execute(
                text(
                    "UPDATE scan_jobs SET status='interrupted', finished_at=CURRENT_TIMESTAMP, "
                    "error='Interrupted by server restart' WHERE status IN ('running', 'pending')"
                )
            )
    except Exception as exc:
        logger.warning("Orphaned scan_jobs cleanup warning: %s", exc)
    try:
        from app.db.database import get_session
        from app.services.reclassification_service import cleanup_stale_reclassification_jobs
        async with get_session() as db:
            cleaned = await cleanup_stale_reclassification_jobs(db)
            if cleaned:
                logger.info("Marked %d stale reclassification job(s) as interrupted", cleaned)
    except Exception as exc:
        logger.warning("Stale reclassification_jobs cleanup warning: %s", exc)
    try:
        from app.db.database import get_session
        from app.services.minhash_service import get_minhash_index
        async with get_session() as db:
            await get_minhash_index().rebuild_from_db(db)
    except Exception as exc:
        logger.warning("MinHash LSH startup rebuild warning: %s", exc)
    logger.info("Seeding default seed profiles if DB is empty...")
    await _ensure_default_seeds()
    logger.info("Loading lexicons...")
    init_lexicons(
        drug_path=settings.DRUG_LEXICON_PATH,
        financial_path=settings.FINANCIAL_LEXICON_PATH,
        arms_path=settings.ARMS_LEXICON_PATH,
        scam_path=settings.SCAM_LEXICON_PATH,
        extended_path=settings.EXTENDED_LEXICON_PATH,
    )
    global _collector_task, _discovery_task
    import os
    skip_bg = settings.TESTING or settings.DISABLE_BACKGROUND_TASKS or bool(os.getenv("PYTEST_CURRENT_TEST"))
    if not skip_bg and settings.TELEGRAM_API_ID and settings.TELEGRAM_API_HASH:
        logger.info("Starting Telegram collector...")
        try:
            collector = get_collector()
            await collector.start()
            scheduler = get_scheduler(collector.client)
            _collector_task = asyncio.create_task(scheduler.run_forever())
            if settings.DISCOVERY_ENABLED:
                logger.info("Starting channel discovery engine...")
                _discovery_task = asyncio.create_task(get_discovery_engine().run_forever())
        except Exception as exc:
            try:
                await collector.client.disconnect()
            except Exception:
                pass
            logger.error(
                "Telegram collector failed to start (%s). "
                "If 'database is locked', stop any other running uvicorn/backend process. "
                "API server will continue without live Telegram polling.",
                exc,
            )
    else:
        logger.warning("TELEGRAM credentials not set - collector disabled.")
    yield
    for task in (_collector_task, _discovery_task):
        if task:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass

app = FastAPI(title="Telegram Illegal Trade Monitor", version="1.3.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.FRONTEND_ORIGIN],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(channels_router)
app.include_router(alerts_router)
app.include_router(graph_router)
app.include_router(import_router)
app.include_router(search_router)
app.include_router(discovery_router)
app.include_router(scan_router)
app.include_router(pivots_router)
app.include_router(seeds_router)
app.include_router(reviews_router)
app.include_router(dispositions_router)
app.include_router(evidence_router)
app.include_router(evidence_v2_router)
app.include_router(governance_router)

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.3.0"}
