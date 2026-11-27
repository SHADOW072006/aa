"""
Train a TF-IDF + LogisticRegression classifier for illegal-ad detection.

Usage
-----
    python scripts/train_classifier.py \
        --input data/training_data.csv \
        --output data/models/classifier.joblib

Training data format (CSV)
--------------------------
    text,label
    "want to buy meth, dm me",1
    "good morning everyone",0

If no training data is available, the script generates synthetic samples
from the lexicons so the ML model bootstraps with reasonable baseline
performance.  Replace with real labelled data for production use.

The trained pipeline is a sklearn Pipeline:
    TfidfVectorizer (char n-grams 2-4, word n-grams 1-3) →
    LogisticRegression (C=1.0, class_weight=balanced)
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline, FeatureUnion
from sklearn.preprocessing import FunctionTransformer

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ── Synthetic data generation ─────────────────────────────────────────────────

def _load_lexicon_terms(path: str) -> list[str]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return list(data.get("terms", {}).keys())


def generate_synthetic_data(lexicon_dir: str = "../data/lexicons") -> list[tuple[str, int]]:
    """
    Minimal synthetic dataset — positive examples are lexicon terms in
    typical ad sentences; negative examples are benign messages.
    For production, replace or augment with real labelled data.
    """
    p = Path(lexicon_dir)
    all_terms: list[str] = []
    for lex_file in p.glob("*.json"):
        all_terms.extend(_load_lexicon_terms(str(lex_file)))

    positive_templates = [
        "{term} available, dm me",
        "best quality {term}, discreet delivery",
        "{term} for sale, contact @dealer123",
        "selling {term} at good price, +919876543210",
        "{term} home delivery, ping me",
        "want {term}? dm for price",
        "{term} chahiye? call now",
        "atm card for sale, {term} available",
        "bank account on rent, {term} deal",
        "{term} guaranteed quality, pay UPI",
    ]

    negative_templates = [
        "good morning everyone!",
        "happy birthday to you",
        "today's weather looks great",
        "join our coding bootcamp",
        "free webinar on python programming",
        "latest cricket match highlights",
        "10% off on all electronics",
        "government scheme for farmers",
        "stock market update for today",
        "healthy breakfast ideas for you",
        "job opening at software firm",
        "how to meditate in 5 steps",
    ]

    samples: list[tuple[str, int]] = []
    rng = np.random.default_rng(42)

    for term in all_terms:
        tmpl = positive_templates[int(rng.integers(len(positive_templates)))]
        samples.append((tmpl.format(term=term), 1))

    # Double up negatives so the class balance is roughly 1:2
    for _ in range(len(samples) * 2):
        tmpl = negative_templates[int(rng.integers(len(negative_templates)))]
        samples.append((tmpl, 0))

    return samples


# ── Pipeline ──────────────────────────────────────────────────────────────────

def build_pipeline() -> Pipeline:
    word_tfidf = TfidfVectorizer(
        analyzer="word",
        ngram_range=(1, 3),
        min_df=1,
        max_features=30_000,
        sublinear_tf=True,
    )
    char_tfidf = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(2, 4),
        min_df=1,
        max_features=30_000,
        sublinear_tf=True,
    )

    features = FeatureUnion([
        ("word", word_tfidf),
        ("char", char_tfidf),
    ])

    clf = LogisticRegression(
        C=1.0,
        class_weight="balanced",
        max_iter=500,
        solver="lbfgs",
        n_jobs=-1,
    )

    return Pipeline([("features", features), ("clf", clf)])


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Train illegal-ad classifier")
    parser.add_argument("--input", default=None, help="CSV file with text,label columns")
    parser.add_argument("--reviewed-db", default=None, help="SQLite DB path to train from analyst_reviews")
    parser.add_argument("--allow-synthetic-bootstrap", action="store_true", help="Explicitly allow synthetic bootstrap data")
    parser.add_argument("--output", default="../data/models/classifier.joblib")
    parser.add_argument("--lexicon-dir", default="../data/lexicons")
    args = parser.parse_args()

    # ── Load data ─────────────────────────────────────────────────────────────
    samples: list[tuple[str, int]] = []

    if args.reviewed_db and Path(args.reviewed_db).exists():
        import sqlite3
        conn = sqlite3.connect(args.reviewed_db)
        rows = conn.execute(
            """
            SELECT m.text, ar.label
            FROM analyst_reviews ar
            JOIN alerts a ON ar.target_type = 'alert' AND ar.target_id = a.id
            JOIN messages m ON a.message_id = m.id
            WHERE ar.label IN ('confirmed_relevant', 'false_positive', 'benign_or_news')
            UNION ALL
            SELECT m.text, ar.label
            FROM analyst_reviews ar
            JOIN messages m ON ar.target_type = 'message' AND ar.target_id = m.id
            WHERE ar.label IN ('confirmed_relevant', 'false_positive', 'benign_or_news')
            """
        ).fetchall()
        for txt, lbl in rows:
            if txt and txt.strip():
                samples.append((txt, 1 if lbl == "confirmed_relevant" else 0))
        conn.close()
        logger.info("Loaded %d analyst-reviewed real samples from DB", len(samples))

    if args.input and Path(args.input).exists():
        logger.info("Loading training data from %s", args.input)
        with open(args.input, encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                text = row.get("text") or row.get("message") or ""
                label_raw = row.get("label") or row.get("class") or "0"
                try:
                    label = int(label_raw)
                except ValueError:
                    label = 1 if label_raw.lower() in ("1", "yes", "true", "positive") else 0
                if text.strip():
                    samples.append((text, label))
        logger.info("Loaded %d labelled samples", len(samples))

    if not samples:
        if not args.allow_synthetic_bootstrap:
            logger.error(
                "No real reviewed data provided (--reviewed-db or --input). "
                "Refusing to train on synthetic data without --allow-synthetic-bootstrap."
            )
            sys.exit(1)
        logger.warning("Using synthetic bootstrap data (do NOT enable USE_ML_SCORING without real evaluation).")
        samples.extend(generate_synthetic_data(args.lexicon_dir))

    if len(samples) < 20:
        logger.error("Not enough data to train.")
        sys.exit(1)

    texts = [s[0] for s in samples]
    labels = [s[1] for s in samples]

    # ── Train ─────────────────────────────────────────────────────────────────
    pipeline = build_pipeline()

    logger.info("Running 5-fold cross-validation…")
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    preds = cross_val_predict(pipeline, texts, labels, cv=cv)
    logger.info("\n%s", classification_report(labels, preds, digits=4))

    logger.info("Fitting final model on all data…")
    pipeline.fit(texts, labels)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, out_path)
    logger.info("Model saved to %s", out_path)


if __name__ == "__main__":
    main()
