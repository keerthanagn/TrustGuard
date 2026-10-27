"""Shared pytest fixtures: a tiny in-memory-style knowledge base built from fixture text, so unit and
integration tests run fast and do not require Ollama or the full seed corpus."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import load_settings
from core.models import Chunk
from database.db import Database

# Minimal statutory fixtures (paraphrased/short, for testing the pipeline, not authoritative law).
FIXTURE_CHUNKS = [
    ("BNS", "103", "Section", "Punishment for murder",
     "103. (1) Whoever commits murder shall be punished with death or imprisonment for life, and shall also be "
     "liable to fine."),
    ("BNS", "303", "Section", "Theft",
     "303. (2) Whoever commits theft shall be punished with imprisonment of either description for a term which "
     "may extend to three years, or with fine, or with both and in case of second or subsequent conviction of "
     "any person under this section, he shall be punished with rigorous imprisonment for a term which shall not "
     "be less than one year but which may extend to five years and with fine."),
    ("BNS", "295", "Section", "Sale, etc., of obscene objects to child",
     "295. Whoever sells or distributes to any child any obscene object shall be punished on first conviction "
     "with imprisonment which may extend to three years and with fine, and in the event of a second or "
     "subsequent conviction, with rigorous imprisonment for a term which shall not be less than one year but "
     "which may extend to five years and with fine."),
    ("BNS", "307", "Section", "Theft after preparation made for causing death, hurt or restraint",
     "307. Whoever commits theft, having made preparation for causing death, or hurt, or restraint, shall be "
     "punished with rigorous imprisonment for a term which may extend to ten years, and shall also be liable to fine."),
    ("BNS", "309", "Section", "Punishment for robbery",
     "309. (4) Whoever commits robbery shall be punished with rigorous imprisonment for a term which may extend "
     "to ten years and shall also be liable to fine."),
    ("BNS", "318", "Section", "Cheating",
     "318. (4) Whoever cheats shall be punished with imprisonment of either description for a term which may "
     "extend to three years, or with fine, or with both."),
    ("ITA", "66C", "Section", "Punishment for identity theft",
     "66C. Whoever, fraudulently or dishonestly makes use of the electronic signature, password or any other "
     "unique identification feature of any other person, shall be punished with imprisonment of either description "
     "for a term which may extend to three years and shall also be liable to fine which may extend to rupees one lakh."),
    ("ITA", "66A", "Section", "Offensive messages",
     "66A. Punishment for sending offensive messages through communication service. (This provision is reproduced "
     "from the Act text.)"),
    ("COI", "21", "Article", "Protection of life and personal liberty",
     "21. No person shall be deprived of his life or personal liberty except according to procedure established by law."),
    ("COI", "20", "Article", "Protection in respect of conviction for offences",
     "20. (1) No person shall be convicted of any offence except for violation of a law in force at the time of "
     "the commission of the act charged as an offence. (2) No person shall be prosecuted and punished for the "
     "same offence more than once. (3) No person accused of any offence shall be compelled to be a witness "
     "against himself."),
    ("COI", "17", "Article", "Abolition of Untouchability",
     "17. Untouchability is abolished and its practice in any form is forbidden. The enforcement of any "
     "disability arising out of untouchability shall be an offence punishable in accordance with law."),
]


@pytest.fixture(scope="session")
def settings(tmp_path_factory):
    s = load_settings()
    base = tmp_path_factory.mktemp("tg")
    s.raw["paths"]["db_path"] = str(base / "test.db")
    s.raw["paths"]["kb_dir"] = str(base / "kb")
    s.raw["retrieval"]["use_semantic"] = False   # BM25-only keeps tests fast and model-free
    s.raw["retrieval"]["use_reranker"] = False
    s.raw["retrieval"]["min_relevance"] = 0.05
    return s


@pytest.fixture(scope="session")
def db(settings):
    database = Database(settings.path("db_path"))
    chunks = []
    docs = {}
    for i, (act, sec, rt, heading, text) in enumerate(FIXTURE_CHUNKS):
        doc_id = f"{act.lower()}-fix"
        docs.setdefault(doc_id, (act, rt))
        chunks.append(Chunk(chunk_id=f"{doc_id}:{i:05d}", doc_id=doc_id, text=text, page_start=1, page_end=1,
                            section=sec, ref_type=rt, heading=heading, act_code=act, ordinal=i))
    for doc_id, (act, rt) in docs.items():
        database.add_document(dict(doc_id=doc_id, title=f"{act} fixture", act_code=act, ref_type=rt,
                                   filename=f"{doc_id}.pdf", sha256=doc_id, status="verified",
                                   index_status="indexed", uploaded_at="2025-01-01T00:00:00+00:00",
                                   pages=1, chunks=0, sections=0))
    database.replace_chunks("bns-fix", [c for c in chunks if c.doc_id == "bns-fix"])
    database.replace_chunks("ita-fix", [c for c in chunks if c.doc_id == "ita-fix"])
    database.replace_chunks("coi-fix", [c for c in chunks if c.doc_id == "coi-fix"])
    return database


@pytest.fixture(scope="session")
def index(settings, db):
    from retrieval.index import HybridIndex
    return HybridIndex(settings=settings, db=db, doc_ids=["bns-fix", "ita-fix", "coi-fix"])
