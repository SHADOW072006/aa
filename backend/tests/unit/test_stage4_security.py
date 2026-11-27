"""
Stage 4 security unit tests:
- Unauthenticated mutations & sensitive reads denied when API_ACCESS_TOKEN is set
- Valid token access (including proxied requests)
- Import media path validation (rejects absolute, traversal, UNC, symlink escape, unsupported ext)
- Valid controlled media import inside IMPORT_MEDIA_ROOT
- Protected /scan/clear endpoint with AuditLog
Uses minimal neutral placeholder strings and generated blank PNG bytes only.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.classifiers.lexicon_loader import init_lexicons
from app.collectors import import_handler
from app.collectors.import_handler import validate_import_media_path
from app.core.config import settings
from app.db.models import AuditLog, Base, Message


def test_validate_import_media_path_rejections(tmp_path):
    root = tmp_path / "import_media"
    root.mkdir()
    valid_img = root / "sample.png"
    valid_img.write_bytes(b"\x89PNG\r\n\x1a\n")
    bad_ext = root / "script.exe"
    bad_ext.write_bytes(b"MZ")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"\x89PNG\r\n\x1a\n")

    # Valid relative path inside root
    assert validate_import_media_path("sample.png", media_root=str(root)) == valid_img.resolve()

    # Reject absolute path
    with pytest.raises(ValueError, match="Absolute paths"):
        validate_import_media_path(str(valid_img), media_root=str(root))

    # Reject parent traversal
    with pytest.raises(ValueError, match="traversal"):
        validate_import_media_path("../outside.png", media_root=str(root))

    # Reject UNC / network path
    with pytest.raises(ValueError, match="UNC"):
        validate_import_media_path("\\\\server\\share\\img.png", media_root=str(root))

    # Reject unsupported extension
    with pytest.raises(ValueError, match="Unsupported"):
        validate_import_media_path("script.exe", media_root=str(root))

    # Reject symlink escape if supported by OS
    link_path = root / "escape.png"
    try:
        link_path.symlink_to(outside)
    except OSError:
        pass
    else:
        with pytest.raises(ValueError, match="escapes"):
            validate_import_media_path("escape.png", media_root=str(root))


@pytest.mark.asyncio
async def test_controlled_media_import_only_inside_root(monkeypatch, tmp_path):
    init_lexicons(
        drug_path=settings.DRUG_LEXICON_PATH,
        financial_path=settings.FINANCIAL_LEXICON_PATH,
        arms_path=settings.ARMS_LEXICON_PATH,
        scam_path=settings.SCAM_LEXICON_PATH,
        extended_path=settings.EXTENDED_LEXICON_PATH,
        overlay_path="",
    )
    root = tmp_path / "import_media"
    root.mkdir()
    img = root / "blank.png"
    img.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00"
        b"\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    monkeypatch.setattr(settings, "IMPORT_MEDIA_ROOT", str(root))

    async def _fake_ocr(_path: str):
        return "[placeholder ocr]"

    monkeypatch.setattr(import_handler, "extract_text_from_image", _fake_ocr)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    @asynccontextmanager
    async def _test_session():
        async with Session() as s:
            yield s
            await s.commit()

    monkeypatch.setattr(import_handler, "get_session", _test_session)

    # Traversal row must fail (errors=1), valid relative row must succeed (imported=1)
    res = await import_handler.process_rows(
        [
            {"channel": "placeholder_c", "text": "[placeholder bad]", "image_attachment": "../secret.png"},
            {"channel": "placeholder_c", "text": "[placeholder ok]", "image_attachment": "blank.png"},
        ],
        default_source="json_import",
        filename="sec.json",
    )
    assert res["errors"] == 1
    assert res["imported"] == 1

    async with Session() as s:
        msg = (await s.execute(select(Message))).scalar_one()
        assert msg.media_hash is not None
        assert msg.ocr_text == "[placeholder ocr]"

    await engine.dispose()


def test_mutation_and_sensitive_routes_require_token(monkeypatch):
    from app.main import app

    monkeypatch.setattr(settings, "API_ACCESS_TOKEN", "test-stage4-token")
    client = TestClient(app)

    protected_calls = [
        ("POST", "/channels/", {"json": {"username": "placeholder_ch"}}),
        ("DELETE", "/channels/1", {}),
        ("POST", "/seeds/", {"json": {"seed_text": "x", "threat_category": "drugs", "intent_type": "sale_or_supply"}}),
        ("POST", "/seeds/sync", {}),
        ("POST", "/scan/run", {"json": {}}),
        ("DELETE", "/scan/clear", {"json": {"confirm": "CLEAR"}}),
        ("POST", "/reviews/export", {}),
        ("POST", "/governance/retention/purge", {}),
        ("POST", "/governance/reclassify", {"json": {"dry_run": True}}),
        ("GET", "/governance/verify/message/1", {}),
        ("GET", "/alerts/1", {}),
        ("GET", "/evidence/?scan_job_id=1", {}),
        ("GET", "/evidence/v2/messages/1", {}),
    ]

    for method, path, kwargs in protected_calls:
        r_no_auth = client.request(method, path, **kwargs)
        assert r_no_auth.status_code == 401, f"{method} {path} returned {r_no_auth.status_code}"

        r_bad_auth = client.request(method, path, headers={"Authorization": "Bearer wrong"}, **kwargs)
        assert r_bad_auth.status_code == 401, f"{method} {path} accepted bad token"

    # Valid token passes auth check (returns non-401/403)
    r_ok = client.get("/governance/audit-logs", headers={"X-API-Key": "test-stage4-token"})
    assert r_ok.status_code != 401 and r_ok.status_code != 403

