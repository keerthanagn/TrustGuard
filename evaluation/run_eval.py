"""Three-system comparison on the HELD-OUT TEST set, with reproducible per-item predictions and
bootstrap 95% confidence intervals.

Systems:
  base       - LLM only, no retrieval, no verification
  retrieval  - LLM + legal retrieval, no verification gate
  trustguard - full middleware (retrieval + claim verification + safety + bounded repair + strict release)

Backends:
  --llm scripted  (default) deterministic: correct items answered from the gold provision; adversarial
                  items answered with the labelled false claim. Measures the *middleware* reproducibly.
  --llm ollama    live local model via the configured adapter (quality depends on the model).

Thresholds are read from config/calibrated.yaml (produced by evaluation/calibrate.py on the DEV set).
This script never reads dev.jsonl, so reported numbers are on held-out data with frozen thresholds.

Usage:
    python -m evaluation.run_eval
    python -m evaluation.run_eval --split test --llm ollama
    python -m evaluation.run_eval --split dev   # optional: inspect dev behaviour (not the headline result)
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from config.settings import get_settings
from database.db import Database
from evaluation.harness import load_split, run_item
from evaluation.metrics import aggregate_system
from retrieval.index import registry


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", choices=["scripted", "ollama"], default="scripted")
    ap.add_argument("--split", choices=["test", "dev", "final_test_v1", "final_test_v2", "final_test_v3",
                                        "final_test_v4"], default="test")
    ap.add_argument("--systems", nargs="+", default=["base", "retrieval", "trustguard"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="reports/eval")
    args = ap.parse_args()

    settings = get_settings()
    db = Database(settings.path("db_path"))
    index = registry.get(settings, db)
    items = load_split(args.split)
    if args.limit:
        items = items[: args.limit]

    thresholds = {"entail_threshold": settings.verification["entail_threshold"],
                  "min_relevance": settings.retrieval["min_relevance"]}
    calibrated = (Path("config/calibrated.yaml").exists())
    from evaluation.datasets.manifest import SPLIT_STATUS
    from evaluation.freeze import freeze_record
    status = SPLIT_STATUS.get(args.split, "unknown")
    freeze = freeze_record(model_id=settings.llm["model"] if args.llm == "ollama" else "scripted")
    print(f"Split: {args.split} ({len(items)} items, status={status.upper()}) · backend: {args.llm} · "
          f"frozen_artifact_hash={freeze['frozen_artifact_hash']} · "
          f"thresholds {thresholds} ({'calibrated on dev' if calibrated else 'defaults - run calibrate.py'})")
    if status == "consumed":
        print("  WARNING: this split is CONSUMED (its failures drove code changes); results are "
              "development-informed, not held-out. Report final numbers on the FROZEN set instead.")
    elif status == "frozen":
        # Freeze ledger: record the artifact hash seen for this split. If the code/config/model changed
        # since the first recorded run, the set has been observed under multiple states and is effectively
        # consumed - flag it loudly so a stale "held-out" claim cannot be made.
        ledger_path = settings.path("reports_dir") / "eval" / "freeze_ledger.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
        entries = ledger.setdefault(args.split, [])
        prior_hashes = {e["frozen_artifact_hash"] for e in entries}
        status_note = "frozen"
        if prior_hashes and freeze["frozen_artifact_hash"] not in prior_hashes:
            status_note = "consumed_after_change"
            print("  WARNING: the frozen artifacts changed since this set was first evaluated "
                  f"(prior {sorted(prior_hashes)}, now {freeze['frozen_artifact_hash']}). This set is now "
                  "effectively CONSUMED - create final_test_v2 before making new confirmatory claims.")
        else:
            print("  NOTE: frozen final set. If a failure here drives a code change, the artifact hash will "
                  "change and this set will be auto-flagged consumed on the next run.")
        entries.append({"frozen_artifact_hash": freeze["frozen_artifact_hash"], "backend": args.llm,
                        "at": time.strftime("%Y-%m-%d %H:%M:%S")})
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
        status = status_note
    print()

    all_records: dict[str, list[dict]] = {s: [] for s in args.systems}
    raw = []
    t0 = time.time()
    for item in items:
        for system in args.systems:
            rec = run_item(settings, db, index, item, system, args.llm)
            all_records[system].append(rec)
            raw.append(rec)
            flag = "REL" if rec["released"] else ("ABS" if rec["abstained"] else "WTH")
            print(f"  [{system:<10}] {item['id']} {item['category']:<22} -> {flag} ({rec['category']})")

    summary = {
        "split": args.split, "split_status": status, "llm_backend": args.llm, "n_questions": len(items),
        "thresholds": thresholds, "thresholds_source": "config/calibrated.yaml (dev-tuned)" if calibrated else "defaults",
        "frozen_artifacts": freeze,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "elapsed_s": round(time.time() - t0, 1),
        "systems": {s: aggregate_system(r) for s, r in all_records.items()},
    }
    out_dir = settings.path("reports_dir") / Path(args.out).name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"metrics_{args.split}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / f"records_{args.split}.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")

    print(f"\n=== Summary: {args.split} set, {args.llm} backend, {len(items)} questions ===")
    print(f"{'system':<12}{'rel':>5}{'abs':>5}{'wth':>5}{'halluc.F1':>11}"
          f"{'unsup.accept [95% CI]':>24}{'valid.rej':>10}{'safetyF1':>10}{'mean ms':>9}")
    for s in args.systems:
        m = summary["systems"][s]
        ci = m["unsupported_claim_acceptance_ci"]
        ci_s = f"{m['unsupported_claim_acceptance_rate']:.2f} [{ci['lo']:.2f},{ci['hi']:.2f}]"
        abst = sum(1 for r in all_records[s] if r["abstained"])
        print(f"{s:<12}{m['released']:>5}{abst:>5}{m['withheld']-abst:>5}"
              f"{m['hallucination_detection']['f1']:>11}{ci_s:>24}"
              f"{m['valid_answer_rejection_rate']:>10}{m['safety']['f1']:>10}{m['latency_ms']['mean']:>9}")
    rs = summary["systems"].get("trustguard", {}).get("retry_success_rate")
    if rs is not None:
        print(f"\nTrustGuard retry success rate: {rs}")
    print(f"Wrote {out_dir}/metrics_{args.split}.json and records_{args.split}.json")


if __name__ == "__main__":
    main()
