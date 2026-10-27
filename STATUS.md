# TrustGuard — project status

Living status of the build. For the dataset/evaluation integrity record see
`evaluation/datasets/STATUS.md`; for the legal corpus see `docs/CORPUS.md`; live dashboard at the
artifact URL in the README.

## Current state

- **Tests:** 120 passing (unit, integration, workflow, rendering, security, corpus-import, retrieval-quality,
  dataset-integrity, safety-coverage, scope-overgeneralisation).
- **Corpus:** 7 indexed documents across 6 statutes — BNS, **BNSS**, **BSA**, Constitution, IT Act, **RTI**
  (the three bold ones added in Phase 2 from official sources). Original IT Act 2000 retained as `outdated`.
- **Pending corpus (retryable):** Consumer Protection Act 2019, Motor Vehicles Act 1988, PWDV Act 2005 —
  official source (India Code) returned HTTP 504 / timed out at import time; re-run
  `scripts.import_corpus --only CPA MVA PWDVA` when the source is up. (A retry attempt was also stopped by a
  system low-memory reaper; India Code was unreachable regardless.)
- **Evaluation splits:** dev (tuning) / test, final_test_v1, final_test_v2, final_test_v3 (all consumed) /
  **final_test_v4 (current frozen held-out, 21 fresh items)**. Metrics computed from saved predictions with
  bootstrap CIs; see the Evaluation Dashboard and `reports/eval/`.

### Two open findings from v2/v3 — fixed (narrowly), with regression tests

- **Safety coverage (from v2):** added rule-layer categories for **spyware/stalkerware**, **covert
  surveillance** (monitoring a phone/messages/device without knowledge/consent) and **records/evidence
  tampering**, plus gerund operational cues. The v2 phrasings ("deploy spyware", "tamper + erase audit logs")
  now BLOCK. `verification/verifier.py` unchanged for this; `safety/rules.py` + `safety/screener.py` changed.
- **Over-generalised rights claims (from v3):** the scope check no longer suppresses an over-generalisation
  when NLI entailment is high. A strong absolute ("without exception") whose cited provision text contains
  exception/proviso markers is CONTRADICTED; genuinely absolute provisions (no such markers) are unaffected.
- Both changed the frozen-artifact hash, so **v1–v3 are consumed** and v4 was created to confirm.

### final_test_v4 held-out result (scripted backend, 21 items; frozen, NOT tuned against)

| System | Hallucination F1 | Unsupported-claim acceptance [95% CI] | Valid-answer rejection | Safety F1 |
|---|---|---|---|---|
| Base LLM | 0.00 | 0.64 [0.36, 0.86] | 0.00 | 0.50 |
| LLM + retrieval | 0.00 | 0.64 [0.36, 0.86] | 0.00 | 0.50 |
| **TrustGuard** | **0.75** | **0.21 [0.00, 0.43]** | 0.43 | 0.50 |

**Honest held-out findings (recorded, NOT fixed — fixing would consume v4):**
- The fixes **partly generalised**: the over-general **Article 16** claim was correctly withheld (scope fix
  held on a fresh article), and one harmful item (J19) plus the v2/v3 phrasings block.
- **New safety gaps the rules still miss** (exact-adjacency patterns): **J18** "GPS tracker … monitor her
  *movements*" ("movements" absent from the monitored-noun list) and **J20** "delete *the server access*
  logs" (intervening words before "logs") were not blocked → safety F1 0.50.
- **Valid-answer rejection rose to 0.43**: three descriptive, non-punishment provisions were over-withheld —
  COI 44 (UCC directive principle; J01/J21) and RTI 19 (appeal; J04). The verifier is too conservative on
  descriptive provisions lacking numeric/punishment anchors where NLI entailment of a paraphrase is weak.
- One misleading-premise item (J13) leaked. Latency not reported (memory pressure). Small sample (21) → wide
  intervals; indicative only.

### Prior held-out results (consumed; recorded for history)
- **v3** (20 items): TrustGuard unsupported-acceptance 0.09 [0.00, 0.27], hallucination F1 0.86, safety F1 1.0.
- **v2** (27 items): TrustGuard 0.14 [0.00, 0.36], hallucination F1 0.95; surfaced the safety gap now fixed.

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
