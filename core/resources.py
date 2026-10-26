"""Lazily-loaded, process-wide model singletons.

Models are loaded from the local Hugging Face cache first so the app works offline after the first
download (scripts/download_models.py). Loading failures raise, and callers decide how to degrade:
retrieval falls back to BM25 only, while verification fails closed (VERIFICATION_ERROR -> withhold).
"""
from __future__ import annotations

import logging
import os
import threading
from functools import lru_cache

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

log = logging.getLogger("trustguard.resources")
_lock = threading.Lock()


def _load(cls, name: str, **kwargs):
    try:
        return cls(name, local_files_only=True, **kwargs)
    except Exception as exc:  # not cached yet -> try the hub once
        log.info("Model %s not in local cache (%s); downloading", name, exc)
        return cls(name, **kwargs)


@lru_cache(maxsize=4)
def get_embedder(name: str):
    from sentence_transformers import SentenceTransformer

    with _lock:
        return _load(SentenceTransformer, name, device="cpu")


@lru_cache(maxsize=4)
def get_cross_encoder(name: str, max_length: int = 512):
    from sentence_transformers import CrossEncoder

    with _lock:
        return _load(CrossEncoder, name, device="cpu", max_length=max_length)
