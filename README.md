# TrustGuard

**An LLM-independent middleware framework for hallucination detection, legal fact verification, and malicious-content prevention — for the Indian legal domain.**

TrustGuard sits between a Large Language Model and the user. It intercepts the model's draft answer, decomposes it into atomic claims, verifies each claim against authoritative legal evidence using multiple independent signals, screens for malicious content, attempts bounded evidence-grounded repair when a draft fails, and **releases an answer only when every mandatory check passes**. Otherwise it withholds the answer and returns an explainable report.

> TrustGuard supports legal **information verification**. It is a research prototype and **not a substitute for a qualified lawyer**.

**Corpus:** 6 Indian statutes (Bharatiya Nyaya Sanhita 2023, Bharatiya Nagarik Suraksha Sanhita 2023,
Bharatiya Sakshya Adhiniyam 2023, Constitution of India, Information Technology Act 2000, Right to
Information Act 2005), imported from official sources (eGazette / India Code). Full inventory and provenance
in [`docs/CORPUS.md`](docs/CORPUS.md); add more via `python -m scripts.import_corpus` (manifest:
`config/corpus_manifest.yaml`). This is a small, fixed corpus — **not all of Indian law**; out-of-corpus
questions are withheld as insufficient evidence.

---

## Why this is not "an LLM with a few keyword checks"

- **Verification is independent of the generating model.** Claims are checked with a separate NLI cross-encoder, deterministic statute/number/punishment logic, a legal-currency registry, and retrieval relevance — never by asking the same LLM "are you sure?".
- **Deterministic legal checks.** Fabricated section numbers, wrong punishments, invented mandatory-minimum fines, and struck-down/repealed provisions are caught by explicit logic, not vibes.
- **Fail-closed.** A verifier crash, an unreachable model, or empty evidence produces a *withhold*, never an unverified release. The retry limit never forces approval.
- **Measured, not asserted.** Three systems (base LLM, RAG, full TrustGuard) are compared on a labelled benchmark with a **held-out test split** and **bootstrap confidence intervals**. No metric is hardcoded.

## Architecture (overview)

```
                        ┌─────────────────────────── TrustGuard middleware ───────────────────────────┐
  user question ──▶ safety screen ─▶ retrieve evidence ─▶ LLM draft ─▶ atomic claims ─▶ verify claims ─┐
                     (block?)         (hybrid: BM25 +      (adapter:     (rule-based or   (NLI + numeric │
                                       FAISS + rerank)      Ollama/        structured)     + statutory + │
                                                            OpenAI-compat)                  currency …)  │
                                                                                                         ▼
   released answer  ◀── strict release policy ◀── bounded repair loop ◀── safety screen ◀── verdicts ───┘
   OR withheld + explainable report
```

Full detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Repository layout

| Path | Purpose |
|---|---|
| `config/` | YAML defaults, env overrides, legal-currency registry, dev-calibrated thresholds |
| `core/` | typed data models, errors, report serialisation, observability |
| `llm/` | model adapters (Ollama, OpenAI-compatible), prompts, structured output, scripted/failing clients |
| `retrieval/` | PDF ingestion + statute-aware chunker, hybrid index, KB manager, legal-reference parser |
| `verification/` | atomic claim extraction, NLI, numeric/punishment logic, legal currency, evidence diagnostics, **verifier** |
| `safety/` | layered rule + zero-shot-classifier malicious-content screener |
| `middleware/` | the pipeline orchestrator and the strict release policy |
| `database/` | SQLite documents/chunks/audit store |
| `evaluation/` | labelled dev/test datasets, calibration, three-system runner, metrics |
| `api/` | FastAPI REST service |
| `app.py`, `app_pages/` | Streamlit application (5 pages) |
| `tests/` | pytest unit + integration suite |

## Hardware & model notes

- Runs on **CPU** (developed on a 16 GB Intel laptop). No GPU required.
- Embedding/NLI models are small (`all-MiniLM-L6-v2`, `ms-marco-MiniLM-L-6-v2`, `nli-deberta-v3-xsmall`) and are cached locally after first download; the app then works offline.
- For very limited hardware, set `retrieval.use_semantic: false` (BM25-only) and `retrieval.use_reranker: false`.
- The LLM runs via **Ollama** locally (default `qwen2.5:3b`, ~2 GB) or any **OpenAI-compatible** endpoint.

## Setup (Windows / PowerShell)

```powershell
# 1. Python 3.11 and Ollama (if not already installed)
winget install Python.Python.3.11
winget install Ollama.Ollama

# 2. Virtual environment + dependencies
cd TrustGuard
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install torch==2.4.1 -r requirements.txt

# 3. Start Ollama and pull a model
ollama serve          # (runs in the background; Ollama for Windows also auto-starts)
ollama pull qwen2.5:3b

# 4. Cache the verification models once (works offline afterwards)
.\.venv\Scripts\python.exe -m scripts.download_models

# 5. Initialise the knowledge base (downloads official legal PDFs if reachable, then indexes them)
.\.venv\Scripts\python.exe -m scripts.init_kb
#   offline / PDFs already present in data/seed_pdfs:
#   .\.venv\Scripts\python.exe -m scripts.init_kb --no-download

# 6. Run the tests
.\.venv\Scripts\python.exe -m pytest -q

# 7. Launch the app
.\.venv\Scripts\python.exe -m streamlit run app.py
#   REST API instead:  .\.venv\Scripts\python.exe -m uvicorn api.server:app --port 8000
```

Linux/macOS: use `python3.11 -m venv .venv` then `.venv/bin/python`.

## Configuration

Defaults live in `config/default.yaml`. Override by (in increasing precedence) editing that file, setting
environment variables `TRUSTGUARD_<SECTION>_<KEY>` (e.g. `TRUSTGUARD_LLM_MODEL=llama3.2:3b`), a `.env`
file (copy `.env.example`), or per-request overrides from the UI/API. Dev-calibrated thresholds in
`config/calibrated.yaml` (produced by `evaluation/calibrate.py`) override the defaults automatically.

Switching LLM backend:

```yaml
llm:
  provider: openai                       # any OpenAI-compatible server
  openai_base_url: http://localhost:1234/v1   # LM Studio / vLLM / llama.cpp-server / OpenRouter / OpenAI
  api_key_env: OPENAI_API_KEY            # key read from this env var; never hardcoded
  model: your-model-id
```

## Evaluation (reproducible)

The methodology avoids test-set contamination (see [`evaluation/datasets/schema.md`](evaluation/datasets/schema.md)):

```powershell
# (a) Calibrate thresholds on the DEV split ONLY -> writes config/calibrated.yaml
.\.venv\Scripts\python.exe -m evaluation.calibrate

# (b) Report on the HELD-OUT TEST split with frozen thresholds + bootstrap 95% CIs
.\.venv\Scripts\python.exe -m evaluation.run_eval --split test             # scripted, deterministic
.\.venv\Scripts\python.exe -m evaluation.run_eval --split test --llm ollama  # live local model
```

Outputs land in `reports/eval/` (`metrics_test.json`, `records_test.json`) and drive the **Evaluation
Dashboard** page. Metrics reported: hallucination-detection precision/recall/F1, **unsupported-claim
acceptance rate** (with CI), valid-answer rejection rate, contradiction-detection rate, safety
precision/recall/F1, withholding rate, retry success rate, and latency. Every per-item prediction is
saved so numbers can be reproduced; nothing is hardcoded.

The scripted backend injects each labelled item's answer (a correct gold answer, or the labelled false
claim for adversarial items) so the **middleware** is measured independently of any one model's quality.

### Dataset integrity (why there are three splits)

See `evaluation/datasets/STATUS.md` and `MANIFEST.json` (SHA-256 per split, leakage reports).

- **`dev.jsonl` (30)** — threshold calibration only.
- **`test.jsonl` (36) — CONSUMED.** Its failures drove code changes during development, so it is no longer
  held-out; numbers on it are *development-informed*.
- **`final_test_v1.jsonl` (33) — FROZEN held-out set.** Provisions are disjoint from `dev` and `test`
  (verified CLEAN by `evaluation/leakage.py`; enforced by `tests/test_datasets.py`), and each run stamps a
  `frozen_artifact_hash` over the decision-governing code+config+prompts+model. Labels are single-reviewer,
  model-authored (no independent human verification yet — a documented limitation).

**Reproducible held-out result — FROZEN set (scripted backend, 33 items; canonical figures in
`reports/eval/metrics_final_test_v1.json`, nothing hardcoded):** TrustGuard reduced the unsupported-claim
acceptance rate to **0.00 [95% CI 0.00–0.00]** versus **0.70 [0.50–0.90]** for both the base LLM and the
retrieval-augmented LLM, at a hallucination-detection F1 of **1.0**, safety F1 **1.0**, and valid-answer
rejection **0.0**. On the *consumed* `test` split the figures were 0.04 / 0.97 (development-informed). The
small sample means the intervals are wide and perfect scores will not survive a larger, independently
labelled set — TrustGuard is *not* claimed to eliminate hallucinations; it measurably reduces them.
Reproduce with `python -m evaluation.run_eval --split final_test_v1`; live-model results depend on the model.

**Retrieval quality (labelled evidence, frozen set; `reports/eval/retrieval_final_test_v1.json`).** Recall@k
and MRR over the gold statutory provisions, comparing retriever configurations (23 items with an in-KB gold
provision; items citing repealed/absent provisions are excluded and counted separately):

| Config | MRR | R@1 | R@5 |
|---|---|---|---|
| BM25 only | 0.86 | 0.83 | 0.91 |
| Hybrid (BM25 + dense) | 0.88 | 0.83 | 0.96 |
| Hybrid + cross-encoder rerank | 0.92 | 0.91 | 0.96 |

Reproduce: `python -m evaluation.retrieval_eval --split final_test_v1`. This quantifies the contribution of
the dense retriever and the reranker rather than assuming them.

## REST API

`uvicorn api.server:app --port 8000` then:

| Method | Path | Purpose | Admin |
|---|---|---|---|
| GET | `/health` | status, document count, backends, `admin_required` | — |
| POST | `/query` | `{question, mode, acts?, model?, max_retries?}` → full report JSON | — |
| GET | `/report/{id}?fmt=json\|markdown\|csv` | stored report (may contain withheld drafts) | 🔒 |
| GET | `/history?text=&decision=` | audit search | 🔒 |
| GET | `/documents` | knowledge-base listing | 🔒 |
| GET | `/admin/audit-integrity` | verify the tamper-evident audit hash chain | 🔒 |
| POST | `/admin/purge?retention_days=N` | delete audit records older than N days | 🔒 |

🔒 endpoints require the `X-Admin-Token` header when `TRUSTGUARD_ADMIN_TOKEN` is set (or
`security.require_admin_token: true`); otherwise they are open in single-user mode. Interactive docs at
`/docs` (Swagger UI). This is a static bearer token suitable for a single-node prototype, not multi-user auth.

## Security & reliability

- Secrets via environment variables only; questions can be stored hashed (`privacy.log_queries: false`).
- Uploaded PDFs are validated (type, magic bytes, size, page count, encryption).
- Retrieved text is treated as **evidence, not instructions**: prompt-injection patterns are flagged and
  neutralised before the model sees them.
- Bounded timeouts and technical retries; system errors are kept distinct from factual failures and never
  become automatic approvals.

## Docker (API)

```powershell
docker build -t trustguard-api .
docker run --rm -p 8000:8000 -v ${PWD}/data:/app/data trustguard-api
```
The container runs the API only; Ollama/models run on the host (set `TRUSTGUARD_LLM_BASE_URL` to reach it).

## License & data provenance

Legal texts are downloaded from official Government of India sources (see `scripts/init_kb.py` for URLs) and
are seeded as `unreviewed` until a curator authenticates them on the Knowledge Base page. The original IT
Act 2000 is seeded as `outdated` (superseded by the 2008 amendment) and excluded from evidence by default.
