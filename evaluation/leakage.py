"""Split-leakage checks: enforce that evaluation splits do not share underlying provisions, questions,
or near-duplicate phrasings, so a metric on one split is not informed by tuning on another.

Some categories cannot be provision-disjoint by nature (outdated_law can only cite the repealed IPC or
the struck-down s.66A, which are the sole legal-currency-registry entries; harmful_request / ambiguous /
out_of_scope have no provision). Such unavoidable overlaps are reported separately and allowlisted, not
hidden.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DATASETS = Path(__file__).parent / "datasets"
# Provisions whose cross-split reuse is unavoidable and therefore allowed (documented in each item's note).
ALLOWED_SHARED_REFS = {"IPC:420", "IPC:378", "IPC:302", "ITA:66A"}
NEAR_DUP_JACCARD = 0.85  # token-Jaccard above this across splits is flagged as a phrasing near-duplicate


def _norm_tokens(q: str) -> set[str]:
    return set(re.sub(r"[^a-z0-9 ]", " ", q.lower()).split())


def load_split(split: str) -> list[dict]:
    return [json.loads(l) for l in (DATASETS / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip()]


def refs_of(items: list[dict]) -> set[str]:
    return {r for it in items for r in (it.get("gold_refs") or [])}


def check_splits(a: str, b: str) -> dict:
    """Return a report of leakage between two splits (no exception raised; the caller/test decides)."""
    ia, ib = load_split(a), load_split(b)
    shared_refs = (refs_of(ia) & refs_of(ib)) - ALLOWED_SHARED_REFS
    qa = {" ".join(sorted(_norm_tokens(x["question"]))) for x in ia}
    exact_dupes = [x["id"] for x in ib if " ".join(sorted(_norm_tokens(x["question"]))) in qa]
    near = []
    ta = {x["id"]: _norm_tokens(x["question"]) for x in ia}
    for x in ib:
        tx = _norm_tokens(x["question"])
        for aid, av in ta.items():
            u = tx | av
            if u and len(tx & av) / len(u) >= NEAR_DUP_JACCARD:
                near.append({"b": x["id"], "a": aid, "jaccard": round(len(tx & av) / len(u), 2)})
    return {
        "splits": [a, b],
        "disallowed_shared_refs": sorted(shared_refs),
        "allowed_shared_refs": sorted((refs_of(ia) & refs_of(ib)) & ALLOWED_SHARED_REFS),
        "exact_question_duplicates": exact_dupes,
        "near_duplicates": near,
        "clean": not shared_refs and not exact_dupes and not near,
    }


if __name__ == "__main__":
    import sys
    a, b = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else ("dev", "final_test")
    rep = check_splits(a, b)
    print(json.dumps(rep, indent=2))
    print("CLEAN" if rep["clean"] else "LEAKAGE DETECTED")
