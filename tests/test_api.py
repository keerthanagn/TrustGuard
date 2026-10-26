"""API tests: admin gate on sensitive endpoints, open query/health. Uses FastAPI TestClient; the
pipeline is exercised via the scripted path indirectly (no live model needed for the gated endpoints)."""
import importlib
import os

import pytest
from fastapi.testclient import TestClient


def _client(monkeypatch, token: str | None):
    if token:
        monkeypatch.setenv("TRUSTGUARD_ADMIN_TOKEN", token)
    else:
        monkeypatch.delenv("TRUSTGUARD_ADMIN_TOKEN", raising=False)
    import api.server as server
    importlib.reload(server)  # re-evaluate module-level settings/token
    return TestClient(server.app)


def test_health_open(monkeypatch):
    c = _client(monkeypatch, None)
    r = c.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_admin_endpoints_open_in_single_user_mode(monkeypatch):
    c = _client(monkeypatch, None)  # no token configured -> open
    assert c.get("/documents").status_code == 200
    assert c.get("/history").status_code == 200
    assert c.get("/admin/audit-integrity").status_code == 200


def test_admin_endpoints_locked_with_token(monkeypatch):
    c = _client(monkeypatch, "s3cret")
    assert c.get("/documents").status_code == 401            # missing header
    assert c.get("/documents", headers={"X-Admin-Token": "wrong"}).status_code == 401
    assert c.get("/documents", headers={"X-Admin-Token": "s3cret"}).status_code == 200


def test_report_requires_admin_when_token_set(monkeypatch):
    c = _client(monkeypatch, "s3cret")
    assert c.get("/report/NOPE").status_code == 401          # gate runs before lookup
    # with the token, an unknown id is a clean 404 (not leaked)
    assert c.get("/report/NOPE", headers={"X-Admin-Token": "s3cret"}).status_code == 404


def test_health_reports_admin_required_flag(monkeypatch):
    c = _client(monkeypatch, "s3cret")
    assert c.get("/health").json()["admin_required"] is True


# restore a clean module state for any later imports in the session
@pytest.fixture(autouse=True)
def _cleanup():
    yield
    os.environ.pop("TRUSTGUARD_ADMIN_TOKEN", None)
    import api.server as server
    importlib.reload(server)
