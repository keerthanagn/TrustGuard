"""Retrieval-quality evaluation on labelled evidence: Recall@k and MRR over the gold statutory
provisions, and a comparison of retriever configurations (BM25-only vs hybrid vs hybrid+rerank).

Only items whose gold provision actually exists in the knowledge base are scored, so the metric measures
*ranking quality*, not corpus coverage. Items citing repealed/absent provisions (e.g. IPC sections, which
are intentionally not in the KB) or carrying no gold provision (fabricated-section, ambiguous, harmful)
are excluded and counted separately.

Usage:
    python -m evaluation.retrieval_eval --split final_test_v1
    python -m evaluation.retrieval_eval --split dev --configs bm25 hybrid hybrid_rerank
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from config.settings import get_settings
from database.db import Database
from evaluation.harness import load_split
from evaluation.metrics import bootstrap_ci
from retrieval.index import registry

KS = [1, 3, 5, 10]
CONFIGS = {
    "bm25": {"use_semantic": False, "rerank": False},
    "hybrid": {"use_semantic": True, "rerank": False},
    "hybrid_rerank": {"use_semantic": True, "rerank": True},
}


def ref_str(e) -> str:
    return f"{e.act_code}:{e.section}" if e.section else ""


def first_hit_rank(ranked_refs: list[set[str]], golds: set[str]) -> int | None:
    for i, refs in enumerate(ranked_refs, 1):
        if refs & golds:
            return i
    return None


def evaluate_config(settings, db, name: str, cfg: dict, items: list[dict]) -> dict:
    s = settings.with_overrides({"retrieval": {"use_semantic": cfg["use_semantic"]}})
    index = registry.get(s, db)
    topk = max(KS)
    per_item, recall_vecs = [], {k: [] for k in KS}
    rr_vec, scored, skipped = [], 0, 0
    for it in items:
        golds = {g for g in (it.get("gold_refs") or []) if index.section_exists(*g.split(":", 1))}
        if not golds:
            skipped += 1
            continue
        scored += 1
        ev = index.search(it["question"], top_k=topk, rerank=cfg["rerank"])
        ranked = [{ref_str(e)} if ref_str(e) else set() for e in ev]
        rank = first_hit_rank(ranked, golds)
        rr = 1.0 / rank if rank else 0.0
        rr_vec.append(rr)
        for k in KS:
            recall_vecs[k].append(1.0 if (rank and rank <= k) else 0.0)
        per_item.append({"id": it["id"], "golds": sorted(golds), "first_hit_rank": rank,
                         "top5": [ref_str(e) for e in ev[:5]]})
    return {
        "config": name, "scored_items": scored, "skipped_no_kb_gold": skipped,
        "mrr": bootstrap_ci(rr_vec),
        **{f"recall@{k}": bootstrap_ci(recall_vecs[k]) for k in KS},
        "per_item": per_item,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["test", "dev", "final_test_v1"], default="final_test_v1")
    ap.add_argument("--configs", nargs="+", default=list(CONFIGS), choices=list(CONFIGS))
    ap.add_argument("--out", default="reports/eval")
    args = ap.parse_args()

    settings = get_settings()
    db = Database(settings.path("db_path"))
    items = load_split(args.split)
    t0 = time.time()
    results = [evaluate_config(settings, db, name, CONFIGS[name], items) for name in args.configs]
    summary = {"split": args.split, "n_items": len(items), "ks": KS,
               "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "elapsed_s": round(time.time() - t0, 1),
               "configs": results}
    out_dir = settings.path("reports_dir") / Path(args.out).name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"retrieval_{args.split}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n=== Retrieval quality: {args.split} ({results[0]['scored_items']} scored, "
          f"{results[0]['skipped_no_kb_gold']} excluded: no in-KB gold provision) ===")
    hdr = f"{'config':<16}{'MRR':>8}" + "".join(f"{'R@'+str(k):>9}" for k in KS)
    print(hdr)
    for r in results:
        row = f"{r['config']:<16}{r['mrr']['estimate']:>8.3f}"
        row += "".join(f"{r[f'recall@{k}']['estimate']:>9.3f}" for k in KS)
        print(row)
    print(f"\n95% CIs and per-item ranks in {out_dir}/retrieval_{args.split}.json")


if __name__ == "__main__":
    main()
