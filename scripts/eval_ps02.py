"""
Score TeleMonitor's PS02 pipeline output against the official answer key.

Measures, from a database produced by scripts/import_ps02.py:
  1. classification  — per-label and per-difficulty precision/recall/F1
                       (expected flag = label != "normal", predicted = alert)
  2. identifiers     — per-type precision/recall/F1 (phones, UPI, handles,
                       wallets, bank accounts, sites, locations) against the
                       expected identifiers listed per post
  3. entity linking  — cross-channel spread per identifier vs entity_graph_identifiers.csv
  4. campaigns       — cross-channel near-duplicate coverage of coordinated_campaigns.csv
  5. OCR             — poster OCR vs expected_ocr_text (token F1 + identifier recovery)

Usage:
    python scripts/eval_ps02.py                       # defaults below
    python scripts/eval_ps02.py --db data/local/ps02_demo/ps02_demo.db
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

LABEL_FAMILIES = {
    "drugs": {"cannabis", "cocaine", "cocaine_sale", "heroin", "mdma", "drug_sale",
              "methamphetamine", "psilocybin", "opium", "crack_cocaine", "lsd",
              "opioid", "dissociative", "depressant", "benzodiazepine",
              "injection_drug", "pills"},
    "arms": {"arms_sale"},
    "fake_documents": {"fake_docs", "forged_documents"},
    "bank_account_sale": {"account_sale", "account_rent", "mule_recruitment",
                          "corporate_mule", "netbanking_sale", "upi_sale"},
    "atm_card_sale": {"card_sale", "card_rent", "credential_sale"},
    "sim_card_sale": {"sim_sale"},
}
IDENT_FIELDS = [
    ("phones_e164", "phone", False),
    ("upi_ids", "upi", False),
    ("handles", "handle", True),      # key uses "@name"; we store without "@"
    ("wallets", "wallet_usdt", False),
    ("bank_accounts", "bank_account", False),
    ("sites", "site", False),
    ("locations", "location", True),  # substring credit against full locality strings
]


def split_list(raw: str) -> list[str]:
    return [p.strip() for p in (raw or "").split(";") if p.strip()]


def load_key(data_dir: Path) -> dict:
    def read_csv(path: Path) -> list[dict]:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))

    key_dir = data_dir / "99_answer_key"
    sm_posts_path = data_dir / "02_social_media" / "posts.csv"
    sm_posts = {}
    if sm_posts_path.exists():
        for r in read_csv(sm_posts_path):
            sm_posts[r["post_id"]] = {"author": r["author"], "text": r["text"]}
    return {
        "posts": read_csv(key_dir / "posts_labelled.csv"),
        "channels": {r["key"]: r for r in read_csv(key_dir / "channel_ids.csv")},
        "graph": read_csv(key_dir / "entity_graph_identifiers.csv"),
        "campaigns": read_csv(key_dir / "coordinated_campaigns.csv"),
        "images": read_csv(key_dir / "images_labelled.csv"),
        "near_dup_images": read_csv(key_dir / "near_duplicate_images.csv"),
        "sm_posts": sm_posts,
    }


def load_db(db_path: Path) -> dict:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    channels = {r["id"]: r["username"] for r in con.execute("SELECT id, username FROM channels")}
    messages = {}
    for r in con.execute(
        "SELECT m.id, m.telegram_msg_id, m.text, m.ocr_text, m.minhash_sig, m.channel_id, "
        "c.username AS channel FROM messages m JOIN channels c ON c.id = m.channel_id"):
        messages[r["id"]] = dict(r)
    alerts = {r["message_id"]: (r["risk_level"], (r["categories"] or "").split(","))
              for r in con.execute("SELECT message_id, risk_level, categories FROM alerts")}
    identifiers = defaultdict(set)   # message_id -> {(type, normalised)}
    for r in con.execute("SELECT message_id, type, normalised FROM identifiers"):
        identifiers[r["message_id"]].add((r["type"], r["normalised"]))
    con.close()
    return {"channels": channels, "messages": messages,
            "alerts": alerts, "identifiers": identifiers}


def join_key_to_db(key: dict, db: dict) -> tuple[dict, list[str]]:
    """Map each answer-key post_uid to our message row (or None)."""
    by_tg = {}
    by_sm = {}
    for mid, m in db["messages"].items():
        by_tg[(m["channel"], int(m["telegram_msg_id"]))] = mid
        by_sm[(m["channel"], (m["text"] or "").strip())] = mid

    mapping, unmapped = {}, []
    for row in key["posts"]:
        uid = row["post_uid"]
        if row["source"] == "telegram":
            # TG:ch01:2 -> ch01 -> channel display name -> (name, msg id)
            key_id = uid.split(":")[1]
            ch_name = key["channels"].get(key_id, {}).get("channel_name")
            mid = by_tg.get((ch_name, int(row["msg_or_post_id"])))
        else:
            sm = key["sm_posts"].get(row["msg_or_post_id"], {})
            chan = sm.get("author", row.get("author", "")).lstrip("@")
            mid = by_sm.get((chan, (sm.get("text") or "").strip()))
        if mid is None:
            unmapped.append(uid)
        mapping[uid] = mid
    return mapping, unmapped


def classification_metrics(key: dict, mapping: dict, db: dict) -> dict:
    buckets = defaultdict(lambda: Counter())   # name -> tp/fp/tn/fn counters
    cat_hits = Counter()
    cat_total = Counter()
    fp_samples, fn_samples = [], []

    for row in key["posts"]:
        mid = mapping.get(row["post_uid"])
        if mid is None:
            buckets["unmapped"]["rows"] += 1
            continue
        expected_flag = row["label"] != "normal"
        alert = db["alerts"].get(mid)
        predicted_flag = alert is not None
        b = buckets["overall"]
        if expected_flag and predicted_flag:
            b["tp"] += 1
        elif expected_flag:
            b["fn"] += 1
            if len(fn_samples) < 15:
                fn_samples.append((row["post_uid"], row["label"], row["difficulty"],
                                   row["difficulty_reason"][:60]))
        elif predicted_flag:
            b["fp"] += 1
            if len(fp_samples) < 15:
                risk, cats = alert
                fp_samples.append((row["post_uid"], row["role"], risk,
                                   ",".join(c for c in cats if c)[:60]))
        else:
            b["tn"] += 1
        for dim, val in (("label", row["label"]), ("difficulty", row["difficulty"]),
                         ("role", row["role"])):
            b = buckets[f"{dim}:{val}"]
            if expected_flag and predicted_flag:
                b["tp"] += 1
            elif expected_flag:
                b["fn"] += 1
            elif predicted_flag:
                b["fp"] += 1
            else:
                b["tn"] += 1
        if expected_flag and predicted_flag:
            fam = LABEL_FAMILIES.get(row["label"], set())
            cat_total[row["label"]] += 1
            if fam & {c.strip() for c in alert[1] if c.strip()}:
                cat_hits[row["label"]] += 1

    def prf(c: Counter) -> dict:
        tp, fp, fn, tn = c["tp"], c["fp"], c["fn"], c["tn"]
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
                "precision": round(p, 3), "recall": round(r, 3), "f1": round(f1, 3)}

    out = {name: prf(c) for name, c in buckets.items() if c}
    out["_category_accuracy"] = {k: f"{cat_hits[k]}/{cat_total[k]}" for k in sorted(cat_total)}
    out["_fp_samples"] = fp_samples
    out["_fn_samples"] = fn_samples
    return out


def identifier_metrics(key: dict, mapping: dict, db: dict) -> dict:
    stats = {name: Counter() for name, _t, _s in IDENT_FIELDS}
    for row in key["posts"]:
        mid = mapping.get(row["post_uid"])
        if mid is None:
            continue
        ours = db["identifiers"].get(mid, set())
        for field, itype, fuzzy in IDENT_FIELDS:
            expected_raw = split_list(row.get(field, ""))
            if not expected_raw and not any(t == itype for t, _n in ours):
                continue
            if itype == "handle":
                expected = {e.lstrip("@").lower() for e in expected_raw}
            elif itype == "phone":
                expected = {re.sub(r"\D", "", e) for e in expected_raw if re.sub(r"\D", "", e)}
            elif fuzzy and itype == "location":
                expected = {e.lower() for e in expected_raw}
            else:
                expected = {e.lower() for e in expected_raw}
            predicted = {n.lower() for t, n in ours if t == itype}
            if itype == "phone":
                predicted = {re.sub(r"\D", "", n) for n in predicted}
            if fuzzy and itype == "location":
                hit = {n for n in predicted if any(n in e for e in expected)}
            else:
                hit = predicted & expected
            stats[field]["tp"] += len(hit)
            stats[field]["fp"] += len(predicted - expected) if not fuzzy else len(predicted - hit)
            stats[field]["fn"] += len(expected - predicted) if not fuzzy else len(expected - hit)
            stats[field]["support"] += len(expected)

    out = {}
    for field, c in stats.items():
        p = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else 0.0
        r = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        out[field] = {"precision": round(p, 3), "recall": round(r, 3), "f1": round(f1, 3),
                      "support": c["support"], "tp": c["tp"], "fp": c["fp"], "fn": c["fn"]}
    return out


def linking_metrics(key: dict, db: dict) -> dict:
    con = sqlite3.connect(_DB_PATH)
    rows_out = []
    hit = 0
    for row in key["graph"]:
        ident = row["identifier"].strip()
        if "(" in ident:  # "(partial ..7431926)" entries — the full number is scored separately
            continue
        norm = ident.lstrip("@").lower()
        expected_n = int(row["n_channels"])
        cur = con.execute(
            "SELECT COUNT(DISTINCT m.channel_id) FROM identifiers i "
            "JOIN messages m ON m.id = i.message_id WHERE i.normalised = ?", (norm,))
        ours = cur.fetchone()[0]
        ok = ours >= expected_n
        hit += ok
        rows_out.append({"identifier": ident, "expected_channels": expected_n,
                         "ours": ours, "match": ok})
    con.close()
    return {"hit_rate": f"{hit}/{len(rows_out)}", "rows": rows_out}


def campaign_metrics(key: dict, mapping: dict, db: dict) -> dict:
    import numpy as np

    msgs = [(mid, m) for mid, m in db["messages"].items() if m["minhash_sig"]]
    mat, meta = [], []
    for mid, m in msgs:
        try:
            sig = json.loads(m["minhash_sig"])
            if len(sig) == 128:
                mat.append(sig)
                meta.append(mid)
        except Exception:
            continue
    if not mat:
        return {"note": "no minhash signatures in DB"}
    M = np.array(mat, dtype=np.int64)
    partners = defaultdict(set)   # message_id -> set of channel_ids with near-dup
    for i in range(len(M)):
        sims = (M[i] == M[i + 1:]).mean(axis=1)
        for j in np.nonzero(sims >= 0.7)[0]:
            a, b = meta[i], meta[i + 1 + j]
            if db["messages"][a]["channel_id"] != db["messages"][b]["channel_id"]:
                partners[a].add(db["messages"][b]["channel_id"])
                partners[b].add(db["messages"][a]["channel_id"])

    out = {}
    for camp in key["campaigns"]:
        uids = camp["post_uids"].split()
        covered = 0
        checked = 0
        for uid in uids:
            mid = mapping.get(uid)
            if mid is None:
                continue
            checked += 1
            if partners.get(mid):
                covered += 1
        out[camp["campaign_id"]] = {"coverage": f"{covered}/{checked}",
                                    "rate": round(covered / checked, 2) if checked else 0.0}
    return out


def ocr_metrics(key: dict, data_dir: Path) -> dict:
    import asyncio

    from app.extractors.ocr import extract_text_from_image

    async def _run():
        results = {}
        posters_dir = data_dir / "03_images" / "posters"
        for row in key["images"]:
            path = posters_dir / row["image"]
            text = await extract_text_from_image(str(path)) or ""
            results[row["image"]] = text
        return results

    ocr = asyncio.run(_run())

    def tokens(s: str) -> set[str]:
        return set(re.findall(r"[a-z0-9@.]{3,}", re.sub(r"\s+", " ", s.lower())))

    # identifier recovery judged through the real extractor, not substrings
    from app.classifiers.lexicon_loader import init_lexicons
    from app.core.config import settings
    from app.extractors.identifier_extractor import extract as extract_ids

    init_lexicons(
        drug_path=settings.DRUG_LEXICON_PATH,
        financial_path=settings.FINANCIAL_LEXICON_PATH,
        arms_path=settings.ARMS_LEXICON_PATH,
        scam_path=settings.SCAM_LEXICON_PATH,
        extended_path=settings.EXTENDED_LEXICON_PATH,
    )

    out, f1s, ident_hits, ident_total = {}, [], 0, 0
    for row in key["images"]:
        expected = row["expected_ocr_text"]
        got = ocr.get(row["image"], "")
        et, gt = tokens(expected), tokens(got)
        tp = len(et & gt)
        p = tp / len(gt) if gt else 0.0
        r = tp / len(et) if et else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        f1s.append(f1)
        got_ids = {(i.type, re.sub(r"\D", "", i.normalised)[-10:] if i.type == "phone" else i.normalised.lower())
                   for i in extract_ids(got)}
        recovered = []
        for m in re.finditer(r"\+91[\s-]?\d{5}[\s-]?\d{5}", expected):
            want = re.sub(r"\D", "", m.group())[-10:]
            recovered.append(("phone", want) in got_ids)
        for m in re.finditer(r"@(\w+(?:\.\w+)*)", expected):
            recovered.append(("handle", m.group(1).lower()) in got_ids)
        for m in re.finditer(r"\bT[A-Za-z0-9]{33}\b", expected):
            recovered.append(("wallet_usdt", m.group().lower()) in got_ids)
        for m in re.finditer(r"[\w.-]+@(?:ybl|axl|paytm|okhdfcbank|okaxis)\b", expected):
            recovered.append(("upi", m.group().lower()) in got_ids)
        ident_hits += sum(1 for x in recovered if x)
        ident_total += len(recovered)
        out[row["image"]] = {"degradation": row["degradation"],
                             "token_f1": round(f1, 2),
                             "identifiers": f"{sum(1 for x in recovered if x)}/{len(recovered)}"}
    return {"mean_token_f1": round(sum(f1s) / len(f1s), 2) if f1s else 0.0,
            "identifier_recovery": f"{ident_hits}/{ident_total}", "posters": out}


_DB_PATH = None


def main() -> int:
    global _DB_PATH
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(REPO / "data" / "local" / "ps02_demo"))
    parser.add_argument("--db", default=None)
    parser.add_argument("--skip-ocr", action="store_true")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    db_path = Path(args.db).resolve() if args.db else data_dir / "ps02_demo.db"
    _DB_PATH = db_path
    os.chdir(str(REPO / "backend"))  # noqa: F821 — ocr import needs backend relative paths? (not strictly)

    key = load_key(data_dir)
    db = load_db(db_path)
    mapping, unmapped = join_key_to_db(key, db)
    print(f"answer-key posts: {len(key['posts'])}  mapped: {len(key['posts']) - len(unmapped)}  "
          f"unmapped: {len(unmapped)}  db messages: {len(db['messages'])}  alerts: {len(db['alerts'])}")

    cls = classification_metrics(key, mapping, db)
    print("\n=== CLASSIFICATION (expected flag = label != normal) ===")
    for name in ("overall",) + tuple(k for k in cls if not k.startswith("_") and k != "overall"):
        m = cls[name]
        print(f"  {name:<28} P {m['precision']:.3f}  R {m['recall']:.3f}  F1 {m['f1']:.3f}  "
              f"(tp {m['tp']} fp {m['fp']} fn {m['fn']} tn {m['tn']})")
    print("  category accuracy:", cls["_category_accuracy"])
    print("  FP samples:", cls["_fp_samples"][:8])
    print("  FN samples:", cls["_fn_samples"][:8])

    ids = identifier_metrics(key, mapping, db)
    print("\n=== IDENTIFIER EXTRACTION ===")
    for field, m in ids.items():
        print(f"  {field:<14} P {m['precision']:.3f}  R {m['recall']:.3f}  F1 {m['f1']:.3f}  "
              f"(support {m['support']}, tp {m['tp']}, fp {m['fp']}, fn {m['fn']})")

    link = linking_metrics(key, db)
    print(f"\n=== ENTITY LINKING (cross-channel spread) === {link['hit_rate']}")
    for r in link["rows"]:
        if not r["match"]:
            print(f"  miss: {r['identifier']} expected {r['expected_channels']} channels, ours {r['ours']}")

    camp = campaign_metrics(key, mapping, db)
    print("\n=== COORDINATED CAMPAIGNS (cross-channel near-dup coverage) ===")
    for cid, m in camp.items():
        print(f"  {cid:<18} {m}")

    if not args.skip_ocr:
        ocr = ocr_metrics(key, data_dir)
        print(f"\n=== POSTER OCR === mean token F1 {ocr['mean_token_f1']}  "
              f"identifier recovery {ocr['identifier_recovery']}")
        for image, m in ocr["posters"].items():
            print(f"  {image:<10} {m['degradation']:<16} F1 {m['token_f1']:<5} ids {m['identifiers']}")

    report = {"classification": cls, "identifiers": ids, "linking": link,
              "campaigns": camp, "unmapped": unmapped}
    if not args.skip_ocr:
        report["ocr"] = ocr
    out_path = data_dir / "eval_report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nreport written: {out_path}")
    return 0


if __name__ == "__main__":
    main()
