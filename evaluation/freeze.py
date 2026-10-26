"""Frozen-artifact hashing for reproducible, comparability-preserving evaluation.

Before a final-set evaluation, we capture a single hash over the artefacts that determine behaviour:
the verification/retrieval/safety/middleware source, the active configuration (defaults + calibrated
thresholds), the prompts, and the model id. The hash is stamped into the metrics output so a reported
number is tied to an exact, inspectable system state. If any of these change, the hash changes, and a
prior final-set result must not be reported as comparable.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from config.settings import PROJECT_ROOT, get_settings

# Source files whose logic determines the release decision.
FROZEN_SOURCES = [
    "config/default.yaml", "config/calibrated.yaml", "config/legal_currency.yaml",
    "llm/prompts.py", "llm/structured.py",
    "retrieval/index.py", "retrieval/legal_refs.py", "retrieval/pdf_ingest.py",
    "verification/verifier.py", "verification/claim_extractor.py", "verification/numeric.py",
    "verification/nli.py", "verification/lexical.py", "verification/currency.py",
    "safety/rules.py", "safety/screener.py", "safety/classifier.py",
    "middleware/pipeline.py", "middleware/policy.py",
]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def artifact_hashes() -> dict:
    out = {}
    for rel in FROZEN_SOURCES:
        p = PROJECT_ROOT / rel
        out[rel] = _sha(p.read_bytes())[:16] if p.exists() else "ABSENT"
    return out


def freeze_record(model_id: str | None = None) -> dict:
    s = get_settings()
    files = artifact_hashes()
    combined = _sha(json.dumps(files, sort_keys=True).encode())
    thresholds = {"entail_threshold": s.verification["entail_threshold"],
                  "min_relevance": s.retrieval["min_relevance"],
                  "contradict_threshold": s.verification["contradict_threshold"],
                  "max_retries": s.middleware["max_retries"]}
    return {
        "frozen_artifact_hash": combined[:16],
        "model_id": model_id or s.llm["model"],
        "provider": s.llm.get("provider", "ollama"),
        "thresholds": thresholds,
        "file_hashes": files,
    }


if __name__ == "__main__":
    print(json.dumps(freeze_record(), indent=2))
