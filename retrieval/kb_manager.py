"""Knowledge-base administration: ingest, re-index, status changes and removal of legal PDFs."""
from __future__ import annotations

import logging
import re
import shutil
import uuid
from pathlib import Path

import numpy as np

from config.settings import Settings
from core.errors import InputValidationError
from core.models import DocStatus
from database.db import Database, utcnow
from retrieval.index import chunk_view, emb_path, embed_texts, registry
from retrieval.pdf_ingest import (chunk_document, detect_file_type, extract_any, sha256_file,
                                  validate_pdf)

log = logging.getLogger("trustguard.kb")

PROVENANCE = {
    "official_download": "Downloaded from a Government of India website (provenance recorded, text not re-verified)",
    "secondary_official": "Copy published by a government body other than the issuing ministry",
    "user_upload": "Uploaded by an administrator; provenance not independently checked",
}


def safe_filename(name: str) -> str:
    p = Path(name)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", p.stem)[:80].strip("._") or "document"
    ext = p.suffix.lower() if p.suffix.lower() in {".pdf", ".txt", ".docx"} else ".pdf"
    return f"{stem}{ext}"

DOC_TYPES = {"legislation", "judgment", "rules", "notification"}


class KnowledgeBase:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.pdf_dir = settings.path("pdf_dir")
        self.kb_dir = settings.path("kb_dir")
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        self.kb_dir.mkdir(parents=True, exist_ok=True)

    def ingest(self, src: Path, title: str, act_code: str, ref_type: str = "Section",
               status: str = DocStatus.UNREVIEWED.value, provenance: str = "user_upload",
               source_url: str = "", version: str = "", notes: str = "", embed: bool = True,
               doc_type: str = "legislation", jurisdiction: str = "India", court: str = "",
               citation: str = "", effective_date: str = "", amendment_history: str = "",
               licence: str = "") -> dict:
        src = Path(src)
        lim = self.settings.limits
        file_type = detect_file_type(src)
        pages = validate_pdf(src, lim["max_upload_mb"], lim["max_pdf_pages"])
        if status not in {s.value for s in DocStatus}:
            raise InputValidationError(f"Unknown status {status!r}")
        if doc_type not in DOC_TYPES:
            raise InputValidationError(f"doc_type must be one of {sorted(DOC_TYPES)}")
        if not re.fullmatch(r"[A-Z]{2,8}", act_code or ""):
            raise InputValidationError("Act/source code must be 2-8 capital letters, e.g. BNS, ITA, COI, SCI.")
        if ref_type not in {"Section", "Article", "Paragraph"}:
            raise InputValidationError("Reference type must be Section, Article or Paragraph.")
        digest = sha256_file(src)
        existing = self.db.find_by_hash(digest)
        if existing:
            raise InputValidationError(f"This exact file is already in the knowledge base as '{existing['title']}'.")

        doc_id = f"{act_code.lower()}-{uuid.uuid4().hex[:8]}"
        dest = self.pdf_dir / f"{doc_id}__{safe_filename(src.name)}"
        if src.resolve() != dest.resolve():
            shutil.copyfile(src, dest)
        record = dict(doc_id=doc_id, title=title.strip()[:200] or src.stem, act_code=act_code, ref_type=ref_type,
                      filename=dest.name, sha256=digest, version=version[:100], status=status,
                      provenance=provenance if provenance in PROVENANCE else "user_upload",
                      source_url=source_url[:500], notes=notes[:1000], pages=pages, uploaded_at=utcnow(),
                      index_status="pending", doc_type=doc_type, jurisdiction=jurisdiction[:100],
                      court=court[:150], citation=citation[:150], effective_date=effective_date[:40],
                      amendment_history=amendment_history[:500], licence=licence[:200], file_type=file_type)
        self.db.add_document(record)
        try:
            self._index(doc_id, dest, act_code, ref_type, embed)
        except Exception as exc:
            self.db.update_document(doc_id, index_status=f"failed: {exc}"[:200])
            raise
        return self.db.get_document(doc_id)

    def _index(self, doc_id: str, path: Path, act_code: str, ref_type: str, embed: bool) -> None:
        r = self.settings.retrieval
        chunks = chunk_document(doc_id, extract_any(path), act_code, ref_type, r["chunk_chars"], r["chunk_overlap"])
        if not chunks:
            raise InputValidationError("No extractable text found (scanned PDFs need OCR before upload).")
        self.db.replace_chunks(doc_id, chunks)
        if embed and r.get("use_semantic", True):
            vecs = embed_texts(self.settings, [chunk_view(c) for c in chunks])
            p = emb_path(self.kb_dir, doc_id)
            p.parent.mkdir(parents=True, exist_ok=True)
            np.save(p, vecs)
        sections = len({c.section for c in chunks if c.section})
        self.db.update_document(doc_id, chunks=len(chunks), sections=sections, index_status="indexed")
        registry.invalidate()
        log.info("Indexed %s: %d chunks, %d sections", doc_id, len(chunks), sections)

    def reindex(self, doc_id: str) -> dict:
        doc = self.db.get_document(doc_id)
        if not doc:
            raise InputValidationError("Unknown document")
        emb_path(self.kb_dir, doc_id).unlink(missing_ok=True)
        self._index(doc_id, self.pdf_dir / doc["filename"], doc["act_code"], doc["ref_type"], True)
        return self.db.get_document(doc_id)

    def set_status(self, doc_id: str, status: str, reviewer_note: str = "") -> None:
        if status not in {s.value for s in DocStatus}:
            raise InputValidationError(f"Unknown status {status!r}")
        fields = {"status": status, "reviewed_at": utcnow()}
        if reviewer_note:
            doc = self.db.get_document(doc_id) or {}
            fields["notes"] = (doc.get("notes", "") + f"\n[{utcnow()}] {reviewer_note}").strip()[:2000]
        self.db.update_document(doc_id, **fields)
        registry.invalidate()

    def remove(self, doc_id: str) -> None:
        doc = self.db.get_document(doc_id)
        if not doc:
            return
        self.db.delete_document(doc_id)
        emb_path(self.kb_dir, doc_id).unlink(missing_ok=True)
        (self.pdf_dir / doc["filename"]).unlink(missing_ok=True)
        registry.invalidate()
