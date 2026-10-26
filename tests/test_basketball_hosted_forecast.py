"""Hosted NBA forward forecasts must be original, signed and truly pregame."""
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from basketball.research_data import write_games
from basketball.research_coldstart import capture as money_capture
from basketball.research_opening_score import capture as score_capture
from basketball.research_private_bundle import export_bundle
from basketball import research_private_store as store
from basketball import research_hosted_forecast as cloud
from tests.test_basketball_early_advanced_ops import setup as setup_lab
from tests.test_basketball_coldstart import game


BASE = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
RUN = datetime(2026, 10, 26, 11, tzinfo=timezone.utc)


def _sessions():
    return sessionmaker(bind=create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ))


def test_cloud_forecast_adds_only_future_games_no_model_rewrite(tmp_path, monkeypatch):
    games = setup_lab(tmp_path)
    assert money_capture(tmp_path, now=BASE)["created"] == 1
    assert score_capture(tmp_path, now=BASE)["created"] == 1
    original = export_bundle(tmp_path)
    sessions = _sessions()
    monkeypatch.setattr(cloud, "SessionLocal", sessions)
    monkeypatch.setattr(store, "SessionLocal", sessions)
    store.import_bundle(original)
    later = game(29001, season=2027, date="2026-10-27",
                 home="1", away="2", status="scheduled",
                 stamp="2026-10-27T20:00:00+00:00")
    season_data = [*games, later]
    assert any(g["season"] == 2026 and g["status"] == "final"
               for g in season_data)

    def loader(years):
        assert years == [2026, 2027]
        return season_data, [{}, {}]

    report = cloud.forecast_hosted(now=RUN, season_loader=loader)
    assert report["status"] == "archived_before_tipoff"
    assert report["new_forecasts"]["original_score"] >= 1
    assert report["new_forecasts"]["advanced_score"] == 0
    with sessions() as db:
        latest = store.latest_bundle(db)
        assert len(latest["fixtures"]) > len(original["fixtures"])
        for kind in ("moneyline", "opening_score", "early_advanced"):
            assert latest["records"][kind][:len(original["records"][kind])] == (
                original["records"][kind])
    again = cloud.forecast_hosted(now=RUN, season_loader=loader)
    assert again["status"] == "no_new_eligible_forecasts"


def test_cloud_forecast_refuses_missing_verified_previous_season(tmp_path, monkeypatch):
    games = setup_lab(tmp_path)
    money_capture(tmp_path, now=BASE)
    score_capture(tmp_path, now=BASE)
    sessions = _sessions()
    monkeypatch.setattr(cloud, "SessionLocal", sessions)
    monkeypatch.setattr(store, "SessionLocal", sessions)
    store.import_bundle(export_bundle(tmp_path))
    missing = [g for g in games if g["season"] == 2027]
    try:
        cloud.forecast_hosted(now=RUN, season_loader=lambda years: (
            missing, [{}, {}]))
    except ValueError as exc:
        assert str(exc) == "NBA_PREVIOUS_SEASON_FINAL_SAMPLE_INCOMPLETE"
    else:
        raise AssertionError("Missing prior season cannot produce a forecast")
    with sessions() as db:
        assert db.query(store.NBAPrivateSnapshot).count() == 1

def test_machine_daily_forecast_token_gate(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from growth import api as growth

    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic/db")
    monkeypatch.setenv("NBA_ADMIN_RESEARCH_ENABLED", "true")
    monkeypatch.setenv("NBA_ADMIN_RESEARCH_FORECAST_ENABLED", "true")
    token = "synthetic-only-test-token-for-nba-forecast-auth-0000000000000"
    monkeypatch.setenv("NBA_FORECAST_JOB_TOKEN", token)
    calls = []
    monkeypatch.setattr(
        growth, "nba_admin_forecast_research",
        lambda response: calls.append("allowed") or {"status": "no_new_eligible_forecasts"}
    )
    app = FastAPI()
    app.include_router(growth.router, prefix="/api/growth")
    client = TestClient(app)
    path = "/api/growth/internal/nba-research/forecast"
    assert client.get(path).status_code == 405
    assert client.post(path).status_code == 404
    assert client.post(path, headers={
        "x-betsightly-nba-forecast-token": "incorrect"}).status_code == 404
    assert calls == []
    assert client.post(path, headers={
        "x-betsightly-nba-forecast-token": token}).status_code == 200
    assert calls == ["allowed"]
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert client.post(path, headers={
        "x-betsightly-nba-forecast-token": token}).status_code == 404
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.delenv("NBA_FORECAST_JOB_TOKEN")
    assert client.post(path, headers={
        "x-betsightly-nba-forecast-token": token}).status_code == 404
    assert calls == ["allowed"]
