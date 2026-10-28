"""Full isolated NBA recovery V2 acceptance, no public services or network."""
import copy
import json
from datetime import datetime, timezone

import pytest

from basketball import research_full_recovery as recovery
from basketball import research_ops_health as ops
from tests.test_basketball_ops_health import NOW, prepare


def test_full_export_cryptographically_restores_job_history(tmp_path, monkeypatch):
    _, factory = prepare(tmp_path, monkeypatch)
    with factory() as db:
        ops._session_tables(db)
        db.add_all([
            ops.NBAPrivateJobRun(
                kind="forecast", status="archived_before_tipoff",
                summary_json='{"outcome":"archived_before_tipoff"}',
                recorded_at=NOW.replace(tzinfo=None),
            ),
            ops.NBAPrivateJobRun(
                kind="settlement", status="settled_and_verified",
                summary_json='{"new_finals":4,"outcome":"settled_and_verified"}',
                recorded_at=NOW.replace(tzinfo=None),
            ),
        ])
        db.commit()
        bundle = recovery.build_full_recovery(db=db)
        assert bundle["version"] == recovery.VERSION
        assert bundle["job_receipt_count"] == 2
        assert bundle["portable_backup_v1"]["archive_digest"]
        result = recovery.verify_full_recovery(bundle)
        assert result["status"] == "full_private_recovery_drill_passed"
        assert result["job_receipt_count"] == 2
        assert result["isolated_ephemeral_database"] is True
        assert result["offsite_storage_proven"] is False
        assert db.query(ops.NBAPrivateJobRun).count() == 2


def test_full_recovery_rejects_missing_reordered_tampered_job_rows(tmp_path, monkeypatch):
    _, factory = prepare(tmp_path, monkeypatch)
    with factory() as db:
        ops._session_tables(db)
        for idx in range(2):
            db.add(ops.NBAPrivateJobRun(
                kind="forecast", status="no_new_eligible_forecasts",
                summary_json='{"outcome":"no_new_eligible_forecasts"}',
                recorded_at=NOW.replace(tzinfo=None),
            ))
        db.commit()
        original = recovery.build_full_recovery(db=db)
        for modification in (
            lambda v: v["job_receipts"].pop(),
            lambda v: v["job_receipts"].reverse(),
            lambda v: v["job_receipts"][0].update(status="altered"),
            lambda v: v.update(sha256="0"*64),
            lambda v: v["portable_backup_v1"].update(archive_digest="0"*64),
        ):
            altered = copy.deepcopy(original)
            modification(altered)
            with pytest.raises(ValueError):
                recovery.verify_full_recovery(altered)
        assert db.query(ops.NBAPrivateJobRun).count() == 2


def test_full_recovery_prevents_unsafe_audit_payloads():
    row = {
        "id": 1, "kind": "forecast", "status": "no_new_eligible_forecasts",
        "summary_json": json.dumps({"secret": "not-permitted"}),
        "recorded_at": NOW.isoformat(),
    }
    with pytest.raises(ValueError, match="CONTENT_INVALID"):
        recovery._validate_rows([row])
    row["summary_json"] = '{"outcome":"ok"}'
    row["recorded_at"] = "2026-10-26T12:00:00"
    with pytest.raises(ValueError, match="CONTENT_INVALID"):
        recovery._validate_rows([row])
    row["recorded_at"] = NOW.isoformat()
    with pytest.raises(ValueError, match="IDENTITY"):
        recovery._validate_rows([row, row])


def test_full_backup_route_never_public(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from growth import api
    token = "private-test-token-" + "z"*52
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("NBA_ADMIN_RESEARCH_ENABLED", "true")
    monkeypatch.setenv("NBA_BACKUP_PRIVATE_ENABLED", "true")
    monkeypatch.setenv("NBA_BACKUP_JOB_TOKEN", token)
    app = FastAPI()
    app.include_router(api.router, prefix="/api/growth")
    client = TestClient(app)
    path = "/api/growth/internal/nba-research/backup-full"
    assert client.get(path).status_code == 404
    assert client.get(path, headers={
        "x-betsightly-nba-backup-token":"wrong"}).status_code == 404
    monkeypatch.setattr(api, "nba_research_export_backup_full",
        lambda response: {"status": "private_only"})
    res = client.get(path, headers={
        "x-betsightly-nba-backup-token": token})
    assert res.status_code == 200
    assert res.json()["status"] == "private_only"
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert client.get(path, headers={
        "x-betsightly-nba-backup-token": token}).status_code == 404
