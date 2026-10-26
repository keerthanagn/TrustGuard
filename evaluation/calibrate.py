"""Threshold calibration on the DEVELOPMENT set only.

Sweeps the two verification thresholds that most affect the release decision - the NLI entailment
threshold and the minimum evidence-relevance threshold - and selects the pair that maximises the
middleware's F1 at distinguishing answers that should be released from answers that should be withheld,
on dev.jsonl. The chosen values are written to config/calibrated.yaml.

This script NEVER reads test.jsonl. The test set is used only by run_eval.py for final reporting, so
thresholds are frozen before any test-set measurement (no test-set tuning).

Usage:
    python -m evaluation.calibrate                 # scripted backend (deterministic, fast)
    python -m evaluation.calibrate --llm ollama
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from config.settings import get_settings
from database.db import Database
from evaluation.harness import load_split, run_item
from retrieval.index import registry

ENTAIL_GRID = [0.50, 0.55, 0.65]
MINREL_GRID = [0.30, 0.35, 0.45]
OUT = Path("config/calibrated.yaml")


def score(records: list[dict]) -> dict:
    """F1 treating 'correctly handled' per the label as the target, balanced across release/withhold."""
    tp = sum(1 for r in records if r["expected_release"] and r["released"])          # correct release
    fn = sum(1 for r in records if r["expected_release"] and not r["released"])      # valid answer rejected
    tn = sum(1 for r in records if not r["expected_release"] and not r["released"])  # correct withhold
    fp = sum(1 for r in records if not r["expected_release"] and r["released"])      # bad answer released
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    # balanced accuracy rewards both catching bad answers and not over-withholding good ones
    tpr = tp / (tp + fn) if (tp + fn) else 0.0
    tnr = tn / (tn + fp) if (tn + fp) else 0.0
    return {"f1": f1, "balanced_acc": (tpr + tnr) / 2, "rejected_valid": fp == 0 and fn,
            "released_bad": fp, "valid_rejected": fn}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", choices=["scripted", "ollama"], default="scripted")
    args = ap.parse_args()

    settings = get_settings()
    db = Database(settings.path("db_path"))
    index = registry.get(settings, db)
    dev = load_split("dev")
    print(f"Calibrating on {len(dev)} DEV items ({args.llm} backend). Test set is not touched.\n")

    results = []
    for entail in ENTAIL_GRID:
        for min_rel in MINREL_GRID:
            overrides = {"verification": {"entail_threshold": entail}, "retrieval": {"min_relevance": min_rel}}
            s = settings.with_overrides(overrides)
            recs = [run_item(s, db, index, it, "trustguard", args.llm) for it in dev]
            m = score(recs)
            m.update({"entail_threshold": entail, "min_relevance": min_rel})
            results.append(m)
            print(f"  entail={entail:.2f} min_rel={min_rel:.2f} -> balanced_acc={m['balanced_acc']:.3f} "
                  f"F1={m['f1']:.3f} (bad_released={m['released_bad']}, valid_rejected={m['valid_rejected']})")

    # prefer: no bad answer released, then highest balanced accuracy, then fewest valid rejections
    best = sorted(results, key=lambda m: (m["released_bad"], -m["balanced_acc"], m["valid_rejected"]))[0]
    chosen = {"verification": {"entail_threshold": best["entail_threshold"]},
              "retrieval": {"min_relevance": best["min_relevance"]}}
    OUT.write_text(
        "# Thresholds calibrated on evaluation/datasets/dev.jsonl ONLY (see evaluation/calibrate.py).\n"
        "# Loaded automatically over config/default.yaml. Do not hand-edit; re-run calibration instead.\n"
        + yaml.safe_dump(chosen, sort_keys=False), encoding="utf-8")
    print(f"\nSelected: entail_threshold={best['entail_threshold']}, min_relevance={best['min_relevance']} "
          f"(balanced_acc={best['balanced_acc']:.3f}). Written to {OUT}.")


if __name__ == "__main__":
    main()
