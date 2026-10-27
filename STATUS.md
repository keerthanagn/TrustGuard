# TrustGuard — project status

Living status of the build. For the dataset/evaluation integrity record see
`evaluation/datasets/STATUS.md`; for the legal corpus see `docs/CORPUS.md`; live dashboard at the
artifact URL in the README.

## Current state

- **Tests:** 107 passing (unit, integration, workflow, rendering, security, corpus-import, retrieval-quality).
- **Corpus:** 7 indexed documents across 6 statutes — BNS, **BNSS**, **BSA**, Constitution, IT Act, **RTI**
  (the three bold ones added in Phase 2 from official sources). Original IT Act 2000 retained as `outdated`.
- **Pending corpus (retryable):** Consumer Protection Act 2019, Motor Vehicles Act 1988, PWDV Act 2005 —
  official source (India Code) returned HTTP 504 at import time; re-run `scripts.import_corpus --only CPA MVA PWDVA`.
- **Evaluation:** dev (tuning) / test (consumed) / final_test_v1 (frozen) splits; metrics computed from saved
  predictions with bootstrap CIs; see the Evaluation Dashboard and `reports/eval/`.

## What works end to end

Interactive Q&A (Streamlit) and REST API through the full middleware: input safety → retrieval → draft
(held) → atomic claims → multi-signal verification → answer safety → bounded repair → strict release or
explainable withholding. Verified live against a local Ollama model.

## Phase progress against the hardening plan

| Phase | State |
|---|---|
| 0 Audit | done (git/tests/corpus reproduced) |
| 1 Error & defect fixes (StageTiming, pyarrow, contrast, fail-closed, theft general-vs-aggravated) | done |
| 2 Corpus expansion | BNSS/BSA/RTI imported & verified; CPA/MVA/PWDVA retryable (source 504) |
| 3 Retrieval & verification | hybrid + rerank + base-provision preference; 9-signal verifier; retrieval metrics |
| 4 UI/UX | 5-page Streamlit workspace |
| 5 Benchmark rigour | splits, manifests, leakage checks, CIs — small, single-reviewer labels (disclosed) |
| 6 Security & engineering | admin gate, audit hash-chain, retention, pinning, API validation |
| 7 Deliverables | README, architecture, corpus, outlines, dashboard |

## Honest limitations

- Benchmark is small and single-reviewer/model-authored (no independent human review yet).
- Newly imported Acts are `unreviewed` (provenance recorded, not yet authenticated against the gazette).
- Three statutes still pending import due to an intermittent official-source outage.
- Court-judgment ingestion (next phase) is designed-for in the schema but not yet populated.
