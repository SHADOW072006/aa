"""
Stage B unit tests: alert lifecycle after reclassification, active vs historical
filtering, legacy-category retention, and zero alert deletion.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.classifiers.lexicon_loader import init_lexicons
from app.core.config import settings
from app.db.crud import get_alert_counts, get_alerts_paginated
from app.db.models import Alert, Base, Channel, Message
from app.services.reclassification_service import backfill_alert_lifecycle, run_reclassification


@pytest.fixture(autouse=True, scope="module")
def _init_lex():
    init_lexicons(
        drug_path=settings.DRUG_LEXICON_PATH,
        financial_path=settings.FINANCIAL_LEXICON_PATH,
        arms_path=settings.ARMS_LEXICON_PATH,
        scam_path=settings.SCAM_LEXICON_PATH,
        extended_path=settings.EXTENDED_LEXICON_PATH,
        overlay_path="",
    )


@pytest.mark.asyncio
async def test_alert_lifecycle_downgrade_active_and_historical_filtering():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    @asynccontextmanager
    async def _factory():
        async with Session() as s:
            yield s
            await s.commit()

    async with Session() as s:
        ch = Channel(username="placeholder_lc_ch", is_active=True)
        s.add(ch)
        await s.flush()

        # Legacy investment alert (will downgrade to LOW -> resolved_by_reclassification)
        m1 = Message(
            channel_id=ch.id, telegram_msg_id=1,
            text="colour prediction group guaranteed return investment",
            created_at=datetime(2025, 1, 1, 10, 0, 0), source="telegram",
        )
        # Newly flagged core alert
        m2 = Message(
            channel_id=ch.id, telegram_msg_id=2,
            text="heroin available for sale dm me @placeholder_dealer",
            created_at=datetime(2025, 1, 1, 10, 5, 0), source="telegram",
        )
        s.add_all([m1, m2])
        await s.flush()

        a1 = Alert(
            message_id=m1.id, risk_level="HIGH", score=0.90,
            categories="investment_fraud,colour_trading_scam",
            evidence='{"scoring_version":"legacy_v1"}',
            disposition="false_positive", is_reviewed=True, reviewed_by="analyst_a",
        )
        s.add(a1)
        await s.commit()

    res = await run_reclassification(_factory, actor="op_stage_b", dry_run=False, batch_size=10)
    assert res["no_longer_flagged"] == 1
    assert res["newly_flagged"] == 1

    async with Session() as s:
        total_alerts = (await s.execute(select(func.count(Alert.id)))).scalar_one()
        assert total_alerts == 2  # NO alerts deleted

        # Default active alerts: only m2 (HIGH)
        active = await get_alerts_paginated(s)
        assert len(active) == 1
        assert active[0].risk_level == "HIGH"
        assert active[0].lifecycle_state == "active"

        active_counts = await get_alert_counts(s)
        assert active_counts == {"HIGH": 1}

        # Historical / resolved view: m1 preserved with legacy_categories + disposition
        resolved = await get_alerts_paginated(s, lifecycle_state="resolved_by_reclassification")
        assert len(resolved) == 1
        r0 = resolved[0]
        assert r0.risk_level == "LOW"
        assert r0.categories == ""
        assert "investment_fraud" in (r0.legacy_categories or "")
        assert r0.resolved_by == "op_stage_b"
        assert r0.resolution_reason == "downgraded_to_low_by_reclassification"
        assert r0.disposition == "false_positive"

        # Backfill function is idempotent
        bf = await backfill_alert_lifecycle(s, actor="op_stage_b")
        assert bf["resolved_by_reclassification"] == 0

    await engine.dispose()

