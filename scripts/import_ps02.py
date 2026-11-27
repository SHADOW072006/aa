"""
Import the official PS02 demo dataset into a fresh TeleMonitor database.

Imports, in order:
  1. 01_telegram_exports/ch*/result.json  — Telegram Desktop exports, one
     channel per folder, photos OCR'd (media root = the channel folder)
  2. 02_social_media/posts.csv            — the CSV/JSON import path
     (channel = author handle, media root = 02_social_media)

Usage (from anywhere):
    python scripts/import_ps02.py                       # default locations
    python scripts/import_ps02.py --db path/to/file.db # custom DB location

Default DB: <data-dir>/ps02_demo.db. The database is recreated on every run.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))


async def run_import(data_dir: Path) -> dict:
    from app.classifiers.lexicon_loader import init_lexicons
    from app.core.config import settings

    init_lexicons(
        drug_path=settings.DRUG_LEXICON_PATH,
        financial_path=settings.FINANCIAL_LEXICON_PATH,
        arms_path=settings.ARMS_LEXICON_PATH,
        scam_path=settings.SCAM_LEXICON_PATH,
        extended_path=settings.EXTENDED_LEXICON_PATH,
    )
    from app.collectors.import_handler import process_rows
    from app.collectors.telegram_export import telegram_export_rows
    from app.db.database import init_db

    await init_db()

    totals = {"messages": 0, "flagged": 0, "errors": 0, "duplicates": 0, "channels": 0}
    report = []

    exports_dir = data_dir / "01_telegram_exports"
    for ch_dir in sorted(p for p in exports_dir.iterdir() if p.is_dir()):
        result_json = ch_dir / "result.json"
        if not result_json.exists():
            continue
        rows, meta = telegram_export_rows(result_json)
        # photos are relative to the channel export folder
        settings.IMPORT_MEDIA_ROOT = str(ch_dir)
        summary = await process_rows(rows, default_source="telegram_export",
                                     filename=meta["name"])
        entry = {"channel": meta["name"], "type": meta["chat_type"], **meta,
                 "summary": summary}
        report.append(entry)
        totals["channels"] += 1
        totals["messages"] += summary["imported"] + summary["duplicates"]
        totals["flagged"] += summary["flagged"]
        totals["errors"] += summary["errors"]
        totals["duplicates"] += summary["duplicates"]
        print(f"[tg] {meta['name']}: {json.dumps(summary)}")

    sm_dir = data_dir / "02_social_media"
    posts_csv = sm_dir / "posts.csv"
    if posts_csv.exists():
        settings.IMPORT_MEDIA_ROOT = str(sm_dir)
        text_content = posts_csv.read_bytes().decode("utf-8-sig", errors="replace")
        rows = list(csv.DictReader(io.StringIO(text_content)))
        summary = await process_rows(rows, default_source="social_import",
                                     filename="posts.csv")
        report.append({"channel": "social_media", "summary": summary})
        totals["channels"] += 1
        totals["messages"] += summary["imported"] + summary["duplicates"]
        totals["flagged"] += summary["flagged"]
        totals["errors"] += summary["errors"]
        totals["duplicates"] += summary["duplicates"]
        print(f"[sm] posts.csv: {json.dumps(summary)}")

    return {"totals": totals, "report": report}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(REPO / "data" / "local" / "ps02_demo"),
                        help="PS02 dataset root (default: data/local/ps02_demo)")
    parser.add_argument("--db", default=None,
                        help="SQLite file path (default: <data-dir>/ps02_demo.db)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    if not data_dir.exists():
        raise SystemExit(f"dataset not found: {data_dir}")
    db_path = Path(args.db).resolve() if args.db else data_dir / "ps02_demo.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()

    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    os.environ["TESTING"] = "1"
    os.environ["DISABLE_BACKGROUND_TASKS"] = "1"
    os.environ["DISCOVERY_ENABLED"] = "false"
    # OCR is deterministic per media file — cache across re-imports so the
    # classifier/extractor iteration loop stays fast.
    os.environ.setdefault("TELEMONITOR_OCR_CACHE", str(data_dir / "ocr_cache.json"))
    os.chdir(BACKEND)  # lexicon paths are relative to backend/

    result = asyncio.run(run_import(data_dir))
    print("\ntotals:", json.dumps(result["totals"]))
    print(f"database: {db_path}")
    (data_dir / "import_report.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return 1 if result["totals"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
