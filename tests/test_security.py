"""P3: audit-integrity hash chain, retention, and admin access control."""
import os

from config.settings import load_settings
from core.access import check_admin
from core.models import Decision, TrustReport
from database.db import Database


def _report(rid: str, created_at: str) -> TrustReport:
    r = TrustReport(request_id=rid, question="q " + rid, created_at=created_at, model="m",
                    knowledge_base=["BNS"], mode="trustguard")
    r.decision = Decision.WITHHELD
    r.decision_category = "CONTRADICTED"
    return r


def test_audit_chain_intact(tmp_path):
    db = Database(tmp_path / "a.db")
    for i in range(5):
        db.save_report(_report(f"R{i}", f"2026-01-0{i+1}T00:00:00+00:00"))
    report = db.verify_audit_integrity()
    assert report["checked"] == 5 and report["intact"]


def test_audit_tamper_detected(tmp_path):
    dbfile = tmp_path / "a.db"
    db = Database(dbfile)
    for i in range(4):
        db.save_report(_report(f"R{i}", f"2026-02-0{i+1}T00:00:00+00:00"))
    # tamper with a stored decision directly, bypassing save_report
    with db.connect() as con:
        con.execute("UPDATE requests SET decision='RELEASED' WHERE request_id='R1'")
    report = db.verify_audit_integrity()
    assert not report["intact"] and "R1" in report["broken_at"]


def test_retention_purges_old(tmp_path):
    db = Database(tmp_path / "a.db")
    db.save_report(_report("OLD", "2000-01-01T00:00:00+00:00"))
    db.save_report(_report("NEW", "2099-01-01T00:00:00+00:00"))
    removed = db.apply_retention(retention_days=30)
    assert removed == 1
    assert db.get_report("OLD") is None and db.get_report("NEW") is not None
    # chain must still verify after a prefix purge (purged prefix boundary is allowed)
    assert db.verify_audit_integrity()["intact"]


def test_retention_disabled_keeps_all(tmp_path):
    db = Database(tmp_path / "a.db")
    db.save_report(_report("OLD", "2000-01-01T00:00:00+00:00"))
    assert db.apply_retention(0) == 0 and db.get_report("OLD") is not None


def test_access_single_user_open_without_token(monkeypatch):
    monkeypatch.delenv("TRUSTGUARD_ADMIN_TOKEN", raising=False)
    s = load_settings()
    ok, _ = check_admin(s, None)
    assert ok  # no token configured, require_admin_token false -> open locally


def test_access_token_enforced(monkeypatch):
    monkeypatch.setenv("TRUSTGUARD_ADMIN_TOKEN", "s3cret")
    s = load_settings()
    assert check_admin(s, "wrong")[0] is False
    assert check_admin(s, "s3cret")[0] is True


def test_access_locked_when_required_but_absent(monkeypatch):
    monkeypatch.delenv("TRUSTGUARD_ADMIN_TOKEN", raising=False)
    s = load_settings()
    s.raw.setdefault("security", {})["require_admin_token"] = True
    assert check_admin(s, None)[0] is False  # fail closed
