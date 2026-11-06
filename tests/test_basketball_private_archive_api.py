"""NBA protected upload: only admin plus TWO separate flags may change data."""
from datetime import datetime, timezone
import hashlib

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from basketball.research_opening_score import capture as score_capture
from basketball.research_early_advanced_ops import capture as advanced_capture
from basketball.research_private_bundle import export_bundle
from basketball.research_coldstart import _json
from basketball import research_private_store as store
from growth.admin_auth import COOKIE_NAME, issue_token
from growth.api import router
from tests.test_basketball_early_advanced_ops import setup as setup_lab

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)


def test_import_cookie_server_flags_and_hosted_digest(tmp_path, monkeypatch):
    setup_lab(tmp_path)
    assert score_capture(tmp_path, now=NOW)["created"] == 1
    assert advanced_capture(tmp_path, now=NOW)["created"] == 1
    archive = export_bundle(tmp_path)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    sessions = sessionmaker(bind=engine)

    def import_in_test(bundle):
        with sessions() as db:
            return original_import(bundle, db=db)

    def read_in_test():
        with sessions() as db:
            current = store.latest_bundle(db)
            if current is None:
                return None
            result = store.report_from_bundle(current)
            return {
                **result,
                "archive_digest": hashlib.sha256(
                    _json(current).encode("utf-8")).hexdigest(),
                "hosted_source": "private_database_snapshot"
            }

    original_import = store.import_bundle
    monkeypatch.setattr(store, "import_bundle", import_in_test)
    monkeypatch.setattr(store, "hosted_board", read_in_test)
    monkeypatch.setenv("SECRET_KEY", "synthetic-only-test-secret")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", "synthetic-configured-hash")
    monkeypatch.delenv("NBA_ADMIN_RESEARCH_ENABLED", raising=False)
    monkeypatch.delenv("NBA_ADMIN_RESEARCH_IMPORT_ENABLED", raising=False)
    app = FastAPI()
    app.include_router(router, prefix="/api/growth")
    client = TestClient(app)
    read = "/api/growth/admin/nba-research"
    upload = read + "/import"
    assert client.post(upload, json=archive).status_code == 401
    assert client.get(read).status_code == 401
    client.cookies.set(COOKIE_NAME, issue_token())
    assert client.post(upload, json=archive).status_code == 404
    monkeypatch.setenv("NBA_ADMIN_RESEARCH_ENABLED", "true")
    assert client.post(upload, json=archive).status_code == 404
    assert client.get(read).status_code == 503
    monkeypatch.setenv("NBA_ADMIN_RESEARCH_IMPORT_ENABLED", "true")
    response = client.post(upload, json=archive)
    assert response.status_code == 200
    assert response.json()["status"] == "saved_and_verified"
    assert response.json()["fixture_count"] == 1
    saved = client.get(read)
    assert saved.status_code == 200
    assert saved.headers["cache-control"] == "private, no-store"
    assert saved.json()["summary"]["fixtures"] == 1
    assert saved.json()["archive_digest"] == response.json()["digest"]
    assert client.post(upload, json=archive).json()["status"] == "already_saved"
    monkeypatch.setenv("NBA_ADMIN_RESEARCH_IMPORT_ENABLED", "false")
    assert client.post(upload, json=archive).status_code == 404
    assert client.get(read).status_code == 200
