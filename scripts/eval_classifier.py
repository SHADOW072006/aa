"""
Evaluate the illegal-sale classifier against a labelled dataset.

Usage (run from backend/ so the relative lexicon paths resolve):
    python scripts/eval_classifier.py path/to/data.csv
    python scripts/eval_classifier.py path/to/data.json --show 15

The file needs a text column (text/message/content/post/body) and a label
column (label/expected_label/expected_category/ground_truth). Labels map with
the same rule as import validation: benign/clear/0/false -> negative, every
other value (crime category names, "flag"/"illegal"/"1") -> positive.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.classifiers.classifier import classify  # noqa: E402
from app.classifiers.lexicon_loader import init_lexicons  # noqa: E402
from app.collectors.import_handler import _flag_label, _row_fields, _unwrap_json_records  # noqa: E402
from app.core.config import settings  # noqa: E402


def load_rows(path: Path) -> list[dict]:
    raw = path.read_bytes()
    if path.suffix.lower() == ".json":
        return _unwrap_json_records(json.loads(raw.decode("utf-8", errors="replace")))
    if path.suffix.lower() == ".csv":
        return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="replace"))))
    raise SystemExit(f"Unsupported file type: {path.suffix} (use .csv or .json)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", help="Labelled .csv or .json dataset")
    parser.add_argument("--show", type=int, default=10, help="Rows to list per error bucket")
    args = parser.parse_args()

    init_lexicons(
        drug_path=settings.DRUG_LEXICON_PATH,
        financial_path=settings.FINANCIAL_LEXICON_PATH,
        arms_path=settings.ARMS_LEXICON_PATH,
        scam_path=settings.SCAM_LEXICON_PATH,
        extended_path=settings.EXTENDED_LEXICON_PATH,
    )

    rows = load_rows(Path(args.file))
    tp = fp = tn = fn = 0
    category_hits = category_positives = 0
    label_counts: Counter = Counter()
    false_positives, false_negatives, missed_categories = [], [], []

    for idx, row in enumerate(rows):
        fields = _row_fields(row)
        text = fields["text"] or ""
        expected = _flag_label(fields["label"])
        if expected is None:
            continue
        label_counts[fields["label"] or "?"] += 1
        result = classify(text)
        predicted = result.is_flagged

        if expected and predicted:
            tp += 1
            category_positives += 1
            label_value = (fields["label"] or "").strip().lower()
            if label_value and any(label_value in c for c in result.categories):
                category_hits += 1
            else:
                missed_categories.append(
                    (idx, fields["label"], result.categories, text[:90])
                )
        elif expected and not predicted:
            fn += 1
            false_negatives.append((idx, fields["label"], result.reason_codes, text[:90]))
        elif not expected and predicted:
            fp += 1
            false_positives.append(
                (idx, result.risk_level, [t["term"] for t in result.matched_terms][:6], text[:90])
            )
        else:
            tn += 1

    total = tp + fp + tn + fn
    if total == 0:
        raise SystemExit("No usable labelled rows found (need text + label columns).")

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    print(f"file: {args.file}   rows: {len(rows)}   labelled: {total}")
    print(f"label distribution: {dict(label_counts.most_common(10))}")
    print()
    print(f"  TP {tp:>4}   FP {fp:>4}   TN {tn:>4}   FN {fn:>4}")
    print(f"  precision {precision:.3f}   recall {recall:.3f}   F1 {f1:.3f}   "
          f"accuracy {(tp + tn) / total:.3f}")
    if category_positives:
        print(f"  predicted-category matches label: {category_hits}/{category_positives}")
    print()

    if false_negatives:
        print(f"— MISSED positives ({len(false_negatives)}):")
        for idx, label, reasons, preview in false_negatives[: args.show]:
            print(f"  row {idx:<5} [{label}] {reasons} :: {preview!r}")
        print()
    if false_positives:
        print(f"— FALSE positives ({len(false_positives)}):")
        for idx, risk, terms, preview in false_positives[: args.show]:
            print(f"  row {idx:<5} {risk} {terms} :: {preview!r}")
        print()
    if missed_categories:
        print(f"— positives flagged under a different category ({len(missed_categories)}):")
        for idx, label, cats, preview in missed_categories[: args.show]:
            print(f"  row {idx:<5} [{label}] -> {cats} :: {preview!r}")


if __name__ == "__main__":
    main()
