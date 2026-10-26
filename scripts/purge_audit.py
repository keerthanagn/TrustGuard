"""Audit-log maintenance: apply the retention policy and verify tamper-evident integrity.

Usage:
    python -m scripts.purge_audit --verify              # check the hash chain only
    python -m scripts.purge_audit --retention-days 90   # delete records older than 90 days
    python -m scripts.purge_audit                        # apply config privacy.retention_days
"""
from __future__ import annotations

import argparse

from config.settings import get_settings
from database.db import Database


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retention-days", type=int, default=None)
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    s = get_settings()
    db = Database(s.path("db_path"))

    integrity = db.verify_audit_integrity()
    print(f"Audit integrity: {'INTACT' if integrity['intact'] else 'TAMPERED'} "
          f"({integrity['checked']} chained records checked)"
          + ("" if integrity["intact"] else f"; broken at: {integrity['broken_at']}"))
    if args.verify:
        return

    days = args.retention_days if args.retention_days is not None else s.privacy.get("retention_days", 0)
    if not days:
        print("Retention disabled (retention_days=0); no records purged.")
        return
    removed = db.apply_retention(days)
    print(f"Purged {removed} audit record(s) older than {days} days.")
    after = db.verify_audit_integrity()
    print(f"Chain after purge: {'INTACT' if after['intact'] else 'BROKEN (expected: purge truncates the chain prefix)'}")


if __name__ == "__main__":
    main()
