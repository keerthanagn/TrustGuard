"""Pre-download and cache the verification models so the app works offline afterwards.

Usage:  python -m scripts.download_models
"""
from __future__ import annotations

from config.settings import get_settings


def main() -> None:
    s = get_settings()
    names = [
        ("embedding", s.retrieval["embedding_model"]),
        ("reranker", s.retrieval["reranker_model"]),
        ("nli / safety classifier", s.verification["nli_model"]),
    ]
    from sentence_transformers import CrossEncoder, SentenceTransformer
    for kind, name in names:
        print(f"Downloading {kind}: {name} ...")
        if "cross-encoder" in name or "nli" in name or "ms-marco" in name:
            CrossEncoder(name, device="cpu")
        else:
            SentenceTransformer(name, device="cpu")
    print("\nAll models cached. You can now set HF_HUB_OFFLINE=1 for fully offline operation.")


if __name__ == "__main__":
    main()
