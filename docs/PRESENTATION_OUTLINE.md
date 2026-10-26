# Presentation Outline (~15 slides, ~15–20 min)

1. **Title** — TrustGuard; your name, guide, department, year. One-line tagline: "verifying what the LLM says
   about the law, before the user sees it."

2. **The problem** — a screenshot of an LLM confidently citing a *fabricated* section or a *wrong* punishment.
   Why this is dangerous in the legal domain. The IPC→BNS 2023 transition makes outdated answers common.

3. **Research question** — can a multi-stage middleware reduce unsupported/hallucinated legal claims vs. a
   plain LLM and a RAG LLM?

4. **Key idea** — verification must be *independent* of the model that generated the answer. (Contrast with
   "ask the model if it's sure" and with plain RAG, which grounds but does not verify.)

5. **Architecture** — the pipeline diagram (safety → retrieve → generate → claims → verify → repair → release).
   Emphasise *fail-closed*.

6. **Knowledge base & retrieval** — official Indian statutes; statute-aware chunking with section/page
   provenance; hybrid BM25 + dense + rerank; traceable citations.

7. **Atomic claim verification** — decompose into claims; the nine independent signals; show one claim going
   SUPPORTED and one going CONTRADICTED with the evidence.

8. **Deterministic legal checks** — live mini-demo on slides: fabricated section, wrong punishment, invented
   minimum fine, struck-down s.66A, repealed IPC. These are caught by logic, not by the LLM.

9. **Safety screening** — legal discussion vs. operational harm; SAFE/REVIEW/BLOCK; a benign question allowed,
   a harmful request blocked.

10. **Bounded repair & strict release** — the repair prompt built from failed claims; re-verification; the
    retry limit never forces approval.

11. **Explainable report** — the released/withheld decision with claim-by-claim evidence, citations, retry
    history, timings; JSON/CSV/Markdown export.

12. **Evaluation methodology** — dev/test split, anti-contamination (tune on dev, report on test), three
    systems, bootstrap confidence intervals. Stress: *no hardcoded results*.

13. **Results** — the three-system table and bar charts from the Evaluation Dashboard. Report the measured
    unsupported-claim-acceptance reduction **with its CI**. Be honest about remaining failures.

14. **Live demo** — follow `docs/DEMO_PLAN.md`: normal, hallucinated, malicious, insufficient-evidence,
    technical-failure.

15. **Contributions, limitations, future work, Q&A** — what's novel, what's not solved, what's next. Close
    with the disclaimer: information verification, not legal advice.

**Demo backup:** have `reports/samples/*.md` and a recorded screen capture ready in case Ollama is slow on
the presentation machine.
