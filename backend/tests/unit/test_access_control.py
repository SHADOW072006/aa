"""
Stage D unit tests: complete access control on sensitive read/export endpoints,
masked public summaries, Nginx header-forwarding config, and no token in frontend build.
Uses neutral placeholder records only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.database import Base, get_db
from app.db.models import Alert, Channel, ChannelScanResult, Identifier, Message, ScanJob
from app.main import app


@pytest.mark.asyncio
async def test_sensitive_endpoints_require_token_and_public_summaries_mask(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    test_token = "stage-d-operator-token-test"
    monkeypatch.setattr(settings, "API_ACCESS_TOKEN", test_token)

    now = datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as db:
        ch = Channel(username="neutral_ac_chan", title="Neutral AC Channel", is_active=True)
        db.add(ch)
        await db.flush()

        msg = Message(
            channel_id=ch.id,
            telegram_msg_id=701,
            text="neutral sample text for access control",
            has_media=False,
            created_at=now,
        )
        db.add(msg)
        await db.flush()

        ident = Identifier(
            message_id=msg.id,
            type="phone",
            value="+919999900001",
            normalised="+919999900001",
        )
        db.add(ident)

        alert = Alert(
            message_id=msg.id,
            risk_level="HIGH",
            score=0.91,
            categories="cat_a",
            lifecycle_state="active",
        )
        db.add(alert)

        job = ScanJob(status="done", seed_terms="[\"neutral\"]", total_channels_found=1)
        db.add(job)
        await db.flush()

        scan_res = ChannelScanResult(
            scan_job_id=job.id,
            channel_username="neutral_ac_chan",
            channel_title="Neutral AC Channel",
            risk_level="HIGH",
            avg_score=0.91,
            messages_scanned=5,
            flagged_count=1,
            high_count=1,
            medium_count=0,
            seed_term="neutral",
            sample_messages="[]",
            top_categories="[\"cat_a\"]",
            top_identifiers="[]",
            connected_nodes="{}",
        )
        db.add(scan_res)
        await db.commit()
        alert_id = alert.id
        job_id = job.id
        res_id = scan_res.id

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            protected_gets = [
                f"/channels/neutral_ac_chan/details",
                f"/channels/neutral_ac_chan/network",
                f"/channels/neutral_ac_chan/chain",
                f"/channels/neutral_ac_chan/chain/export/json",
                f"/scan/jobs/{job_id}/results",
                f"/scan/results/{res_id}",
                "/graph/",
                "/graph/clusters",
                "/graph/ego/neutral",
                f"/reviews/history/alert/{alert_id}",
                "/reviews/alerts/reviewed",
                f"/dispositions/history/alert/{alert_id}",
                "/search/identifier?value=99999",
                "/search/identifier/export/pdf?value=99999",
                "/pivots/",
            ]
            for path in protected_gets:
                r = await client.get(path)
                assert r.status_code == 401, f"Expected 401 for unauthenticated GET {path}, got {r.status_code}"

            r_patch = await client.patch(f"/alerts/{alert_id}/review", json={"reviewed_by": "analyst"})
            assert r_patch.status_code == 401

            # Valid X-API-Key and Bearer token succeed
            for hdrs in ({"X-API-Key": test_token}, {"Authorization": f"Bearer {test_token}"}):
                for path in protected_gets:
                    r_ok = await client.get(path, headers=hdrs)
                    assert r_ok.status_code == 200, f"Expected 200 for authorized GET {path}, got {r_ok.status_code}"

            # Public /alerts/ masks identifiers and redacts raw text
            r_pub = await client.get("/alerts/")
            assert r_pub.status_code == 200
            pub_rows = r_pub.json()
            assert len(pub_rows) == 1
            assert pub_rows[0]["message"]["text"] is None
            assert pub_rows[0]["message"]["raw_content_redacted"] is True
            assert pub_rows[0]["message"]["identifiers"][0]["masked"] is True
            assert pub_rows[0]["message"]["identifiers"][0]["value"] != "+919999900001"
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


def test_nginx_forwards_auth_headers_and_dist_has_no_token():
    repo_root = Path(__file__).resolve().parents[3]
    nginx_conf = (repo_root / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    assert "proxy_set_header Authorization $http_authorization;" in nginx_conf
    assert "proxy_set_header X-API-Key $http_x_api_key;" in nginx_conf

    dist_dir = repo_root / "frontend" / "dist"
    if dist_dir.exists():
        for asset in dist_dir.rglob("*"):
            if asset.is_file() and asset.suffix in {".js", ".html", ".css"}:
                content = asset.read_text(encoding="utf-8", errors="ignore")
                assert "VITE_API_ACCESS_TOKEN" not in content
                assert "API_ACCESS_TOKEN" not in content

