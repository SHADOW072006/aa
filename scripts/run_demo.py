"""
TeleMonitor demo dataset: generate + run the complete pipeline end to end.

The dataset is fully synthetic (fictional identifiers in reserved-looking
ranges: +91 90000 xxxxx, @demo_* handles, *@fakebank-style UPI). It exercises
every PS feature: multi-category classification, identifier extraction and
cross-channel linking, near-duplicate ads, OCR on generated posters, evidence
timestamps, and the entity graph.

Usage (from backend/):
    python ../scripts/run_demo.py            # generate if missing, run checks
    python ../scripts/run_demo.py --regen    # regenerate dataset files

Exit code 0 = every check passed.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
DEMO = REPO / "data" / "demo"
sys.path.insert(0, str(BACKEND))

# ─────────────────────────────────────────────────────────────────────────────
# 1. Synthetic dataset definition
# ─────────────────────────────────────────────────────────────────────────────

# One fictional syndicate shares a phone, a UPI id and a handle across three
# channels; other channels cover the remaining PS categories; a benign channel
# proves the false-positive controls.
SHARED_PHONE = "+91 90000 41255"
SHARED_UPI = "cashhub99@ybl"
SHARED_HANDLE = "@cashagent_main"

POSTERS = {
    "poster_mule_kit.png": [
        "FULL KYC KIT ON RENT",
        "BANK ACCOUNT + ATM CARD",
        "NET BANKING + REGISTERED SIM",
        "WEEKLY RENT 5000 ONLY",
        f"CONTACT {SHARED_PHONE}",
        f"UPI {SHARED_UPI}",
    ],
    "poster_atm_card.png": [
        "ATM CARD FOR SALE",
        "ACTIVE CARD WITH PIN",
        "ALL BANKS ACCEPTED",
        "DM @cashagent_main NOW",
    ],
    "poster_sim.png": [
        "FRESH SIM CARDS",
        "OTP ACCESS READY",
        "BULK ORDER 500 PER SIM",
        f"WHATSAPP {SHARED_PHONE}",
    ],
    "poster_docs.png": [
        "FAKE AADHAAR CARD",
        "PAN CARD DRIVING LICENCE",
        "MADE IN 1 DAY 5000 EACH",
        "WHATSAPP +91 90000 55210",
    ],
    "poster_arms.png": [
        "DESI KATTA AVAILABLE",
        "9MM PISTOL WITH AMMO",
        "DELIVERY IN UP BIHAR",
        "CONTACT +91 90000 55310",
    ],
    "poster_drugs.png": [
        "PREMIUM COKE AVAILABLE",
        "DISCREET DELIVERY",
        "DM FOR PRICE",
        "UPI ACCEPTED @snowman_deals",
    ],
}

# (id, text, channel, created_at, sender, poster-or-None, label, categories_any)
ROWS = [
    (1, f"Fresh bank account with net banking available on rent, contact {SHARED_PHONE}",
     "mule_recruiter_01", "2026-11-20T09:00:00Z", "sellerA", None, "flag",
     ["account_sale", "account_rent", "netbanking_sale"]),
    (2, f"Need savings account chahiye with ATM card, rent 8000 monthly. Ping {SHARED_HANDLE}",
     "mule_agent_02", "2026-11-21T10:15:00", "sellerA", None, "flag",
     ["account_sale", "card_sale"]),
    (3, f"Bank account for sale with netbanking kit and registered sim, dm {SHARED_HANDLE} or pay to {SHARED_UPI}",
     "cash_hub_03", "2026-11-22T11:30:00+05:30", "sellerB", None, "flag",
     ["account_sale", "netbanking_sale", "sim_sale"]),
    (4, f"We buy bank accounts, 15000 per account with active net banking and debit card, pay UPI {SHARED_UPI} or whatsapp {SHARED_PHONE}",
     "mule_recruiter_01", "2026-11-22T12:00:00Z", "sellerA", None, "flag",
     ["account_sale", "card_sale"]),
    (5, f"Current account sale, corporate account lena hai 3 percent commission, dm {SHARED_HANDLE}",
     "mule_agent_02", "2026-11-23T13:00:00Z", "sellerC", None, "flag",
     ["account_sale", "corporate_mule"]),
    # near-duplicate ad posted in two channels (MinHash); the two posts share
    # every token except the closing word so the Jaccard stays above 0.7
    (6, f"Full kit on rent ATM card cheque book net banking registered SIM weekly rent 5000 contact {SHARED_PHONE} today",
     "mule_agent_02", "2026-11-23T14:00:00Z", "sellerC", None, "flag",
     ["account_sale", "card_sale", "netbanking_sale", "sim_sale"]),
    (7, f"Full kit on rent ATM card cheque book net banking registered SIM weekly rent 5000 contact {SHARED_PHONE} now",
     "cash_hub_03", "2026-11-23T15:00:00Z", "sellerB", "posters/poster_mule_kit.png", "flag",
     ["account_sale", "card_sale", "netbanking_sale", "sim_sale"]),
    (8, "Premium Colombian coke available in Delhi NCR, discreet delivery, UPI accepted, dm @snowman_deals",
     "green_market", "2026-11-23T16:00:00Z", "sellerD", "posters/poster_drugs.png", "flag",
     ["cocaine", "drug_sale"]),
    (9, "weed available discreet delivery dm for price",
     "green_market", "2026-11-23T16:30:00Z", "sellerD", None, "flag", ["cannabis"]),
    (10, "\U0001F344 \U0001F36C available dm for rates",
     "green_market", "2026-11-23T16:45:00Z", "sellerD", None, "flag",
     ["psilocybin", "mdma"]),
    (11, "Desi katta available 15000, 9mm pistol with ammo, contact on whatsapp",
     "iron_deals", "2026-11-23T17:00:00Z", "sellerE", "posters/poster_arms.png", "flag",
     ["arms_sale"]),
    (12, ".32 bore revolver for sale with 6 live rounds, delivery in UP and Bihar, dm @ironwala_77",
     "iron_deals", "2026-11-23T17:30:00Z", "sellerE", None, "flag", ["arms_sale"]),
    (13, "Fake Aadhaar card, PAN card, driving licence made in 1 day, 5000 each, WhatsApp +91 90000 55210",
     "doc_factory", "2026-11-23T18:00:00Z", "sellerF", "posters/poster_docs.png", "flag",
     ["fake_docs"]),
    (14, "Passport quality fake documents, degrees, marksheet available, dm @docwala_official",
     "doc_factory", "2026-11-23T18:30:00Z", "sellerF", None, "flag", ["fake_docs"]),
    (15, "ATM card for sale dm +91 90000 55400",
     "sim_deals", "2026-11-23T19:00:00Z", "sellerG", "posters/poster_atm_card.png", "flag",
     ["card_sale"]),
    (16, "Fresh SIM cards available with OTP access, 500 per sim, bulk order accepted",
     "sim_deals", "2026-11-23T19:30:00Z", "sellerG", "posters/poster_sim.png", "flag",
     ["sim_sale"]),
    # benign distractors
    (17, "Good morning everyone, have a great day",
     "normal_market", "2026-11-23T20:00:00Z", "friendH", None, "clear", []),
    (18, "New iPhone 15 available for sale, DM for price",
     "normal_market", "2026-11-23T20:30:00Z", "friendH", None, "clear", []),
    (19, "Open a zero balance savings account with free ATM card and net banking. Visit your branch with Aadhaar and PAN.",
     "normal_market", "2026-11-23T21:00:00Z", "friendH", None, "clear", []),
    (20, "Royal Enfield Bullet 350 for sale, first owner, single hand, contact 98765 43210",
     "normal_market", "2026-11-23T21:30:00Z", "friendH", None, "clear", []),
    (21, "Police arrested two drug peddlers in Mumbai and seized 5 kg of heroin worth 2 crore",
     "normal_market", "2026-11-23T22:00:00Z", "friendH", None, "clear", []),
    (22, "I love Mumbai city life, the food is amazing",
     "normal_market", "2026-11-23T22:30:00Z", "friendH", None, "clear", []),
]

CSV_HEADER = ["message_id", "text", "channel", "created_at", "sender", "image_attachment", "label"]


def generate_dataset(force: bool = False) -> None:
    """Write demo_posts.csv, expected_labels.json and the poster PNGs."""
    csv_path = DEMO / "demo_posts.csv"
    labels_path = DEMO / "expected_labels.json"
    posters_dir = DEMO / "posters"
    if force or not csv_path.exists():
        DEMO.mkdir(parents=True, exist_ok=True)
        posters_dir.mkdir(exist_ok=True)
        with open(csv_path, "w", encoding="utf-8", newline="") as fh:
            import csv as csv_lib

            writer = csv_lib.writer(fh)
            writer.writerow(CSV_HEADER)
            for rid, text, channel, ts, sender, poster, label, _cats in ROWS:
                writer.writerow([rid, text, channel, ts, sender, poster or "", label])
        labels_path.write_text(json.dumps({
            "note": "Fully synthetic demo labels. All identifiers are fictional.",
            "rows": [
                {"message_id": rid, "expect": label, "categories_any": cats}
                for rid, _t, _c, _ts, _s, _p, label, cats in ROWS
            ],
        }, indent=2), encoding="utf-8")
        print(f"dataset written: {csv_path}")
    if force or not any(posters_dir.glob("*.png")):
        _render_posters(posters_dir)


def _render_posters(posters_dir: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    def font(size):
        for name in ("arialbd.ttf", "arial.ttf", "segoeui.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    big, mid = font(46), font(30)
    for name, lines in POSTERS.items():
        img = Image.new("RGB", (820, 120 + 62 * len(lines)), (16, 18, 34))
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 819, 8], fill=(220, 60, 60))
        y = 46
        for i, line in enumerate(lines):
            draw.text((46, y), line, fill=(255, 214, 0) if i == 0 else (235, 235, 235),
                      font=big if i == 0 else mid)
            y += 62
        img.save(posters_dir / name)
    print(f"posters written: {posters_dir} ({len(POSTERS)} files)")


# ─────────────────────────────────────────────────────────────────────────────
# 2. End-to-end run + checks
# ─────────────────────────────────────────────────────────────────────────────

def main(regen: bool = False) -> int:
    generate_dataset(force=regen)

    tmp = Path(tempfile.mkdtemp(prefix="telemonitor_demo_"))
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(tmp / 'demo.db').as_posix()}"
    os.environ["TESTING"] = "1"
    os.environ["DISABLE_BACKGROUND_TASKS"] = "1"
    os.environ["DISCOVERY_ENABLED"] = "false"
    os.chdir(BACKEND)  # lexicon paths are relative to backend/

    from app.classifiers.lexicon_loader import init_lexicons
    from app.core.config import settings

    init_lexicons(
        drug_path=settings.DRUG_LEXICON_PATH,
        financial_path=settings.FINANCIAL_LEXICON_PATH,
        arms_path=settings.ARMS_LEXICON_PATH,
        scam_path=settings.SCAM_LEXICON_PATH,
        extended_path=settings.EXTENDED_LEXICON_PATH,
    )
    from app.db.database import init_db

    asyncio.run(init_db())

    from app.collectors.import_handler import import_csv

    settings.IMPORT_MEDIA_ROOT = str(DEMO)
    summary = asyncio.run(import_csv((DEMO / "demo_posts.csv").read_bytes(), "demo_posts.csv"))
    print("import summary:", json.dumps(summary))

    con = sqlite3.connect(tmp / "demo.db")
    cur = con.cursor()

    failures: list[str] = []
    passed = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal passed
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}" + (f" — {detail}" if detail and not ok else ""))
        if ok:
            passed += 1
        else:
            failures.append(name)

    # 1. every expected flag → alert with the right family of categories
    alerts = {mid: (risk, cats.split(","))
              for mid, risk, cats in cur.execute(
                  "SELECT m.telegram_msg_id, a.risk_level, a.categories FROM alerts a "
                  "JOIN messages m ON m.id = a.message_id")}
    for rid, _t, _c, _ts, _s, _p, label, cats in ROWS:
        if label == "flag":
            risk, got_cats = alerts.get(rid, (None, []))
            ok = risk in ("HIGH", "MEDIUM") and set(got_cats) & set(cats)
            check(f"flag row {rid} -> alert {risk or 'MISSING'}", bool(ok),
                  f"expected any of {cats}, got {got_cats}")
        else:
            check(f"clear row {rid} -> no alert", rid not in alerts)

    # 2. shared identifiers really connect the syndicate channels
    for label, expected_min in (("phone", 3), ("upi", 2), ("handle", 2)):
        norm = {"phone": "+919000041255", "upi": "cashhub99@ybl", "handle": "cashagent_main"}[label]
        chans = [r[0] for r in cur.execute(
            "SELECT DISTINCT c.username FROM identifiers i "
            "JOIN messages m ON m.id = i.message_id JOIN channels c ON c.id = m.channel_id "
            "WHERE i.normalised = ?", (norm,))]
        check(f"shared {label} links >= {expected_min} channels", len(chans) >= expected_min,
              f"{norm} found in {chans}")

    # 3. graph: syndicate cluster + near-duplicate edge
    from app.db.database import get_session
    from app.graph.entity_graph import build_graph, get_graph_json

    async def _graph():
        async with get_session() as db:
            return get_graph_json(await build_graph(db), limit_nodes=500)

    g = asyncio.run(_graph())
    chan_nodes = {e["data"]["id"] for e in g["elements"] if e["data"].get("type") == "channel"}
    check("graph contains syndicate channel nodes",
          {"ch:mule_recruiter_01", "ch:mule_agent_02", "ch:cash_hub_03"} <= chan_nodes,
          f"channel nodes: {sorted(chan_nodes)}")
    near_dup = any(
        "near_duplicate_text" in (e["data"].get("reason", "") + "," + ",".join(e["data"].get("reasons", [])))
        for e in g["elements"] if "source" in e["data"])
    check("graph has a near-duplicate text edge", near_dup)

    # 4. timestamps preserved (row 1 was ISO-Z; stored naive-UTC)
    row1 = cur.execute(
        "SELECT created_at FROM messages WHERE telegram_msg_id = 1").fetchone()
    ok_ts = row1 and row1[0].startswith("2026-11-20 09:00:00")
    check("ISO-Z timestamp preserved through import", bool(ok_ts), f"stored: {row1}")

    # 5. OCR on the generated posters
    ocr_rows = cur.execute(
        "SELECT COUNT(*), SUM(CASE WHEN ocr_text IS NOT NULL AND ocr_text != '' THEN 1 ELSE 0 END) "
        "FROM messages WHERE has_media = 1").fetchone()
    try:
        import easyocr  # noqa: F401
        ocr_available = True
    except ImportError:
        ocr_available = False
    if ocr_available:
        check(f"OCR extracted text from posters ({ocr_rows[1]}/{ocr_rows[0]} media rows)",
              ocr_rows[0] > 0 and ocr_rows[1] == ocr_rows[0])
    else:
        print(f"[SKIP] OCR check — easyocr not installed ({ocr_rows[0]} media rows imported)")

    # 6. identifiers on flagged rows feed the search API path
    ident_total = cur.execute("SELECT COUNT(*) FROM identifiers").fetchone()[0]
    check("identifiers extracted", ident_total >= 5, f"count: {ident_total}")

    print(f"\n{passed} checks passed, {len(failures)} failed")
    if failures:
        print("failed:", ", ".join(failures))
    else:
        print(f"demo DB kept at: {tmp / 'demo.db'}  (temp dir {tmp})")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(regen="--regen" in sys.argv))
