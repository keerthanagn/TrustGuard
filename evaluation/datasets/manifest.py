"""Generate MANIFEST.json for the evaluation datasets: integrity hashes, counts, category histograms,
gold-provision sets, split status (active / consumed / frozen), and cross-split leakage reports.

Run:  python -m evaluation.datasets.manifest
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from evaluation.leakage import check_splits, load_split

HERE = Path(__file__).parent

# Honest status of each split (see STATUS.md):
#   active   - may be inspected/used in development
#   consumed - its failures have driven code changes; NOT a held-out set anymore
#   frozen   - the current final evaluation set; must not be used for tuning/debugging
SPLIT_STATUS = {
    "dev": "active",
    "test": "consumed",          # drove code changes on 2026-10-26 (safety rules, verifier, section ranking)
    "final_test_v1": "consumed", # consumed-after-change: Phase 1E/2 code changed its frozen-artifact hash
    "final_test_v2": "consumed", # consumed-after-change: the attribution fix (commit e13ec51) changed the hash
    "final_test_v3": "consumed", # consumed-after-change: safety + scope fixes (commit) changed the hash
    "final_test_v4": "frozen",   # current frozen held-out set (fresh provisions, disjoint from all prior)
    "benchmark": "superseded",
}


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarise(split: str) -> dict:
    path = HERE / f"{split}.jsonl"
    if not path.exists():
        return {"present": False}
    items = load_split(split)
    refs = sorted({r for it in items for r in (it.get("gold_refs") or [])})
    return {
        "present": True,
        "file": f"{split}.jsonl",
        "sha256": _file_sha(path),
        "n_items": len(items),
        "status": SPLIT_STATUS.get(split, "unknown"),
        "categories": dict(sorted(Counter(it["category"] for it in items).items())),
        "gold_provisions": refs,
        "review_status": sorted({it.get("review_status", "unspecified") for it in items}),
        "annotators": sorted({it.get("annotator", "unspecified") for it in items}),
    }


def main() -> None:
    splits = ["dev", "test", "final_test_v1", "final_test_v2", "final_test_v3", "final_test_v4", "benchmark"]
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "Integrity manifest. 'test' is CONSUMED (not held-out). 'final_test_v1' is the current "
                "frozen final set: do not use it to tune thresholds, select models, or debug examples. "
                "All labels are single-reviewer, model-authored (no independent human verification yet) - "
                "see STATUS.md.",
        "splits": {s: summarise(s) for s in splits},
        "leakage": {
            "dev_vs_final_test_v1": check_splits("dev", "final_test_v1"),
            "test_vs_final_test_v1": check_splits("test", "final_test_v1"),
            "dev_vs_final_test_v2": check_splits("dev", "final_test_v2"),
            "test_vs_final_test_v2": check_splits("test", "final_test_v2"),
            "final_test_v1_vs_final_test_v2": check_splits("final_test_v1", "final_test_v2"),
            "dev_vs_final_test_v3": check_splits("dev", "final_test_v3"),
            "test_vs_final_test_v3": check_splits("test", "final_test_v3"),
            "final_test_v1_vs_final_test_v3": check_splits("final_test_v1", "final_test_v3"),
            "final_test_v2_vs_final_test_v3": check_splits("final_test_v2", "final_test_v3"),
            "dev_vs_final_test_v4": check_splits("dev", "final_test_v4"),
            "test_vs_final_test_v4": check_splits("test", "final_test_v4"),
            "final_test_v1_vs_final_test_v4": check_splits("final_test_v1", "final_test_v4"),
            "final_test_v2_vs_final_test_v4": check_splits("final_test_v2", "final_test_v4"),
            "final_test_v3_vs_final_test_v4": check_splits("final_test_v3", "final_test_v4"),
        },
    }
    out = HERE / "MANIFEST.json"
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {out}")
    for s, info in manifest["splits"].items():
        if info["present"]:
            print(f"  {s:<16} {info['status']:<10} n={info['n_items']:<3} sha256={info['sha256'][:16]}")
    for name, rep in manifest["leakage"].items():
        print(f"  leakage {name}: {'CLEAN' if rep['clean'] else 'LEAKAGE'} "
              f"(disallowed_shared_refs={rep['disallowed_shared_refs']}, "
              f"near_dups={len(rep['near_duplicates'])}, allowed_shared={rep['allowed_shared_refs']})")


if __name__ == "__main__":
    main()
