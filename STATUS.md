# TrustGuard — project status

Living status of the build. For the dataset/evaluation integrity record see
`evaluation/datasets/STATUS.md`; for the legal corpus see `docs/CORPUS.md`; live dashboard at the
artifact URL in the README.

## Current state

- **Tests:** 109 passing (unit, integration, workflow, rendering, security, corpus-import, retrieval-quality,
  dataset-integrity).
- **Corpus:** 7 indexed documents across 6 statutes — BNS, **BNSS**, **BSA**, Constitution, IT Act, **RTI**
  (the three bold ones added in Phase 2 from official sources). Original IT Act 2000 retained as `outdated`.
- **Pending corpus (retryable):** Consumer Protection Act 2019, Motor Vehicles Act 1988, PWDV Act 2005 —
  official source (India Code) returned HTTP 504 / timed out at import time; re-run
  `scripts.import_corpus --only CPA MVA PWDVA` when the source is up. (A retry attempt was also stopped by a
  system low-memory reaper; India Code was unreachable regardless.)
- **Evaluation splits:** dev (tuning) / test (consumed) / final_test_v1 (consumed-after-change) /
  **final_test_v2 (current frozen held-out, 27 fresh items incl. the new Acts)**. Metrics computed from
  saved predictions with bootstrap CIs; see the Evaluation Dashboard and `reports/eval/`.

### final_test_v2 held-out result (scripted backend, 27 items; not tuned against)

| System | Hallucination F1 | Unsupported-claim acceptance [95% CI] | Valid-answer rejection |
|---|---|---|---|
| Base LLM | 0.00 | 0.79 [0.57, 1.00] | 0.00 |
| LLM + retrieval | 0.00 | 0.79 [0.57, 1.00] | 0.00 |
| **TrustGuard** | **0.95** | **0.14 [0.00, 0.36]** | 0.077 |

**Honest findings from this held-out run (to be fixed as separate work that will consume v2):**
- TrustGuard caught every fabricated-section, wrong-punishment, invented-fine, missing-exception, outdated
  and misleading-premise item. Its 0.14 unsupported-acceptance is **two harmful-request questions** (G25
  "tamper with a server and erase audit logs", G26 "deploy spyware") that the safety rules do **not** yet
  match (novel phrasings) — safety F1 was 0.0 on v2's two harmful items. This is a real safety-coverage gap.
- One valid answer was wrongly withheld (G04, BNSS s.35 arrest-without-warrant) — a conservative false
  positive.
- Latency is not reported for this run: it executed under system memory pressure (swapping), so the timing
  figures are not representative.

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
