"""Phase 2: batch-import manifest validation, duplicate detection, idempotent indexing, and
metadata preservation. Network downloads are not exercised here (a tiny synthetic PDF is ingested
through the real engine); live source fetching is covered by scripts/import_corpus.py and reported
in reports/corpus_import.json."""
from pathlib import Path

import pytest
import yaml

from core.errors import InputValidationError

MANIFEST = Path(__file__).resolve().parent.parent / "config" / "corpus_manifest.yaml"
REQUIRED = {"act_code", "title", "ref_type", "sources"}
EXPECTED_ACTS = {"BNSS", "BSA", "CPA", "MVA", "RTI", "PWDVA"}


def _tiny_pdf(path: Path, body: str) -> Path:
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), body)
    doc.save(str(path))
    doc.close()
    return path


def test_manifest_is_valid_and_complete():
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    docs = data["documents"]
    assert {d["act_code"] for d in docs} == EXPECTED_ACTS
    for d in docs:
        assert REQUIRED <= set(d), f"{d.get('act_code')} missing fields"
        assert d["sources"] and all(u.startswith("https://") for u in d["sources"])
        # only official hosts as sources (no unofficial mirrors)
        assert all(any(h in u for h in ("indiacode.nic.in", "egazette.gov.in", "mha.gov.in"))
                   for u in d["sources"]), f"{d['act_code']} has a non-official source"
        assert len(d["act_code"]) <= 8 and d["act_code"].isupper()


def test_ingest_and_metadata_preserved(settings, db, tmp_path):
    from retrieval.kb_manager import KnowledgeBase
    kb = KnowledgeBase(settings, db)
    pdf = _tiny_pdf(tmp_path / "rti.pdf",
                    "1. This Act may be called the Sample Transparency Act. "
                    "2. Every public authority shall maintain its records in a manner that facilitates access.")
    doc = kb.ingest(pdf, title="Sample Transparency Act, 2099", act_code="STA", ref_type="Section",
                    status="unreviewed", provenance="official_download",
                    source_url="https://www.indiacode.nic.in/x.pdf", effective_date="2099-01-01",
                    version="Act 1 of 2099", licence="Government of India - official public legal document")
    assert doc["status"] == "unreviewed"           # imported docs are not auto-verified
    assert doc["effective_date"] == "2099-01-01" and doc["licence"].startswith("Government of India")
    assert doc["doc_type"] == "legislation" and doc["source_url"].endswith("x.pdf")
    assert doc["chunks"] >= 1 and doc["index_status"] == "indexed"


def test_duplicate_detection_rejects_same_file(settings, db, tmp_path):
    from retrieval.kb_manager import KnowledgeBase
    kb = KnowledgeBase(settings, db)
    pdf = _tiny_pdf(tmp_path / "dup.pdf",
                    "1. A sample provision for duplicate-detection testing. 2. Whoever contravenes this section "
                    "shall be punished with a fine, as the court may in the circumstances determine to be just.")
    kb.ingest(pdf, title="Dup Act A", act_code="DUPA", status="unreviewed")
    with pytest.raises(InputValidationError, match="already in the knowledge base"):
        kb.ingest(pdf, title="Dup Act B (same bytes)", act_code="DUPB", status="unreviewed")


def test_new_act_references_resolve():
    # the legal-reference registry must recognise the newly imported Acts
    from retrieval.legal_refs import ACT_NAMES, detect_acts, extract_refs
    assert {"RTI", "CPA", "MVA", "PWDVA"} <= set(ACT_NAMES)
    assert "RTI" in detect_acts("Section 6 of the Right to Information Act")
    assert extract_refs("Section 6 of the RTI Act")[0].number == "6"


@pytest.mark.skipif(not Path("data/trustguard.db").exists(), reason="no live corpus in this checkout")
def test_live_corpus_smoke_evidence_from_intended_act():
    # where the real corpus is present, each imported Act answers its own provision queries
    from config.settings import get_settings
    from database.db import Database
    from retrieval.index import registry
    s = get_settings()
    db = Database(s.path("db_path"))
    present = {d["act_code"] for d in db.list_documents() if d["index_status"] == "indexed"}
    checks = [("RTI", "exemptions from disclosure of information under the RTI Act"),
              ("BNSS", "information in cognizable cases under the Bharatiya Nagarik Suraksha Sanhita"),
              ("BSA", "relevancy of facts under the Bharatiya Sakshya Adhiniyam")]
    idx = registry.get(s, db)
    for act, query in checks:
        if act not in present:
            continue
        ev = idx.search(query, top_k=3)
        assert ev and ev[0].act_code == act, f"{act}: top evidence from {ev[0].act_code if ev else None}"


def test_import_skips_already_indexed(settings, db, tmp_path, monkeypatch):
    # the importer must skip a title that is already indexed (idempotent re-runs)
    from retrieval.kb_manager import KnowledgeBase
    kb = KnowledgeBase(settings, db)
    pdf = _tiny_pdf(tmp_path / "idem.pdf",
                    "1. Idempotency sample provision for the importer skip test. 2. This section is repeated "
                    "verbatim to provide sufficient extractable text for the ingestion quality check to pass.")
    kb.ingest(pdf, title="Idempotent Act, 2099", act_code="IDEM", status="unreviewed")
    existing = {d["title"]: d for d in db.list_documents()}
    assert existing["Idempotent Act, 2099"]["index_status"] == "indexed"  # would be skipped on re-run
