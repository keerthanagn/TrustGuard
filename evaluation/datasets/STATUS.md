# Evaluation dataset status & integrity

Generated artefacts of record: `MANIFEST.json` (per-split SHA-256, counts, categories, leakage reports).
Regenerate with `python -m evaluation.datasets.manifest`; verified by `tests/test_datasets.py`.

## Split status

| Split | Status | n | Role |
|---|---|---|---|
| `dev.jsonl` | **active** | 30 | Threshold calibration (`calibrate.py`) and development. May be inspected and tuned on. |
| `test.jsonl` | **consumed** | 36 | Was a held-out set, but on 2026-10-26 its failures (T03, T05, T22, T33, T34) drove code changes to `safety/rules.py`, `safety/screener.py`, `verification/verifier.py`, `retrieval/index.py`, and a scripted gold answer. **It is no longer held-out**; any metric on it is development-informed. Kept unchanged for history. |
| `final_test_v1.jsonl` | **frozen** | 33 | The current final evaluation set. Must **not** be used to tune thresholds, select models, design rules, or debug examples. Provisions are disjoint from `dev` (leakage check CLEAN). |
| `benchmark.jsonl` | **superseded** | 30 | The original single-file benchmark, replaced by `dev.jsonl`. Retained for history. |

## Anti-leakage protocol (enforced)

- `final_test_v1` shares **no** gold provision, exact question, or near-duplicate phrasing (token-Jaccard ≥ 0.85) with `dev` or the consumed `test` — verified by `evaluation/leakage.py` and the regression tests.
- **Unavoidable overlap, documented:** the `outdated_law` category can only cite the repealed IPC or the struck-down IT Act s.66A (the sole entries in `config/legal_currency.yaml`), so `ITA:66A`/`IPC:*` reuse across splits is allowlisted in `leakage.py` and noted on each item. Categories `harmful_request`, `ambiguous`, and `out_of_scope` have no provision by nature.
- Before a final-set run, `evaluation/freeze.py` hashes the decision-governing source + config + prompts + model id into a single `frozen_artifact_hash`, stamped into the metrics output. If that hash changes, a prior final-set result is **not** comparable.
- **Consumption rule:** if a `final_test_v1` failure leads to a code change, that set becomes *consumed*; create `final_test_v2` (fresh, disjoint provisions) before making confirmatory claims again.

## Honest labelling limitations

- **All labels are single-reviewer and model-authored** (`review_status: single_reviewer_model_authored`, `annotator: model`). There has been **no independent human verification and no second-reviewer adjudication**, which a publishable legal benchmark would require (see project report §Future work). Each item nonetheless carries a human-checkable `source` (a statute citation or case cite) so a human reviewer can validate or overturn it.
- **No truly hidden custodian test set** is maintained (single-developer prototype). This is a known limitation; `final_test_v1` is a newly-collected, provision-disjoint set used as the stand-in, with the freeze-hash providing tamper-evidence instead of a custodian.
