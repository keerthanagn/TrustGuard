"""Reproducible, idempotent batch import of Indian central legislation from official sources.

Reuses the existing ingestion engine (retrieval.kb_manager.KnowledgeBase.ingest): statute-aware
chunking, SHA-256 dedup, scanned-PDF detection, and the provenance schema. Imported documents enter
as status=unreviewed.

Behaviour:
  - Reads config/corpus_manifest.yaml.
  - Skips an Act already indexed (same title) so re-running retries only the failures.
  - Tries each official source URL in order, with a timeout and bounded retries, and verifies the
    %PDF- header before ingesting. Never substitutes an unofficial mirror for a primary source.
  - Prints and saves a per-document report (source used, HTTP result, SHA-256, pages, chunks, sections,
    extraction/index status) to reports/corpus_import.json.

Usage:
    python -m scripts.import_corpus                 # import all pending documents
    python -m scripts.import_corpus --dry-run       # show what would be imported, download nothing
    python -m scripts.import_corpus --only RTI CPA  # restrict to certain act codes
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import requests
import yaml

from config.settings import get_settings
from core.errors import InputValidationError
from database.db import Database
from retrieval.kb_manager import KnowledgeBase

MANIFEST = Path("config/corpus_manifest.yaml")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TrustGuard/1.0 corpus-importer"
LICENCE = "Government of India - official public legal document"


def _curl_fetch(url: str, dest: Path, timeout: int) -> bool:
    """Fallback fetch via curl.exe (ships with Windows; uses the OS TLS/Schannel stack, which some
    government hosts need where Python's requests raises SSLError). Returns True on a valid PDF."""
    curl = shutil.which("curl") or shutil.which("curl.exe")
    if not curl:
        return False
    try:
        subprocess.run([curl, "-sS", "-L", "--max-time", str(timeout), "-A", UA, "-o", str(dest), url],
                       check=True, capture_output=True, timeout=timeout + 15)
    except (subprocess.SubprocessError, OSError):
        return False
    return dest.exists() and dest.stat().st_size > 1024 and dest.read_bytes()[:5] == b"%PDF-"


def download(urls: list[str], dest: Path, timeout: int = 90, retries: int = 2) -> dict:
    """Try each URL in order with bounded retries, then a curl fallback. Returns a result dict (never raises)."""
    attempts = []
    for url in urls:
        for attempt in range(retries + 1):
            try:
                r = requests.get(url, timeout=timeout, headers={"User-Agent": UA})
                status = r.status_code
                if status == 200 and r.content[:5] == b"%PDF-":
                    dest.write_bytes(r.content)
                    return {"ok": True, "url": url, "http": status, "bytes": len(r.content),
                            "via": "requests", "attempts": attempts}
                attempts.append({"url": url, "http": status,
                                 "note": "not a PDF" if status == 200 else "http error"})
                break  # non-retryable (wrong content / 4xx): move to next URL
            except requests.RequestException as exc:
                attempts.append({"url": url, "error": type(exc).__name__})
                time.sleep(min(2 ** attempt, 4))
        # requests failed for this URL (e.g. SSLError on some gov hosts) -> try curl via the OS TLS stack
        if _curl_fetch(url, dest, timeout):
            return {"ok": True, "url": url, "http": 200, "bytes": dest.stat().st_size,
                    "via": "curl", "attempts": attempts}
        attempts.append({"url": url, "note": "curl fallback failed"})
    return {"ok": False, "url": None, "attempts": attempts}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", nargs="+", default=None, help="restrict to these act codes")
    args = ap.parse_args()

    settings = get_settings()
    db = Database(settings.path("db_path"))
    kb = KnowledgeBase(settings, db)
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["documents"]
    if args.only:
        want = {c.upper() for c in args.only}
        manifest = [m for m in manifest if m["act_code"] in want]

    existing_titles = {d["title"]: d for d in db.list_documents()}
    seed_dir = settings.path("data_dir") / "seed_pdfs"
    seed_dir.mkdir(parents=True, exist_ok=True)

    report = []
    for item in manifest:
        entry = {"act_code": item["act_code"], "title": item["title"]}
        prior = existing_titles.get(item["title"])
        if prior and prior["index_status"] == "indexed":
            entry.update({"result": "skipped (already indexed)", "doc_id": prior["doc_id"],
                          "chunks": prior["chunks"], "sections": prior["sections"],
                          "status": prior["status"]})
            report.append(entry)
            print(f"SKIP  {item['act_code']:<6} already indexed ({prior['chunks']} chunks)")
            continue
        if args.dry_run:
            entry["result"] = "would import"
            report.append(entry)
            print(f"DRY   {item['act_code']:<6} {item['sources'][0]}")
            continue

        print(f"GET   {item['act_code']:<6} ...")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_pdf = Path(tmp) / f"{item['act_code'].lower()}.pdf"
            dl = download(item["sources"], tmp_pdf)
            entry["download"] = dl
            if not dl["ok"]:
                entry["result"] = "download failed (retryable)"
                report.append(entry)
                print(f"FAIL  {item['act_code']:<6} all sources unreachable; will retry on next run")
                continue
            try:
                doc = kb.ingest(tmp_pdf, title=item["title"], act_code=item["act_code"],
                                ref_type=item.get("ref_type", "Section"), status="unreviewed",
                                provenance="official_download", source_url=dl["url"],
                                version=item.get("version", ""), notes=item.get("notes", ""),
                                doc_type="legislation", jurisdiction="India",
                                effective_date=item.get("effective_date", ""), licence=LICENCE)
                entry.update({"result": "indexed", "doc_id": doc["doc_id"], "source_url": dl["url"],
                              "sha256": doc["sha256"][:16], "pages": doc["pages"],
                              "chunks": doc["chunks"], "sections": doc["sections"],
                              "status": doc["status"]})
                print(f"OK    {item['act_code']:<6} {doc['pages']}p {doc['chunks']}ch {doc['sections']}sec "
                      f"<- {dl['url'].split('/')[2]}")
            except InputValidationError as exc:
                entry["result"] = f"ingestion rejected: {exc}"
                report.append(entry)
                print(f"REJECT {item['act_code']:<6} {exc}")
                continue
        report.append(entry)

    out = settings.path("reports_dir") / "corpus_import.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    ok = sum(1 for r in report if r.get("result") == "indexed")
    skip = sum(1 for r in report if str(r.get("result", "")).startswith("skipped"))
    fail = sum(1 for r in report if "fail" in str(r.get("result", "")).lower())
    print(f"\nImported {ok}, skipped {skip}, failed {fail}. Report -> {out}")


if __name__ == "__main__":
    main()
