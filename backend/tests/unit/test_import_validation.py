"""
Import robustness tests: timestamp parsing never invents values, and the
dry-run preview (validate_rows) reports accurate, side-effect-free results.
"""
from __future__ import annotations

import pytest

from app.classifiers.lexicon_loader import init_lexicons
from app.collectors.import_handler import _parse_date, validate_rows
from app.core.config import settings


@pytest.fixture(scope="module", autouse=True)
def _lexicons():
    init_lexicons(
        drug_path=settings.DRUG_LEXICON_PATH,
        financial_path=settings.FINANCIAL_LEXICON_PATH,
        arms_path=settings.ARMS_LEXICON_PATH,
        scam_path=settings.SCAM_LEXICON_PATH,
        extended_path=settings.EXTENDED_LEXICON_PATH,
        overlay_path="",
    )


def test_parse_date_handles_iso_z_and_offsets():
    dt, status = _parse_date("2024-03-15T10:30:00Z")
    assert status == "parsed"
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2024, 3, 15, 10, 30)

    dt, status = _parse_date("2024-03-15T10:30:00+05:30")
    assert status == "parsed"
    # +05:30 offset normalised to naive UTC
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2024, 3, 15, 5, 0)


def test_parse_date_epoch_and_common_formats():
    dt, status = _parse_date("1710498600")
    assert status == "epoch" and dt.year == 2024

    dt, status = _parse_date("2024-03-15 10:30:00")
    assert status == "parsed" and dt.hour == 10

    dt, status = _parse_date("15/03/2024")
    assert status == "parsed" and dt.day == 15 and dt.month == 3


def test_parse_date_never_invents_timestamps():
    for raw in ("March 15, 2024", "not-a-date", "2024-13-99"):
        dt, status = _parse_date(raw)
        assert dt is None and status == "unparsed"
    assert _parse_date("") == (None, "missing")
    assert _parse_date(None) == (None, "missing")


def test_validate_rows_reports_and_agrees_with_labels():
    rows = [
        {"text": "weed available discreet delivery dm for price", "channel": "ch_a",
         "created_at": "2025-01-01T10:00:00Z", "label": "flag"},
        {"text": "account on rent with atm card and netbanking kit, rent 8000 monthly", "channel": "ch_b",
         "created_at": "2025-01-02 11:00:00", "label": "flag"},
        {"text": "good morning everyone", "channel": "ch_a", "created_at": "bad-date!!", "label": "clear"},
        {"text": "new iphone available for sale dm for price", "channel": "ch_a", "label": "clear"},
    ]
    report = validate_rows(rows, default_source="csv_import", filename="t.csv")
    assert report["total_rows"] == 4
    assert report["timestamps"]["parsed"] == 2
    assert report["timestamps"]["unparsed"] == 1
    assert report["timestamps"]["missing"] == 1
    assert report["classification"]["flagged"] == 2
    assert report["labels"]["column"] == "label"
    assert report["label_agreement"]["labelled_rows"] == 4
    assert report["label_agreement"]["agree"] == 4
    assert report["label_agreement"]["disagree"] == 0
    assert report["channels"]["ch_a"] == 3
    assert report["errors"] == []


def test_validate_rows_counts_media_and_never_touches_the_database():
    rows = [
        {"text": "poster ad text", "channel": "ch_x",
         "image_attachment": "posters/does_not_exist.png"},
        {"text": "totally normal post about cricket", "channel": "ch_x",
         "created_at": "2025-02-03T09:00:00Z", "label": "clear"},
    ]
    report = validate_rows(rows, filename="preview.json")
    assert report["media_rows"] == 1
    assert report["classification"]["flagged"] == 0
    assert report["timestamps"]["parsed"] == 1
    assert report["label_agreement"]["agree"] == 1
    # Preview must not have created import artefacts
    assert report["source_type"] == "csv_import"


def test_validate_rows_labels_distribution_and_disagreement_sample():
    rows = [
        {"text": "desi katta available 15000 with ammo", "channel": "c", "label": "arms_sale"},
        {"text": " completely benign text about a birthday party", "channel": "c", "label": "benign"},
        {"text": "savings account on rent, contact us", "channel": "c", "label": "1"},
    ]
    report = validate_rows(rows)
    assert report["labels"]["distribution"] == {"arms_sale": 1, "benign": 1, "1": 1}
    agreement = report["label_agreement"]
    assert agreement["labelled_rows"] == 3
    assert agreement["disagree"] == 0


@pytest.mark.asyncio
async def test_import_keeps_one_channel_across_link_forms_and_case(monkeypatch):
    from contextlib import asynccontextmanager

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.collectors import import_handler
    from app.db.database import Base
    from app.db.models import Channel, Message

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

    rows = [
        {"text": "placeholder neutral post one", "channel": "@Demo_Seller", "created_at": "2025-04-01T10:00:00Z"},
        {"text": "placeholder neutral post two", "channel": "t.me/demo_seller", "created_at": "2025-04-02T10:00:00Z"},
        {"text": "placeholder neutral post three", "channel": "https://t.me/Demo_Seller/",
         "created_at": "2025-04-03T10:00:00Z"},
    ]
    try:
        res = await import_handler.process_rows(rows, default_source="csv_import", filename="channels.csv")
        assert res["imported"] == 3 and res["errors"] == 0

        async with Session() as s:
            names = [r[0] for r in (await s.execute(select(Channel.username))).all()]
            channel_ids = [r[0] for r in (await s.execute(select(Message.channel_id))).all()]
        assert names == ["Demo_Seller"]
        assert len(set(channel_ids)) == 1 and len(channel_ids) == 3
    finally:
        await engine.dispose()


def test_import_summary_reports_unparsed_timestamps_instead_of_hiding_them():
    rows = [{"text": "placeholder neutral post", "channel": "ch", "created_at": "later today!!"}]
    report = validate_rows(rows)
    assert report["timestamps"]["unparsed"] == 1
    assert report["timestamps"]["unparsed_row_indices"] == [0]
