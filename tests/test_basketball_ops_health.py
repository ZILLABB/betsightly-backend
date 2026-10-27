"""Private NBA operational health/export and stage route contracts."""
import hashlib
import json
from datetime import datetime, timedelta, timezone

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
        assert info["remaining_fixture_slots"] == ops.MAX_FIXTURES - len(archive["fixtures"])
        assert info["archive_digest"] == _digest(archive)
        assert info["automatic_backup_proven"] is False
        assert info["backup_policy"] == "private_vercel_blob_daily_snapshot_with_hash_readback"
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

def test_backup_restore_drill_and_tamper_rejection(tmp_path, monkeypatch):
    import pytest
    from basketball.research_restore_drill import verify_portable_backup
    _, factory = prepare(tmp_path, monkeypatch)
    with factory() as db:
        backup = ops.export_verified_backup(db=db)
        assert backup["restore_drill_passed"] is True
        audited = verify_portable_backup(backup)
        assert audited["restore_drill_passed"] is True
        assert audited["isolated_ephemeral_database"] is True
        assert audited["permanent_database_unchanged"] is True
        original_rows = db.query(store.NBAPrivateSnapshot).count()
        assert original_rows == 1
        tampered = {**backup, "archive_digest": "0"*64}
        with pytest.raises(ValueError, match="NBA_BACKUP_DIGEST_MISMATCH"):
            verify_portable_backup(tampered)
        assert db.query(store.NBAPrivateSnapshot).count() == original_rows


def test_backup_machine_routes_are_not_public(monkeypatch):
    from growth import api as growth
    token = "synthetic-backup-machine-token-never-used-in-production-123456789"
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("NBA_ADMIN_RESEARCH_ENABLED", "true")
    monkeypatch.setenv("NBA_BACKUP_PRIVATE_ENABLED", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake/staging")
    monkeypatch.setenv("NBA_BACKUP_JOB_TOKEN", token)
    app = FastAPI()
    app.include_router(growth.router, prefix="/api/growth")
    client = TestClient(app)
    path="/api/growth/internal/nba-research/backup"
    assert client.get(path).status_code == 404
    assert client.get(path, headers={
        "x-betsightly-nba-backup-token": "incorrect"}).status_code == 404
    stub=[]
    monkeypatch.setattr(growth, "nba_research_export_backup",
        lambda response: stub.append("export") or {"status":"research_only"})
    assert client.get(path, headers={
        "x-betsightly-nba-backup-token": token}).status_code == 200
    assert stub==["export"]
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert client.get(path, headers={
        "x-betsightly-nba-backup-token": token}).status_code == 404
    ack=path+"/ack"
    assert client.post(ack,json={
        "verified":True,"store":"private_vercel_blob",
        "archive_digest":"1"*64,"backup_sha256":"2"*64
    }).status_code == 404
    assert client.post(ack,json={},headers={
        "x-betsightly-nba-backup-token": token}).status_code == 404


def test_job_health_distinguishes_missing_stale_and_degraded_runs(tmp_path, monkeypatch):
    archive, factory = prepare(tmp_path, monkeypatch)
    with factory() as db:
        empty = ops.read_health(db=db, now=NOW)
        assert set(empty["job_readiness"]) == {
            "forecast", "settlement", "market", "backup"
        }
        assert all(v["state"] == "not_observed"
                   for v in empty["job_readiness"].values())
        assert empty["backup_recent_for_current_archive"] is False
        stamp = NOW.replace(tzinfo=None)
        db.add_all([
            ops.NBAPrivateJobRun(
                kind="forecast", status="no_new_eligible_forecasts",
                summary_json=_json({"outcome": "no_new_eligible_forecasts"}),
                recorded_at=stamp - timedelta(hours=40),
            ),
            ops.NBAPrivateJobRun(
                kind="settlement", status="provider_partial",
                summary_json=_json({"outcome": "provider_partial",
                                    "provider_status": "partial"}),
                recorded_at=stamp - timedelta(hours=2),
            ),
            ops.NBAPrivateJobRun(
                kind="backup", status="verified_private_blob_readback",
                summary_json=_json({"archive_digest": _digest(archive)}),
                recorded_at=stamp - timedelta(hours=40),
            ),
        ])
        db.commit()
        info = ops.read_health(db=db, now=NOW)
        assert info["job_readiness"]["forecast"]["state"] == "stale"
        assert info["job_readiness"]["settlement"]["state"] == "degraded"
        assert info["job_readiness"]["backup"]["state"] == "stale"
        assert info["job_readiness"]["market"]["state"] == "not_observed"
        assert info["automatic_backup_proven"] is True
        assert info["backup_recent_for_current_archive"] is False


def test_backup_readback_is_recent_only_for_current_signed_archive(tmp_path, monkeypatch):
    archive, factory = prepare(tmp_path, monkeypatch)
    with factory() as db:
        stamp = NOW.replace(tzinfo=None)
        row = ops.NBAPrivateJobRun(
            kind="backup", status="verified_private_blob_readback",
            summary_json=_json({"archive_digest": "a" * 64}),
            recorded_at=stamp - timedelta(hours=2),
        )
        db.add(row)
        db.commit()
        assert ops.read_health(db=db, now=NOW)[
            "backup_recent_for_current_archive"] is False
        row.summary_json = _json({"archive_digest": _digest(archive)})
        db.commit()
        status = ops.read_health(db=db, now=NOW)
        assert status["backup_recent_for_current_archive"] is True
        assert status["job_readiness"]["backup"]["state"] == "observed"
        row.recorded_at = stamp - timedelta(hours=40)
        db.commit()
        assert ops.read_health(db=db, now=NOW)[
            "backup_recent_for_current_archive"] is False


def test_nba_job_receipts_redact_provider_failures_and_preserve_digest(tmp_path, monkeypatch):
    archive, factory = prepare(tmp_path, monkeypatch)
    ops.record_run("settlement", "provider_partial", detail={
        "provider_status": "partial", "failed_dates": [
            {"date": "2026-10-25", "detail": "private provider error"}
        ], "secret": "NEVER_EXPORT_THIS",
    })
    ops.record_run("backup", "verified_private_blob_readback",
                   detail={"archive_digest": _digest(archive)})
    with factory() as db:
        rows = db.query(ops.NBAPrivateJobRun).order_by(
            ops.NBAPrivateJobRun.id.desc()).all()
        assert json.loads(rows[0].summary_json)["archive_digest"] == _digest(archive)
        settlement = json.loads(rows[1].summary_json)
        assert settlement["provider_status"] == "partial"
        assert settlement["failed_date_count"] == 1
        assert "NEVER_EXPORT_THIS" not in rows[1].summary_json
        assert "private provider error" not in rows[1].summary_json
