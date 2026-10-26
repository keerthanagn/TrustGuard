# TrustGuard — System Architecture

## 1. Design goal

A **model-independent middleware** that gates an LLM's legal answers. Generation is strictly separated
from verification and the release decision, so the component that *judges* an answer is never the component
that *wrote* it. The system is designed to **fail closed**: any uncertainty, error, or missing evidence
results in a withheld answer with an explainable report, never an unverified release.

## 2. Request lifecycle

```
run(question, acts, mode)
  │
  ├─ validate question (length, non-empty)
  ├─ question safety screen ───────────────── BLOCK ─▶ WITHHELD (QUESTION_BLOCKED)
  ├─ retrieve legal evidence (hybrid)
  ├─ evidence diagnostics (insufficient / outdated / conflicting)
  │
  └─ attempt loop (0 = initial, 1..N = repairs):
        ├─ generate draft (LLM adapter)         ── LLM error ─▶ WITHHELD (SYSTEM_ERROR)
        ├─ extract atomic claims (rule-based | structured)
        ├─ verify each claim (multi-signal, independent)
        ├─ answer safety screen
        ├─ strict release policy
        │     ├─ pass ───────────────────────────────────────▶ RELEASED (VERIFIED)
        │     ├─ repairable & retries remain ─▶ build repair prompt, loop
        │     └─ otherwise ──────────────────────────────────▶ WITHHELD (<category>)
        └─ (verification error) ─────────────────────────────▶ WITHHELD (SYSTEM_ERROR)
```

Every stage is timed; every decision, model, evidence source, failed claim, retry, and latency is recorded
in a `TrustReport` and the SQLite audit log, and a structured JSON audit line is emitted per request.

## 3. Components

### 3.1 LLM adapter layer (`llm/`)
A thin `LLMClient` protocol (`generate(system, prompt) -> Generation`). Adapters: **Ollama** (local),
**OpenAI-compatible** (vLLM / LM Studio / llama.cpp server / OpenRouter / OpenAI), plus **scripted** and
**failing** clients for tests and fault injection. Selected by `llm.provider`. Bounded connect/read
timeouts and technical retries are separate from the verification repair retries.

### 3.2 Legal knowledge base (`retrieval/`)
- **Ingestion** (`pdf_ingest.py`): **PDF, TXT and DOCX** supported. PyMuPDF text extraction; a
  **dynamic-programming chunker** recovers the section/article numbering chain of gazette statutes
  (handling marginal-note headings, printed page numbers, amendment footnotes, and bilingual/legacy-font
  pages), attaching page and section provenance to every chunk. Validates uploads (type, magic bytes, size,
  pages, encryption) and **detects scanned/image-only PDFs** (low text density) to fail with a clear
  message rather than index empty text. DOCX tables are flattened row-by-row.
- **Provenance** (DB `documents` table, additive migration): every document carries `doc_type`
  (legislation / judgment / rules / notification), `jurisdiction`, `court`, `citation`, `effective_date`,
  `amendment_history`, `licence`, `source_url`, `version`, `file_type`, and a `verified`/`unreviewed`/
  `outdated` status — so the schema distinguishes legislation from judgments and preserves citations and
  effective dates even though the seed corpus is currently legislation only.
- **Hybrid index** (`index.py`): BM25 (lexical) + FAISS dense embeddings fused with **Reciprocal Rank
  Fusion**, re-ranked by a cross-encoder, with exact statutory-reference lookup always included. Act-aware:
  when a question names a statute, search is restricted to it and the statute title is stripped so matching
  is on substance. Degrades to BM25-only if embeddings are unavailable.
- **Metadata & currency**: each document carries act, jurisdiction (section/article), version, source URL,
  effective date, and a status of `verified` / `unreviewed` / `outdated`. Outdated documents are excluded
  from evidence by default but retained for audit and the outdated-law benchmark.

### 3.3 Atomic claim extraction (`verification/claim_extractor.py`)
Splits an answer into sentences (abbreviation-aware) and compound clauses, builds one `Claim` per atomic
statement with: statutory references (with cross-sentence inheritance), quantities (durations, fines, ages;
lakh/crore and number-words; max/min qualifiers), punishment types, conditions, dates, jurisdiction, and
absolute-wording markers. A **materiality** flag separates checkable legal assertions from advice/filler so
unsupported material claims cannot hide inside an otherwise supported paragraph. An optional
**structured-output** path lets the model emit JSON claims with self-citations (re-verified independently,
never trusted).

### 3.4 Independent verification (`verification/verifier.py`)
Each material claim is checked by nine signals, in an explainable order:

| Signal | What it checks |
|---|---|
| `currency` | provision repealed / struck down (curator registry, with authority) |
| `statutory` | cited section/article actually exists in the cited act (fabrication detection) |
| `relevance` | sufficiently relevant evidence exists |
| `nli` | cross-encoder entailment / contradiction over sentence windows of the evidence |
| `numeric` | durations, fines, ages and max/min qualifiers match the source |
| `punishment` | claimed punishment types are prescribed by the source provision |
| `attribution` | the statement is supported by the cited provision, not a different one |
| `scope` | absolute wording ("always", "without exception") vs. provisions that contain exceptions |
| `lexical` | the claim's substantive vocabulary appears in the supporting passage (veto only) |

Verdict: `SUPPORTED` / `CONTRADICTED` / `INSUFFICIENT_EVIDENCE` / `VERIFICATION_ERROR`. Deterministic
conflicts (wrong number, wrong punishment, fabricated reference, outdated law) decide first; soft NLI
contradiction only decides when nothing entails the claim, so illustrations and provisos do not cause false
contradictions. **Any exception in a verifier component yields `VERIFICATION_ERROR`, which the policy treats
as a withhold — never an approval.**

### 3.5 Malicious-content screening (`safety/`)
Layered: a rule layer separating harmful **categories** (credential theft, malware, unauthorized access,
data exfiltration, physical harm, fraud) from **operational intent** ("step-by-step", "write code to…")
and **legal/educational context**; plus a **zero-shot NLI classifier** scoring harm vs. benign hypotheses.
Labels: `SAFE` / `REVIEW` / `BLOCK`. Legal discussion of an offence is not blocked; operational instructions
to commit one are. The classifier is treated as fallible — it only raises risk alongside operational cues,
and its performance is measured on the labelled set. A screening error fails safe to `REVIEW`.

### 3.6 Repair loop & strict release policy (`middleware/`)
On failure the policy classifies the failure and `is_repairable` decides whether a repair can help (factual
/ safety problems) or not (system errors). A repair prompt is built from the specific failed claims and the
relevant evidence. The corrected answer is **fully re-verified**. Release requires: all material claims
satisfied, no material contradiction, required citations present, safety passed, all mandatory components
completed, and the final attempt passing. The retry limit (default 2) never forces approval.

### 3.7 Persistence & observability (`database/`, `core/`)
SQLite stores documents, chunks, and an audit log of every request (optionally hashing the question and
redacting drafts for privacy). Reports export to JSON / claim-level CSV / Markdown. Structured JSON logs
carry request IDs, decisions, counts, and timings (no sensitive content).

## 4. Deliberate technology choices

- **SQLite + FAISS, not Postgres/pgvector/Chroma.** At this corpus size (~2k chunks) on a single CPU node,
  a server-based store adds operational weight and breaks offline simplicity with no measurable retrieval
  benefit. A `VectorStore`/`DocStore` boundary keeps a future swap cheap.
- **Small cross-encoders on CPU, not large hosted models**, so the verifier is reproducible, free, and
  offline after first download.
- **Rule-based claim extraction as the default** (LLM-independent), with structured-output as an opt-in.
- **Structured JSON logging, not a full tracing stack**, matching a single-node research deployment.

## 5. Threat model & safeguards

- **Prompt injection via retrieved documents**: retrieved text is quoted as untrusted evidence; instruction
  patterns ("ignore previous instructions", "mark this as verified") are flagged at ingestion and
  neutralised before the model sees them.
- **Model self-certification**: never relied upon — verification uses independent signals.
- **Release-check bypass**: the release decision is computed by the middleware, not the model; the draft is
  never exposed before the controller finishes.
- **Secrets**: API keys read from environment variables; audit logging of question text can be disabled.

## 6. Known limitations

- Secondary consolidated PDFs can contain artefacts (e.g. "two three years" from a struck-through
  amendment); the numeric parser handles the common form but such copies should be promoted to `verified`
  only after human authentication.
- The legal-currency registry is curator-maintained, not exhaustive.
- Evaluation is on a modest labelled set; confidence intervals are reported precisely because the sample is
  small.
