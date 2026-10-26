"""P2: multi-format ingestion, scanned-PDF detection, and provenance schema migration."""
import sqlite3

import pytest

from core.errors import InputValidationError
from retrieval.pdf_ingest import (chunk_document, detect_file_type, extract_any, extract_text_pages)


def test_detect_file_type():
    from pathlib import Path
    assert detect_file_type(Path("a.PDF")) == "pdf"
    assert detect_file_type(Path("a.txt")) == "txt"
    assert detect_file_type(Path("a.docx")) == "docx"
    with pytest.raises(InputValidationError):
        detect_file_type(Path("a.exe"))


def test_txt_extraction_and_chunking(tmp_path):
    f = tmp_path / "law.txt"
    f.write_text("1. This Act may be called the Sample Act and comes into force on a notified date.\n"
                 "2. Whoever contravenes this Act shall be punished with imprisonment up to three years, "
                 "or with fine, or with both as the court may decide in the circumstances.", encoding="utf-8")
    pages = extract_text_pages(f)
    assert pages and "Sample Act" in pages[0].text
    chunks = chunk_document("t", pages, "SMP", "Section")
    assert chunks


def test_docx_extraction(tmp_path):
    docx = pytest.importorskip("docx")
    path = tmp_path / "law.docx"
    d = docx.Document()
    d.add_paragraph("1. This is section one of the sample legislation for testing extraction.")
    d.add_paragraph("2. This is section two describing a penalty of up to two years imprisonment.")
    d.save(str(path))
    pages = extract_any(path)
    assert pages and "section one" in pages[0].text.lower()


def test_scanned_pdf_detected(tmp_path):
    import fitz
    path = tmp_path / "scanned.pdf"
    doc = fitz.open()
    doc.new_page()  # blank page, no text layer -> looks scanned/image-only
    doc.new_page()
    doc.save(str(path))
    doc.close()
    with pytest.raises(InputValidationError, match="scanned or image-only"):
        extract_any(path)


def test_schema_migration_adds_columns(tmp_path):
    # create an OLD-style documents table, then open with Database and confirm new columns appear
    dbfile = tmp_path / "old.db"
    con = sqlite3.connect(dbfile)
    con.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, title TEXT, act_code TEXT, ref_type TEXT,"
                " filename TEXT, sha256 TEXT UNIQUE, version TEXT, status TEXT, provenance TEXT,"
                " source_url TEXT, notes TEXT, pages INT, chunks INT, sections INT, index_status TEXT,"
                " uploaded_at TEXT, reviewed_at TEXT)")
    con.commit(); con.close()
    from database.db import Database
    db = Database(dbfile)
    with db.connect() as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(documents)").fetchall()}
    assert {"doc_type", "court", "citation", "effective_date", "licence", "file_type"} <= cols
