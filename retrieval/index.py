"""Hybrid legal retrieval: BM25 (lexical) + FAISS (semantic) -> reciprocal rank fusion -> cross-encoder rerank.

Exact statutory references in the query ("section 66C of the IT Act") are resolved by direct lookup so
that the cited provision itself is always available as evidence when it exists in the knowledge base.
"""
from __future__ import annotations

import logging
import math
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from config.settings import Settings
from core.errors import RetrievalError
from core.models import Chunk, DocStatus, Evidence
from core.resources import get_cross_encoder, get_embedder
from database.db import Database
from retrieval.legal_refs import detect_acts, extract_refs, strip_act_names

log = logging.getLogger("trustguard.retrieval")

STOPWORDS = set("""a an the of and or in on to for by with is are be shall may any such that this which who
whom whose as at from it its into under than other being been has have had not no nor if so do does""".split())


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS and len(t) > 1 or t.isdigit()]


def emb_path(kb_dir: Path, doc_id: str) -> Path:
    return kb_dir / "embeddings" / f"{doc_id}.npy"


def chunk_view(c: Chunk) -> str:
    """Text used for indexing and reranking: heading (marginal note) + body."""
    return f"{c.heading}. {c.text}" if c.heading else c.text


def embed_texts(settings: Settings, texts: list[str]) -> np.ndarray:
    model = get_embedder(settings.retrieval["embedding_model"])
    vecs = model.encode(texts, batch_size=64, show_progress_bar=False, normalize_embeddings=True,
                        convert_to_numpy=True)
    return vecs.astype("float32")


@dataclass
class HybridIndex:
    settings: Settings
    db: Database
    doc_ids: list[str]
    chunks: list[Chunk] = field(default_factory=list)
    docs: dict[str, dict] = field(default_factory=dict)
    semantic_ok: bool = False
    degraded_reason: str = ""

    def __post_init__(self) -> None:
        self.docs = {d["doc_id"]: d for d in self.db.list_documents()}
        self.chunks = self.db.load_chunks(self.doc_ids)
        if not self.chunks:
            raise RetrievalError("The selected knowledge base contains no indexed passages.")
        self._acts = {c.act_code for c in self.chunks}
        # headings are counted twice: they summarise the provision and are short relative to the body
        self._bm25 = BM25Okapi([tokenize(f"{c.heading} {c.heading} {c.text}") for c in self.chunks])
        self._sections: dict[tuple[str, str], list[int]] = {}
        for i, c in enumerate(self.chunks):
            if c.section:
                self._sections.setdefault((c.act_code, c.section), []).append(i)
        self._faiss = None
        self._matrix = None
        if self.settings.retrieval.get("use_semantic", True):
            self._build_semantic()

    # ------------------------------------------------------------------ build
    def _build_semantic(self) -> None:
        kb_dir = self.settings.path("kb_dir")
        try:
            mats = []
            for doc_id in self.doc_ids:
                n = sum(1 for c in self.chunks if c.doc_id == doc_id)
                if n == 0:
                    continue
                p = emb_path(kb_dir, doc_id)
                if p.exists():
                    m = np.load(p)
                    if m.shape[0] != n:
                        raise RetrievalError(f"Embedding cache for {doc_id} is stale; re-index the document.")
                else:
                    m = embed_texts(self.settings, [chunk_view(c) for c in self.chunks if c.doc_id == doc_id])
                    p.parent.mkdir(parents=True, exist_ok=True)
                    np.save(p, m)
                mats.append(m)
            self._matrix = np.vstack(mats).astype("float32")
            try:
                import faiss

                index = faiss.IndexFlatIP(self._matrix.shape[1])
                index.add(self._matrix)
                self._faiss = index
            except ImportError:  # numpy fallback keeps semantic search available
                self._faiss = None
            self.semantic_ok = True
        except Exception as exc:
            self.semantic_ok = False
            self.degraded_reason = f"semantic retrieval unavailable ({exc}); using BM25 only"
            log.warning(self.degraded_reason)

    # ------------------------------------------------------------------ lookups
    def section_exists(self, act_code: str, number: str) -> bool:
        if act_code:
            return (act_code, number) in self._sections
        return any(k[1] == number for k in self._sections)

    def acts(self) -> set[str]:
        return self._acts

    def section_chunks(self, act_code: str, number: str, limit: int = 3) -> list[int]:
        keys = [(act_code, number)] if act_code else [k for k in self._sections if k[1] == number]
        out: list[int] = []
        for k in keys:
            out.extend(self._sections.get(k, [])[:limit])
        return out

    def all_section_chunks(self, act_code: str, number: str) -> list[int]:
        keys = [(act_code, number)] if act_code else [k for k in self._sections if k[1] == number]
        out: list[int] = []
        for k in keys:
            out.extend(self._sections.get(k, []))
        return out

    def rank_section(self, act_code: str, number: str, query: str, top: int = 5) -> list[tuple[int, float]]:
        """Return a cited section's own chunks ranked by relevance to the claim.

        A statute section can span many sub-chunks (definition, illustrations, provisos, the punishment
        subsection); fetching only the first by ordinal can miss the operative text. Ranking the section's
        chunks against the claim surfaces the right sub-chunk (e.g. the punishment clause) for NLI/numeric.
        """
        idxs = self.all_section_chunks(act_code, number)
        if not idxs:
            return []
        if len(idxs) <= top:
            scored = [(i, 1.0) for i in idxs]
        else:
            scored = None
            cfg = self.settings.retrieval
            if cfg.get("use_reranker", True) and cfg.get("reranker_model"):
                try:
                    import math

                    ce = get_cross_encoder(cfg["reranker_model"])
                    logits = ce.predict([(query, chunk_view(self.chunks[i])) for i in idxs],
                                        show_progress_bar=False)
                    scored = [(i, 1.0 / (1.0 + math.exp(-float(lg)))) for i, lg in zip(idxs, np.atleast_1d(logits))]
                except Exception as exc:
                    log.warning("Section rerank failed (%s); falling back", exc)
            if scored is None and self.semantic_ok:
                q = embed_texts(self.settings, [query])[0]
                scored = [(i, float(self._matrix[i] @ q)) for i in idxs]
            if scored is None:
                scored = [(i, 1.0 - n / len(idxs)) for n, i in enumerate(idxs)]  # ordinal fallback
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:top]

    def to_evidence(self, idx: int, score: float, retrievers: list[str]) -> Evidence:
        c = self.chunks[idx]
        d = self.docs.get(c.doc_id, {})
        return Evidence(chunk_id=c.chunk_id, doc_id=c.doc_id, doc_title=d.get("title", c.doc_id),
                        act_code=c.act_code, section=c.section, ref_type=c.ref_type, page_start=c.page_start,
                        page_end=c.page_end, text=c.text, score=round(float(score), 4),
                        doc_status=d.get("status", DocStatus.UNREVIEWED.value), retrievers=retrievers,
                        injection_flag=c.injection_flag)

    # ------------------------------------------------------------------ search
    def _dense(self, query: str, k: int) -> list[int]:
        if not self.semantic_ok:
            return []
        q = embed_texts(self.settings, [query])
        if self._faiss is not None:
            _, idx = self._faiss.search(q, min(k, len(self.chunks)))
            return [int(i) for i in idx[0] if i >= 0]
        scores = self._matrix @ q[0]
        return [int(i) for i in np.argsort(-scores)[:k]]

    def _lexical(self, query: str, k: int) -> list[int]:
        toks = tokenize(query)
        if not toks:
            return []
        scores = self._bm25.get_scores(toks)
        order = np.argsort(-scores)[:k]
        return [int(i) for i in order if scores[i] > 0]

    def search(self, query: str, top_k: int | None = None, rerank: bool | None = None) -> list[Evidence]:
        cfg = self.settings.retrieval
        top_k = top_k or cfg["top_k"]
        cand_k, rrf_k = cfg["candidate_k"], cfg["rrf_k"]
        # When the question names a statute that is in the KB, search only that statute and match on
        # the substance of the question rather than on the statute's title.
        original_query = query
        acts = [a for a in detect_acts(query) if a in self.acts()]
        content_query = strip_act_names(query) if acts else query
        content_query = content_query or query
        pool = cand_k * 4 if acts else cand_k

        def keep(ranking: list[int]) -> list[int]:
            return [i for i in ranking if not acts or self.chunks[i].act_code in acts][:cand_k]

        lexical, dense = keep(self._lexical(content_query, pool)), keep(self._dense(content_query, pool))
        query = content_query
        fused: dict[int, float] = {}
        sources: dict[int, list[str]] = {}
        for name, ranking in (("bm25", lexical), ("dense", dense)):
            for rank, i in enumerate(ranking):
                fused[i] = fused.get(i, 0.0) + 1.0 / (rrf_k + rank + 1)
                sources.setdefault(i, []).append(name)
        # exact statutory references are always considered
        for ref in extract_refs(original_query):
            for i in self.section_chunks(ref.act_code, ref.number):
                fused[i] = fused.get(i, 0.0) + 2.0 / (rrf_k + 1)
                sources.setdefault(i, []).append("section_lookup")
        if not fused:
            return []
        n_channels = 2 if self.semantic_ok else 1
        max_rrf = n_channels / (rrf_k + 1)
        ranked = sorted(fused, key=fused.get, reverse=True)[: max(top_k * 3, 15)]
        use_rerank = cfg.get("use_reranker", True) if rerank is None else rerank
        scores = {i: min(1.0, fused[i] / max_rrf) for i in ranked}
        if use_rerank and cfg.get("reranker_model"):
            try:
                ce = get_cross_encoder(cfg["reranker_model"])
                logits = ce.predict([(query, chunk_view(self.chunks[i])) for i in ranked],
                                    show_progress_bar=False)
                for i, lg in zip(ranked, np.atleast_1d(logits)):
                    rel = 1.0 / (1.0 + math.exp(-float(lg)))
                    # blend: reranker judges relevance, fusion keeps exact-reference hits from being dropped
                    bonus = 0.25 if "section_lookup" in sources[i] else 0.0
                    scores[i] = min(1.0, 0.75 * rel + 0.25 * scores[i] + bonus)
                    if "rerank" not in sources[i]:
                        sources[i].append("rerank")
            except Exception as exc:
                log.warning("Reranker unavailable (%s); using fusion scores", exc)
        best = sorted(ranked, key=lambda i: scores[i], reverse=True)[:top_k]
        return [self.to_evidence(i, scores[i], sources[i]) for i in best]


class RetrieverRegistry:
    """Caches one HybridIndex per knowledge-base selection; invalidated when the KB changes."""

    def __init__(self) -> None:
        self._cache: dict[tuple, HybridIndex] = {}
        self._lock = threading.Lock()
        self.generation = 0

    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()
            self.generation += 1

    def get(self, settings: Settings, db: Database, doc_ids: list[str] | None = None) -> HybridIndex:
        include_outdated = settings.retrieval.get("include_outdated", False)
        docs = [d for d in db.list_documents() if d["index_status"] == "indexed"]
        if doc_ids is not None:
            docs = [d for d in docs if d["doc_id"] in set(doc_ids)]
        if not include_outdated:
            docs = [d for d in docs if d["status"] != DocStatus.OUTDATED.value]
        ids = sorted(d["doc_id"] for d in docs)
        if not ids:
            raise RetrievalError("No indexed, current documents are selected in the knowledge base.")
        key = (tuple(ids), settings.retrieval.get("use_semantic", True), settings.retrieval["embedding_model"],
               self.generation)
        with self._lock:
            if key not in self._cache:
                self._cache[key] = HybridIndex(settings=settings, db=db, doc_ids=ids)
            return self._cache[key]


registry = RetrieverRegistry()
