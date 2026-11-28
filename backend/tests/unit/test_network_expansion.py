"""Unit tests for offline & verified network expansion + discovery seed profile."""
from __future__ import annotations

import json
from datetime import datetime
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base, Channel, ChannelScanResult, Identifier, Message
from app.services.network_expansion import expand_channel_network
from app.services.seed_defaults import DISCOVERY_SEED_CATALOGUE, ILLEGAL_TRADE_CATEGORIES
from app.services.seed_service import sync_seed_catalogue


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session
    await engine.dispose()


def test_discovery_seed_catalogue_covers_all_categories():
    assert len(DISCOVERY_SEED_CATALOGUE) >= 20
    cats = {e["threat_category"] for e in DISCOVERY_SEED_CATALOGUE}
    assert cats == set(ILLEGAL_TRADE_CATEGORIES)
    for entry in DISCOVERY_SEED_CATALOGUE:
        assert entry["profile"] == "discovery"
        assert entry["status"] == "active"


@pytest.mark.asyncio
async def test_sync_seed_catalogue_loads_discovery_profile(db: AsyncSession):
    await sync_seed_catalogue(db)
    from app.db.crud import list_seed_profiles

    disc = await list_seed_profiles(db, is_active=True, profile="discovery", status="active", limit=500)
    assert len(disc) == len(DISCOVERY_SEED_CATALOGUE)


@pytest.mark.asyncio
async def test_offline_network_expansion_bfs_and_persist(db: AsyncSession):
    hub = Channel(username="reseller_hub", title="Reseller Hub")
    seller_a = Channel(username="seller_alpha", title="Seller Alpha")
    seller_b = Channel(username="seller_beta", title="Seller Beta")
    db.add_all([hub, seller_a, seller_b])
    await db.flush()

    m_hub1 = Message(
        channel_id=hub.id,
        telegram_msg_id=1,
        text="Check t.me/seller_gamma_unseen for stock",
        forwarded_from="seller_fwd_source",
        created_at=datetime.utcnow(),
        source="telegram",
    )
    m_hub2 = Message(
        channel_id=hub.id,
        telegram_msg_id=2,
        text="Contact +919876543210",
        created_at=datetime.utcnow(),
        source="telegram",
    )
    m_a = Message(
        channel_id=seller_a.id,
        telegram_msg_id=10,
        text="Call +919876543210",
        created_at=datetime.utcnow(),
        source="telegram",
    )
    m_b = Message(
        channel_id=seller_b.id,
        telegram_msg_id=20,
        text="UPI: hubpay@oksbi",
        created_at=datetime.utcnow(),
        source="telegram",
    )
    db.add_all([m_hub1, m_hub2, m_a, m_b])
    await db.flush()

    db.add_all([
        Identifier(message_id=m_hub2.id, type="phone", value="+919876543210", normalised="+919876543210"),
        Identifier(message_id=m_a.id, type="phone", value="+919876543210", normalised="+919876543210"),
        Identifier(message_id=m_b.id, type="upi", value="hubpay@oksbi", normalised="hubpay@oksbi"),
    ])
    await db.flush()

    # Dry-run expansion
    res = await expand_channel_network(db, "reseller_hub", max_hops=2, persist=False, verify=False)
    by_user = {f["username"]: f for f in res["frontier"]}
    assert "seller_alpha" in by_user
    assert "shared_identifier" in by_user["seller_alpha"]["reasons"]
    assert "seller_fwd_source" in by_user
    assert "forwarded_from" in by_user["seller_fwd_source"]["reasons"]
    assert "seller_gamma_unseen" in by_user
    assert "tme_link" in by_user["seller_gamma_unseen"]["reasons"]
    assert res["persisted_count"] == 0

    # Persist + mock verify
    async def _mock_verify(uname: str):
        if uname == "seller_alpha":
            return {"status": "verified", "telegram_id": 111222, "title": "Alpha Verified"}
        return {"status": "not_found"}

    res_persist = await expand_channel_network(
        db, "reseller_hub", max_hops=1, persist=True, verify=True, verify_fn=_mock_verify
    )
    assert res_persist["mode"] == "persist"
    assert res_persist["persisted_count"] >= 3
    by_user_v = {f["username"]: f for f in res_persist["frontier"]}
    assert by_user_v["seller_alpha"]["verification_status"] == "verified"
    assert by_user_v["seller_gamma_unseen"]["verification_status"] == "not_found"

    saved_rows = (await db.execute(select(ChannelScanResult))).scalars().all()
    assert len(saved_rows) == res_persist["persisted_count"]
