"""Only an authenticated operator can access archived NBA paper forecasts."""
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from basketball.research_admin_board import board_from_home
from basketball.research_opening_score import capture as original_capture
from basketball.research_early_advanced_ops import capture as advanced_capture
from growth.admin_auth import COOKIE_NAME, issue_token
from growth.api import router
from tests.test_basketball_early_advanced_ops import setup as setup_lab

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)


def test_nba_dashboard_never_invents_local_forecasts(tmp_path):
    report = board_from_home(tmp_path, now=NOW)
    assert report["status"] == "data_not_configured"
    assert report["games"] == []
    assert report["no_writes"] is True


def test_nba_board_joins_original_and_advanced_signed_archives(tmp_path):
    setup_lab(tmp_path)
    assert original_capture(tmp_path, now=NOW)["created"] == 1
    assert advanced_capture(tmp_path, now=NOW)["created"] == 1
    report = board_from_home(tmp_path, now=NOW)
    assert report["status"] == "recorded_research_only"
    assert report["summary"]["fixtures"] == 1
    assert report["summary"]["forecasts"]["moneyline"] == 0
    assert report["summary"]["forecasts"]["original_score"] == 1
    assert report["summary"]["forecasts"]["advanced_score"] == 1
    g = report["games"][0]
    assert g["game_id"] == "29000"
    assert g["status"] == "upcoming"
    assert g["home_win_probability"] is None
    assert g["projected_total"] is not None
    assert g["advanced_total"] is not None
    assert g["tipoff_wat"].endswith("+01:00")
    assert g["sportybet_code"] is None
    assert not g["bookmaker_market_verified"]


def test_signed_archive_tampering_blocks_entire_board(tmp_path):
    setup_lab(tmp_path)
    original_capture(tmp_path, now=NOW)
    file = tmp_path / "opening_score_forecasts.jsonl"
    file.write_text(file.read_text().replace(
        '"predicted_total":', '"predicted_total":999,"extra":'))
    result = board_from_home(tmp_path, now=NOW)
    assert result["status"] == "integrity_failed"
    assert result["games"] == []


def test_admin_auth_and_server_feature_flag_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "synthetic-server-key")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", "synthetic-configuration-present")
    monkeypatch.setenv("NBA_RESEARCH_HOME", str(tmp_path))
    monkeypatch.delenv("NBA_ADMIN_RESEARCH_ENABLED", raising=False)
    app = FastAPI()
    app.include_router(router, prefix="/api/growth")
    client = TestClient(app)
    path = "/api/growth/admin/nba-research"
    assert client.get(path).status_code == 401
    client.cookies.set(COOKIE_NAME, issue_token())
    assert client.get(path).status_code == 404
    monkeypatch.setenv("NBA_ADMIN_RESEARCH_ENABLED", "true")
    assert client.get(path).status_code == 503
    setup_lab(tmp_path)
    original_capture(tmp_path, now=NOW)
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert response.json()["summary"]["fixtures"] == 1
