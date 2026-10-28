"""Hosted NBA grading: original forecasts stay immutable, no betting or football."""
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from basketball.research_coldstart import _json
from basketball.research_opening_score import capture as opening_capture
from basketball.research_early_advanced_ops import capture as advanced_capture
from basketball.research_private_bundle import export_bundle
from basketball import research_private_store as store
from basketball import research_hosted_settlement as hosted
from growth.admin_auth import COOKIE_NAME, issue_token
from growth.api import router
from tests.test_basketball_early_advanced_ops import setup as setup_lab


NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
AFTER = datetime(2026, 10, 26, 23, tzinfo=timezone.utc)


def prepared_archive(tmp_path):
    setup_lab(tmp_path)
    assert opening_capture(tmp_path, now=NOW)["created"] == 1
    assert advanced_capture(tmp_path, now=NOW)["created"] == 1
    return export_bundle(tmp_path)


def sqlite_sessions():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    return sessionmaker(bind=engine)


def test_hosted_settlement_appends_three_grades_and_preserves_forecasts(tmp_path, monkeypatch):
    original = prepared_archive(tmp_path)
    sessions = sqlite_sessions()
    monkeypatch.setattr(hosted, "SessionLocal", sessions)
    monkeypatch.setattr(store, "SessionLocal", sessions)
    store.import_bundle(original)

    def final_provider(fixtures, *, as_of):
        assert len(fixtures) == 1
        assert as_of == AFTER
        amended = [{**g, "status": "final", "home_score": 114,
                    "away_score": 102, "retrieved_at": as_of.isoformat()}
                   for g in fixtures]
        return amended, {"status": "ok", "dates_checked": 1, "failed_dates": []}

    result = hosted.settle_hosted(now=AFTER, refresher=final_provider)
    assert result["status"] == "settled_and_verified"
    assert result["new_finals"] == 1
    # This fixture setup has no moneyline forecast; only saved forecast\n    # ledgers may be graded. Production archive has all three models.\n    assert result["new_settlements"] == {\n        "moneyline": 0, "original_score": 1, "advanced_score": 1}
    saved = store.hosted_board()
    assert saved["archive_digest"] == result["archive_digest"]
    assert saved["summary"]["fixtures"] == 1
    with sessions() as db:
        latest = store.latest_bundle(db)
        for kind in ("moneyline", "opening_score", "early_advanced"):
            assert latest["records"][kind] == original["records"][kind]
        assert len(latest["records"]["moneyline_finals"]) == 0
        assert all(len(latest["records"][k]) == 1 for k in (
            "opening_score_finals", "early_advanced_finals"))
        assert db.query(store.NBAPrivateSnapshot).count() == 2
    again = hosted.settle_hosted(now=AFTER, refresher=final_provider)
    assert again["status"] == "idle"
    with sessions() as db:
        assert db.query(store.NBAPrivateSnapshot).count() == 2


def test_hosted_provider_identity_anomaly_cannot_modify_snapshot(tmp_path, monkeypatch):
    original = prepared_archive(tmp_path)
    sessions = sqlite_sessions()
    monkeypatch.setattr(hosted, "SessionLocal", sessions)
    monkeypatch.setattr(store, "SessionLocal", sessions)
    first = store.import_bundle(original)

    def wrong_provider(fixtures, *, as_of):
        return [{**g, "home_id": "999999", "status": "final",
                 "home_score": 115, "away_score": 102}
                for g in fixtures], {"status": "ok", "dates_checked": 1}

    with pytest.raises(ValueError):
        hosted.settle_hosted(now=AFTER, refresher=wrong_provider)
    with sessions() as db:
        assert db.query(store.NBAPrivateSnapshot).count() == 1
        assert store.latest_bundle(db) == original


def test_stage_hosted_settlement_route_is_opt_in_admin_only(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "local-synthetic-test-secret")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", "synthetic-test-hash")
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic-not-real/db")
    monkeypatch.setenv("NBA_ADMIN_RESEARCH_ENABLED", "true")
    monkeypatch.setenv("NBA_ADMIN_RESEARCH_SETTLE_ENABLED", "true")
    app = FastAPI()
    app.include_router(router, prefix="/api/growth")
    client = TestClient(app)
    path = "/api/growth/admin/nba-research/settle"
    assert client.post(path).status_code == 401
    client.cookies.set(COOKIE_NAME, issue_token())
    assert client.get(path).status_code == 405
    monkeypatch.setenv("NBA_ADMIN_RESEARCH_SETTLE_ENABLED", "false")
    assert client.post(path).status_code == 404
    monkeypatch.setenv("NBA_ADMIN_RESEARCH_SETTLE_ENABLED", "true")
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert client.post(path).status_code == 404
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///football.db")
    assert client.post(path).status_code == 404

def test_machine_settlement_requires_staging_secret_and_same_flag(monkeypatch):
    from growth import api as growth
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic-not-real/db")
    monkeypatch.setenv("NBA_ADMIN_RESEARCH_ENABLED", "true")
    monkeypatch.setenv("NBA_ADMIN_RESEARCH_SETTLE_ENABLED", "true")
    token = "synthetic-integration-test-only-token-0000"
    monkeypatch.setenv("NBA_SETTLEMENT_JOB_TOKEN", token)
    calls = []
    monkeypatch.setattr(growth, "nba_admin_research_settle",
                        lambda response: calls.append(True) or {"status": "idle"})
    app = FastAPI()
    app.include_router(router, prefix="/api/growth")
    client = TestClient(app)
    path = "/api/growth/internal/nba-research/settle"
    assert client.get(path).status_code == 405
    assert client.post(path).status_code == 404
    assert client.post(path, headers={
        "x-betsightly-nba-settle-token": "wrong-secret"}).status_code == 404
    assert not calls
    result = client.post(path, headers={
        "x-betsightly-nba-settle-token": token})
    assert result.status_code == 200
    assert result.json()["status"] == "idle"
    assert len(calls) == 1
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert client.post(path, headers={
        "x-betsightly-nba-settle-token": token}).status_code == 404
    assert len(calls) == 1


@pytest.mark.parametrize(
    "provider_status,failed_dates,expected_http,expected_audit",
    [
        ("ok", [], 200, "settled_and_verified"),
        ("partial", [{"date": "2026-10-26"}], 503, "provider_partial"),
        ("ok", [{"date": "2026-10-26"}], 503, "provider_partial"),
    ],
)
def test_machine_settlement_never_acknowledges_partial_provider_as_success(
        monkeypatch, provider_status, failed_dates, expected_http, expected_audit):
    """Authenticated cron must surface degraded verification even after a safe commit."""
    from growth import api as growth

    token = "synthetic-stage-settlement-machine-token-longer-than-32"
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("NBA_SETTLEMENT_JOB_TOKEN", token)
    calls = []
    monkeypatch.setattr(
        growth, "nba_admin_research_settle",
        lambda response: {
            "status": "settled_and_verified",
            "provider_status": provider_status,
            "failed_dates": failed_dates,
            "new_finals": 1,
            "research_only": True,
        },
    )
    monkeypatch.setattr(
        growth, "_record_nba_machine_job",
        lambda kind, status, result=None: calls.append((kind, status)),
    )
    app = FastAPI()
    app.include_router(growth.router, prefix="/api/growth")
    response = TestClient(app).post(
        "/api/growth/internal/nba-research/settle",
        headers={"x-betsightly-nba-settle-token": token},
    )
    assert response.status_code == expected_http
    assert calls == [("settlement", expected_audit)]
    if expected_http != 200:
        assert response.json()["detail"] == "NBA scoreboard verification incomplete."
