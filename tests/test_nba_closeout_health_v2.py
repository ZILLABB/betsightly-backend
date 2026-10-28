"""V2 operations should stay honest under heavy NBA scheduler traffic."""
from datetime import timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient

from basketball import research_ops_health as ops
from basketball import research_closeout as closeout
from basketball.research_coldstart import _json
from basketball.research_private_bundle import _digest
from tests.test_basketball_ops_health import NOW, prepare


def test_v2_backup_is_current_and_records_full_audit_watermark(tmp_path, monkeypatch):
    archive, factory = prepare(tmp_path, monkeypatch)
    with factory() as db:
        ops._session_tables(db)
        stamp = NOW.replace(tzinfo=None)
        first = ops.NBAPrivateJobRun(
            kind="forecast", status="archived_before_tipoff",
            summary_json=_json({"outcome": "archived_before_tipoff"}),
            recorded_at=stamp - timedelta(minutes=12),
        )
        db.add(first)
        db.flush()
        ack = ops.NBAPrivateJobRun(
            kind="backup", status=ops.BACKUP_V2_STATUS,
            summary_json=_json({
                "archive_digest": _digest(archive),
                "outcome": ops.BACKUP_V2_STATUS,
                "last_job_id": first.id,
                "job_receipt_count": 1,
                "market_receipt_count": 0,
            }),
            recorded_at=stamp - timedelta(minutes=5),
        )
        db.add(ack)
        db.commit()
        report = ops.read_health(db=db, now=NOW)
        assert report["automatic_backup_proven"] is True
        assert report["backup_version"] == "v2"
        assert report["backup_recent_for_current_archive"] is True
        assert report["job_audit_history_in_portable_backup"] is True
        assert report["backup_covers_latest_job_history"] is True
        assert report["backup_recovery_scope"] == (
            "research_archive_market_receipts_and_job_audit_history"
        )
        assert report["archive_capacity_state"] == "normal"
        assert not report["archive_cohort_coverage"][
            "full_league_schedule_completeness_proven"
        ]
        result = closeout.evaluate_closeout(report, archive)
        assert result["offsite_recovery"]["v2_blob_readback_verified"] is True
        assert result["offsite_recovery"][
            "exact_private_blob_restored_on_independent_postgres"
        ] is False
        assert result["public_publishing_enabled"] is False
        assert len(result["league_research"]) == 6

        for i in range(27):
            db.add(ops.NBAPrivateJobRun(
                kind="settlement", status="idle",
                summary_json=_json({"outcome": "idle"}),
                recorded_at=stamp - timedelta(minutes=4),
            ))
        db.commit()
        busy = ops.read_health(db=db, now=NOW)
        assert busy["backup_version"] == "v2"
        assert busy["job_readiness"]["backup"]["state"] == "observed"
        assert busy["automatic_backup_proven"]
        assert busy["backup_covers_latest_job_history"] is False


def test_v2_backup_recency_and_forecast_do_not_confer_public_approval(tmp_path, monkeypatch):
    archive, factory = prepare(tmp_path, monkeypatch)
    with factory() as db:
        ops._session_tables(db)
        db.add(ops.NBAPrivateJobRun(
            kind="backup", status=ops.BACKUP_V2_STATUS,
            summary_json=_json({"outcome": ops.BACKUP_V2_STATUS,
                                "archive_digest": _digest(archive)}),
            recorded_at=NOW.replace(tzinfo=None) - timedelta(hours=40),
        ))
        db.commit()
        report = ops.read_health(db=db, now=NOW)
        assert report["backup_version"] == "v2"
        assert report["backup_recent_for_current_archive"] is False
        result = closeout.evaluate_closeout(report, archive)
        assert "current_complete_offsite_backup_not_verified" in (
            result["infrastructure"]["blocking_evidence"]
        )
        assert result["nba_model_validation"]["eligible_for_public_prediction"] is False
        assert result["not_a_betting_recommendation"] is True


def test_closeout_page_rejects_unauthorized_and_production(monkeypatch):
    from growth import api as growth
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("NBA_ADMIN_RESEARCH_ENABLED", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake/isolated_test")
    app = FastAPI()
    app.include_router(growth.router, prefix="/api/growth")
    client = TestClient(app)
    route = "/api/growth/admin/nba-research/closeout"
    assert client.get(route).status_code == 401
    from growth.admin_auth import COOKIE_NAME, issue_token
    monkeypatch.setenv("SECRET_KEY", "private-nba-testing-key-only")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", "test-nonsecret-hash")
    client.cookies.set(COOKIE_NAME, issue_token())
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert client.get(route).status_code == 404
