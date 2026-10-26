"""Initialise the database and index the seed Indian legal corpus.

Usage:
    python -m scripts.init_kb            # download missing PDFs (best effort) and index them
    python -m scripts.init_kb --no-download

Every seed document is registered as 'unreviewed': it was downloaded from a government website, but
its text has not been independently authenticated by a reviewer. Promote a document to 'verified' on the
Knowledge Base page after checking it against the official gazette.
"""
from __future__ import annotations

import argparse
import logging
import tempfile
from pathlib import Path

import requests

from config.settings import get_settings
from database.db import Database
from retrieval.kb_manager import KnowledgeBase

SEED = [
    {
        "file": "bns_2023.pdf", "effective_date": "2024-07-01",
        "title": "Bharatiya Nyaya Sanhita, 2023 (Act 45 of 2023)",
        "act_code": "BNS", "ref_type": "Section", "status": "unreviewed", "provenance": "official_download",
        "version": "Gazette of India, 25 Dec 2023; in force 1 Jul 2024",
        "source_url": "https://egazette.gov.in/WriteReadData/2023/250883.pdf",
        "notes": "Official e-Gazette publication of the Act as enacted.",
    },
    {
        "file": "it_act_2000_amended_2008.pdf", "effective_date": "2009-02-05",
        "title": "Information Technology Act, 2000 (as amended by ITAA 2008)",
        "act_code": "ITA", "ref_type": "Section", "status": "unreviewed", "provenance": "secondary_official",
        "version": "Consolidated text incl. IT (Amendment) Act 2008",
        "source_url": "https://citizen.goapolice.gov.in/documents/10184/1794152/it_act.pdf/5a707136-4540-4913-8d49-bcd193ab6d34",
        "notes": "Consolidated copy hosted by Goa Police. Section 66A text is present but was struck down "
                 "in Shreya Singhal v. Union of India (2015); see config/legal_currency.yaml.",
    },
    {
        "file": "constitution_of_india_2024.pdf", "effective_date": "1950-01-26",
        "title": "Constitution of India (as on 1 May 2024)",
        "act_code": "COI", "ref_type": "Article", "status": "unreviewed", "provenance": "official_download",
        "version": "Legislative Department edition as on 1 May 2024 (incl. 106th Amendment)",
        "source_url": "https://www.legislative.gov.in/static/uploads/2025/07/ca7ce5c746fa7480804bbdeb6cb704f0.pdf",
        "notes": "English text; bilingual front matter in legacy Hindi fonts is skipped during extraction.",
    },
    {
        "file": "it_act_2000_meity.pdf", "effective_date": "2000-10-17",
        "title": "Information Technology Act, 2000 (original 2000 text)",
        "act_code": "ITA", "ref_type": "Section", "status": "outdated", "provenance": "official_download",
        "version": "As enacted, 9 Jun 2000 (pre-2008 amendment)",
        "source_url": "https://www.meity.gov.in/static/uploads/2024/03/ITbill_2000.pdf",
        "notes": "Superseded by the 2008 amendments (e.g. s.66 was substituted). Kept for audit and the "
                 "outdated-law benchmark; excluded from evidence by default.",
    },
]


def download(url: str, dest: Path) -> bool:
    try:
        r = requests.get(url, timeout=120, headers={"User-Agent": "Mozilla/5.0 TrustGuard/1.0"})
        r.raise_for_status()
        if not r.content.startswith(b"%PDF-"):
            return False
        dest.write_bytes(r.content)
        return True
    except requests.RequestException as exc:
        print(f"  download failed: {exc}")
        return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--reset", action="store_true", help="remove existing seed documents first")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    settings = get_settings()
    db = Database(settings.path("db_path"))
    kb = KnowledgeBase(settings, db)
    seed_dir = settings.path("data_dir") / "seed_pdfs"
    seed_dir.mkdir(parents=True, exist_ok=True)
    legacy_dir = settings.path("pdf_dir")

    if args.reset:
        for d in db.list_documents():
            kb.remove(d["doc_id"])

    known = {d["sha256"] for d in db.list_documents()}
    for item in SEED:
        path = seed_dir / item["file"]
        if not path.exists() and (legacy_dir / item["file"]).exists():
            (legacy_dir / item["file"]).replace(path)
        if not path.exists():
            if args.no_download:
                print(f"SKIP {item['file']}: not present")
                continue
            print(f"Downloading {item['title']} ...")
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp) / item["file"]
                if not download(item["source_url"], tmp_path):
                    print(f"SKIP {item['file']}: download failed; place the PDF in {seed_dir} manually")
                    continue
                tmp_path.replace(path)
        from retrieval.pdf_ingest import sha256_file
        if sha256_file(path) in known:
            print(f"OK   {item['title']} (already indexed)")
            continue
        doc = kb.ingest(path, title=item["title"], act_code=item["act_code"], ref_type=item["ref_type"],
                        status=item["status"], provenance=item["provenance"], source_url=item["source_url"],
                        version=item["version"], notes=item["notes"], doc_type="legislation",
                        jurisdiction="India", effective_date=item.get("effective_date", ""),
                        licence="Government of India - official public legal document")
        print(f"OK   {doc['title']}: {doc['pages']} pages, {doc['chunks']} chunks, {doc['sections']} sections")

    print("\nKnowledge base:")
    for d in db.list_documents():
        print(f"  [{d['status']:<10}] {d['doc_id']:<14} {d['title']}  ({d['index_status']})")


if __name__ == "__main__":
    main()




