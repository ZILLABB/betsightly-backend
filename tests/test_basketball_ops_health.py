"""Private NBA operational health/export and stage route contracts."""
import hashlib
import json
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from basketball.research_coldstart import _json
from basketball.research_opening_score import capture as capture_score
from basketball.research_early_advanced_ops import capture as capture_advanced
from basketball.research_private_bundle import _digest, export_bundle
from basketball import research_private_store as store
from basketball import research_ops_health as ops
from basketball.research_market_store import NBAMarketObservation
from growth.admin_auth import COOKIE_NAME, issue_token
from growth.api import router
from tests.test_basketball_early_advanced_ops import setup as setup_lab

NOW = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)


def sessions():
    return sessionmaker(bind=create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ))


def prepare(tmp_path, monkeypatch):
    setup_lab(tmp_path)
    cutoff = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    assert capture_score(tmp_path, now=cutoff)["created"] == 1
    assert capture_advanced(tmp_path, now=cutoff)["created"] == 1
    archive = export_bundle(tmp_path)
    factory = sessions()
    monkeypatch.setattr(store, "SessionLocal", factory)
    monkeypatch.setattr(ops, "SessionLocal", factory)
    store.import_bundle(archive)
    return archive, factory


def test_health_reports_archive_and_runs_without_fake_backup(tmp_path, monkeypatch):
    archive, factory = prepare(tmp_path, monkeypatch)
    with factory() as db:
        info = ops.read_health(db=db)
        assert info["fixtures"] == len(archive["fixtures"])
        assert info["remaining_fixture_slots"] == 120 - len(archive["fixtures"])
        assert info["archive_digest"] == _digest(archive)
        assert info["automatic_backup_proven"] is False
        assert info["backup_policy"] == "manual_export_only_no_offsite_backup"
    ops.record_run("forecast", "no_new_eligible_forecasts",
                   detail={"new_forecasts": {"moneyline": 0}})
    with factory() as db:
        info = ops.read_health(db=db)
        assert info["jobs"][0]["kind"] == "forecast"
        assert info["jobs"][0]["summary"]["new_forecasts"]["moneyline"] == 0


def test_complete_backup_checks_hash_and_preserves_original(tmp_path, monkeypatch):
    archive, factory = prepare(tmp_path, monkeypatch)
    with factory() as db:
        receipt = {"source": "sportybet_ng_basketball_read_only",
                   "observed_at": NOW.isoformat(), "fixtures": [],
                   "research_only": True}
        receipt["digest"] = hashlib.sha256(
            _json(receipt).encode("utf-8")).hexdigest()
        NBAMarketObservation.__table__.create(
            bind=db.get_bind(), checkfirst=True)
        db.add(NBAMarketObservation(
            digest=receipt["digest"], payload_json=_json(receipt),
            recorded_at=NOW.replace(tzinfo=None),
        ))
        db.commit()
        backup = ops.export_verified_backup(db=db)
        assert backup["market_receipt_count"] == 1
        assert backup["market_receipts"] == [receipt]
        assert backup["archive"] == archive
        assert backup["archive_digest"] == _digest(archive)
        digest = backup.pop("backup_sha256")
        assert hashlib.sha256(_json(backup).encode("utf-8")).hexdigest() == digest


def test_export_fails_closed_on_tampered_market_data(tmp_path, monkeypatch):
    _, factory = prepare(tmp_path, monkeypatch)
    with factory() as db:
        NBAMarketObservation.__table__.create(
            bind=db.get_bind(), checkfirst=True)
        db.add(NBAMarketObservation(
            digest="0"*64, payload_json=json.dumps({"invalid": True}),
            recorded_at=NOW.replace(tzinfo=None),
        ))
        db.commit()
        import pytest
        with pytest.raises(ValueError, match="DIGEST_INVALID"):
            ops.export_verified_backup(db=db)


def test_operations_api_admin_only_staging_only(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "private-test-only")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", "nonsecret-test-hash")
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic/test")
    monkeypatch.setenv("NBA_ADMIN_RESEARCH_ENABLED", "true")
    monkeypatch.setenv("ENVIRONMENT", "staging")
    app = FastAPI()
    app.include_router(router, prefix="/api/growth")
    client = TestClient(app)
    names = ["health", "history", "backup"]
    for name in names:
        assert client.get("/api/growth/admin/nba-research/"+name).status_code == 401
    client.cookies.set(COOKIE_NAME, issue_token())
    monkeypatch.setenv("ENVIRONMENT", "production")
    for name in names:
        assert client.get("/api/growth/admin/nba-research/"+name).status_code == 404
