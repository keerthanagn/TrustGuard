# Major-Project Report — Outline

**Title:** TrustGuard: An Intelligent Middleware Framework for Hallucination Detection, Legal Fact
Verification, and Malicious-Content Prevention in Large Language Models (Indian Legal Domain)

Suggested length ~60–80 pages. Each chapter lists the artefacts in this repo that supply its evidence.

### Abstract
The problem (LLMs hallucinate confident but false legal claims), the approach (an independent verification
middleware), and the headline measured result (unsupported-claim acceptance reduced vs. base LLM and RAG;
report the figure from `reports/eval/metrics_test.json`, with its confidence interval — do not round away
the uncertainty).

### Chapter 1 — Introduction
- 1.1 Motivation: reliance on LLMs for legal information; cost of hallucinated sections/punishments.
- 1.2 Problem statement and the central research question (can multi-stage middleware reduce unsupported
  legal claims vs. a conventional LLM and a RAG LLM?).
- 1.3 Objectives and scope (Indian statutes: BNS 2023, IT Act 2000, Constitution).
- 1.4 Contributions (independent multi-signal verifier; deterministic legal checks; strict release with
  bounded repair; reproducible three-system evaluation).
- 1.5 Report organisation.

### Chapter 2 — Literature Review / Background
- 2.1 LLM hallucination: taxonomy and causes.
- 2.2 Retrieval-augmented generation and its limits (RAG grounds but does not verify).
- 2.3 Natural Language Inference and entailment-based fact checking.
- 2.4 Claim decomposition and atomic fact verification.
- 2.5 LLM safety / jailbreak / prompt-injection literature.
- 2.6 Legal NLP and Indian legal informatics; the 2023–24 criminal-law reforms (IPC → BNS).
- 2.7 Gap analysis: what TrustGuard adds over self-check and RAG.

### Chapter 3 — System Analysis & Requirements
- 3.1 Functional requirements (verify, screen, repair, release/withhold, explain, audit).
- 3.2 Non-functional requirements (fail-closed, offline-capable, CPU-only, privacy).
- 3.3 Feasibility (hardware: 16 GB CPU laptop; licensing of models and data).
- 3.4 Use cases and actors (end user, administrator/curator, evaluator).

### Chapter 4 — System Design
- 4.1 Architecture overview (reproduce `docs/ARCHITECTURE.md` §2 diagram).
- 4.2 Data model (`core/models.py`): Chunk, Evidence, Claim, ClaimVerification, SafetyResult, TrustReport.
- 4.3 Retrieval design (hybrid fusion + rerank; the DP chunker).
- 4.4 Verification design (the nine signals; decision ordering; fail-closed).
- 4.5 Safety design (layered rules + zero-shot classifier).
- 4.6 Repair loop and strict release policy.
- 4.7 Persistence, reporting, observability.
- 4.8 Design decisions and alternatives rejected (§4 of ARCHITECTURE).

### Chapter 5 — Implementation
- 5.1 Technology stack and versions (`requirements.txt`).
- 5.2 Module walkthrough with key algorithms (chunker DP; RRF; numeric parser; verifier cascade).
- 5.3 Model-adapter layer and configuration system.
- 5.4 UI (Streamlit, 5 pages) and REST API (FastAPI).
- 5.5 Security measures (input validation, prompt-injection neutralisation, secrets handling).
- 5.6 Engineering practices (tests, Docker, structured logging).

### Chapter 6 — Experimental Methodology
- 6.1 Dataset construction and labelling (`evaluation/datasets/`, `schema.md`); every label's `source`.
- 6.2 Dev/test split and the **anti-contamination protocol** (thresholds calibrated on dev only).
- 6.3 The three systems compared (base, RAG, TrustGuard).
- 6.4 Metrics and their definitions (hallucination P/R/F1, unsupported-claim acceptance, valid-answer
  rejection, contradiction-detection, safety P/R/F1, withholding, retry success, latency).
- 6.5 Scripted vs. live-LLM backends and why both are reported.
- 6.6 Bootstrap confidence intervals.

### Chapter 7 — Results & Discussion
- 7.1 Headline three-system comparison (table + bar charts from the Evaluation Dashboard / `metrics_test.json`).
- 7.2 Per-category breakdown (fabricated sections, wrong punishments, outdated law, …).
- 7.3 Effect of retries (retry success rate).
- 7.4 Safety results and the false-positive/false-negative trade-off.
- 7.5 Latency analysis (per-stage timings).
- 7.6 Error analysis: where TrustGuard still fails, and why (be candid).
- 7.7 Threats to validity (dataset size, single jurisdiction, data-quality artefacts).

### Chapter 8 — Conclusion & Future Work
- 8.1 Answer to the research question, stated with its measured uncertainty.
- 8.2 Limitations (§6 of ARCHITECTURE).
- 8.3 Future work (larger annotated corpus; more statutes/jurisdictions; calibrated signal fusion;
  human evaluation; case-law support).

### References
Statutes (BNS 2023, IT Act 2000 & 2008 amendment, Constitution), Shreya Singhal v. Union of India (2015),
and the NLP/safety literature from Chapter 2.

### Appendices
- A. Installation & reproduction commands.
- B. Sample released and withheld reports (`reports/samples/`).
- C. Full benchmark listing (`evaluation/datasets/dev.jsonl`, `test.jsonl`).
- D. Configuration reference (`config/default.yaml`).

> Integrity note for the write-up: cite metrics directly from `reports/eval/metrics_test.json` and never
> state that hallucinations are "eliminated" — report the measured reduction with its confidence interval.
