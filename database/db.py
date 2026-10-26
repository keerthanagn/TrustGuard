"""SQLite persistence: document registry, chunk store and audit log of verification requests."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from core.models import Chunk, TrustReport

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id        TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    act_code      TEXT NOT NULL,
    ref_type      TEXT NOT NULL DEFAULT 'Section',
    filename      TEXT NOT NULL,
    sha256        TEXT NOT NULL UNIQUE,
    version       TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'unreviewed',
    provenance    TEXT NOT NULL DEFAULT 'user_upload',
    source_url    TEXT NOT NULL DEFAULT '',
    notes         TEXT NOT NULL DEFAULT '',
    pages         INTEGER NOT NULL DEFAULT 0,
    chunks        INTEGER NOT NULL DEFAULT 0,
    sections      INTEGER NOT NULL DEFAULT 0,
    index_status  TEXT NOT NULL DEFAULT 'pending',
    uploaded_at   TEXT NOT NULL,
    reviewed_at   TEXT NOT NULL DEFAULT '',
    -- legal provenance (P2)
    doc_type         TEXT NOT NULL DEFAULT 'legislation',  -- legislation | judgment | rules | notification
    jurisdiction     TEXT NOT NULL DEFAULT 'India',
    court            TEXT NOT NULL DEFAULT '',             -- for judgments, e.g. "Supreme Court of India"
    citation         TEXT NOT NULL DEFAULT '',             -- e.g. "(2015) 5 SCC 1"
    effective_date   TEXT NOT NULL DEFAULT '',             -- ISO date the text came into force
    amendment_history TEXT NOT NULL DEFAULT '',
    licence          TEXT NOT NULL DEFAULT '',             -- e.g. "GoI / public document"
    file_type        TEXT NOT NULL DEFAULT 'pdf'           -- pdf | txt | docx
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id       TEXT PRIMARY KEY,
    doc_id         TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    ordinal        INTEGER NOT NULL,
    section        TEXT NOT NULL DEFAULT '',
    ref_type       TEXT NOT NULL DEFAULT 'Section',
    heading        TEXT NOT NULL DEFAULT '',
    act_code       TEXT NOT NULL DEFAULT '',
    page_start     INTEGER NOT NULL,
    page_end       INTEGER NOT NULL,
    text           TEXT NOT NULL,
    injection_flag INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_chunks_section ON chunks(act_code, section);
CREATE TABLE IF NOT EXISTS requests (
    request_id     TEXT PRIMARY KEY,
    created_at     TEXT NOT NULL,
    mode           TEXT NOT NULL,
    question       TEXT NOT NULL,
    question_hash  TEXT NOT NULL,
    model          TEXT NOT NULL,
    decision       TEXT NOT NULL,
    category       TEXT NOT NULL,
    retries        INTEGER NOT NULL,
    total_ms       REAL NOT NULL,
    report_json    TEXT NOT NULL,
    seq            INTEGER,          -- monotonic sequence for the tamper-evident chain
    prev_hash      TEXT NOT NULL DEFAULT '',
    integrity_hash TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_requests_created ON requests(created_at);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self.connect() as con:
            con.executescript(SCHEMA)
            self._migrate(con)

    # Additive migration: ADD COLUMN for provenance fields missing from an older documents table.
    _DOC_MIGRATIONS = {
        "doc_type": "TEXT NOT NULL DEFAULT 'legislation'", "jurisdiction": "TEXT NOT NULL DEFAULT 'India'",
        "court": "TEXT NOT NULL DEFAULT ''", "citation": "TEXT NOT NULL DEFAULT ''",
        "effective_date": "TEXT NOT NULL DEFAULT ''", "amendment_history": "TEXT NOT NULL DEFAULT ''",
        "licence": "TEXT NOT NULL DEFAULT ''", "file_type": "TEXT NOT NULL DEFAULT 'pdf'",
    }

    _REQ_MIGRATIONS = {
        "seq": "INTEGER", "prev_hash": "TEXT NOT NULL DEFAULT ''", "integrity_hash": "TEXT NOT NULL DEFAULT ''",
    }

    def _migrate(self, con) -> None:
        existing = {r["name"] for r in con.execute("PRAGMA table_info(documents)").fetchall()}
        for col, decl in self._DOC_MIGRATIONS.items():
            if col not in existing:
                con.execute(f"ALTER TABLE documents ADD COLUMN {col} {decl}")
        req_cols = {r["name"] for r in con.execute("PRAGMA table_info(requests)").fetchall()}
        for col, decl in self._REQ_MIGRATIONS.items():
            if col not in req_cols:
                con.execute(f"ALTER TABLE requests ADD COLUMN {col} {decl}")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # ---------------------------------------------------------------- documents
    def add_document(self, doc: dict) -> None:
        cols = ", ".join(doc)
        marks = ", ".join("?" for _ in doc)
        with self._lock, self.connect() as con:
            con.execute(f"INSERT INTO documents ({cols}) VALUES ({marks})", list(doc.values()))

    def update_document(self, doc_id: str, **fields) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._lock, self.connect() as con:
            con.execute(f"UPDATE documents SET {sets} WHERE doc_id = ?", [*fields.values(), doc_id])

    def delete_document(self, doc_id: str) -> None:
        with self._lock, self.connect() as con:
            con.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            con.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))

    def get_document(self, doc_id: str) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
        return dict(row) if row else None

    def find_by_hash(self, sha256: str) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM documents WHERE sha256 = ?", (sha256,)).fetchone()
        return dict(row) if row else None

    def list_documents(self) -> list[dict]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM documents ORDER BY act_code, uploaded_at").fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------------------------- chunks
    def replace_chunks(self, doc_id: str, chunks: list[Chunk]) -> None:
        with self._lock, self.connect() as con:
            con.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            con.executemany(
                "INSERT INTO chunks (chunk_id, doc_id, ordinal, section, ref_type, heading, act_code,"
                " page_start, page_end, text, injection_flag) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [(c.chunk_id, c.doc_id, c.ordinal, c.section, c.ref_type, c.heading, c.act_code,
                  c.page_start, c.page_end, c.text, int(c.injection_flag)) for c in chunks])

    def load_chunks(self, doc_ids: list[str] | None = None) -> list[Chunk]:
        q = "SELECT * FROM chunks"
        args: list = []
        if doc_ids is not None:
            if not doc_ids:
                return []
            q += f" WHERE doc_id IN ({','.join('?' for _ in doc_ids)})"
            args = list(doc_ids)
        q += " ORDER BY doc_id, ordinal"
        with self.connect() as con:
            rows = con.execute(q, args).fetchall()
        return [Chunk(chunk_id=r["chunk_id"], doc_id=r["doc_id"], text=r["text"], page_start=r["page_start"],
                      page_end=r["page_end"], section=r["section"], ref_type=r["ref_type"], heading=r["heading"],
                      act_code=r["act_code"], ordinal=r["ordinal"], injection_flag=bool(r["injection_flag"]))
                for r in rows]

    # ---------------------------------------------------------------- audit log
    def save_report(self, report: TrustReport, log_queries: bool = True, store_drafts: bool = True) -> None:
        payload = report.to_dict(include_drafts=store_drafts and log_queries)
        qhash = hashlib.sha256(report.question.encode("utf-8")).hexdigest()
        if not log_queries:
            payload["question"] = f"[not logged; sha256={qhash[:16]}]"
        report_json = json.dumps(payload, ensure_ascii=False)
        with self._lock, self.connect() as con:
            row = con.execute("SELECT seq, integrity_hash FROM requests ORDER BY seq DESC LIMIT 1").fetchone()
            seq = (row["seq"] + 1) if row and row["seq"] is not None else 1
            prev_hash = row["integrity_hash"] if row else ""
            # tamper-evident chain: each record's hash covers the previous hash + this record's key fields
            integrity_hash = hashlib.sha256(
                f"{prev_hash}|{seq}|{report.request_id}|{report.created_at}|{report.decision.value}|"
                f"{report.decision_category}|{qhash}|{report_json}".encode("utf-8")).hexdigest()
            con.execute(
                "INSERT OR REPLACE INTO requests (request_id, created_at, mode, question, question_hash, model,"
                " decision, category, retries, total_ms, report_json, seq, prev_hash, integrity_hash)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (report.request_id, report.created_at, report.mode, payload["question"], qhash, report.model,
                 report.decision.value, report.decision_category, report.retries, report.total_ms,
                 report_json, seq, prev_hash, integrity_hash))

    def get_report(self, request_id: str) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT report_json FROM requests WHERE request_id = ?", (request_id,)).fetchone()
        return json.loads(row["report_json"]) if row else None

    def search_requests(self, text: str = "", decision: str = "", limit: int = 200) -> list[dict]:
        q = ("SELECT request_id, created_at, mode, question, model, decision, category, retries, total_ms"
             " FROM requests WHERE 1=1")
        args: list = []
        if text:
            q += " AND (request_id LIKE ? OR question LIKE ?)"
            args += [f"%{text}%", f"%{text}%"]
        if decision:
            q += " AND decision = ?"
            args.append(decision)
        q += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with self.connect() as con:
            return [dict(r) for r in con.execute(q, args).fetchall()]

    def purge_requests(self, older_than_iso: str) -> int:
        with self._lock, self.connect() as con:
            cur = con.execute("DELETE FROM requests WHERE created_at < ?", (older_than_iso,))
            return cur.rowcount

    def apply_retention(self, retention_days: int) -> int:
        """Delete audit records older than retention_days (privacy-conscious retention). 0 = keep forever."""
        if not retention_days or retention_days <= 0:
            return 0
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat(timespec="seconds")
        return self.purge_requests(cutoff)

    def verify_audit_integrity(self) -> dict:
        """Recompute the hash chain and report whether the audit log is intact (tamper-evident).

        Assumes an append-only log; records with no integrity_hash (pre-migration) are skipped and counted.
        """
        with self.connect() as con:
            rows = con.execute(
                "SELECT seq, request_id, created_at, decision, category, question_hash, report_json,"
                " prev_hash, integrity_hash FROM requests WHERE seq IS NOT NULL ORDER BY seq").fetchall()
        broken, checked, prev_row_hash = [], 0, None
        for r in rows:
            if not r["integrity_hash"]:
                continue
            checked += 1
            # recompute this record's hash from its OWN stored prev_hash (detects content tampering)
            expect = hashlib.sha256(
                f"{r['prev_hash']}|{r['seq']}|{r['request_id']}|{r['created_at']}|{r['decision']}|"
                f"{r['category']}|{r['question_hash']}|{r['report_json']}".encode("utf-8")).hexdigest()
            content_ok = expect == r["integrity_hash"]
            # linkage: each record must point at the previous record's hash (detects deletion/reordering).
            # The first record after a retention purge may have a non-empty prev_hash pointing at a purged
            # record - that boundary is allowed; only mid-chain breaks are flagged.
            link_ok = prev_row_hash is None or r["prev_hash"] == prev_row_hash
            if not content_ok or not link_ok:
                broken.append(r["request_id"])
            prev_row_hash = r["integrity_hash"]
        return {"checked": checked, "intact": not broken, "broken_at": broken}
