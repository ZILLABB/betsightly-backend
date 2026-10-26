"""Stage-only NBA bookmaker research: exact market identity, no made-up picks."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from basketball.research_market_watch import _event, match_board, compare_to_archive
from growth.admin_auth import COOKIE_NAME, issue_token
from growth.api import router

NOW = datetime(2026, 10, 26, 10, tzinfo=timezone.utc)
START = NOW + timedelta(hours=6)
START_MS = int(START.timestamp() * 1000)


def fixture():
    return {
        "game_id": "401909870", "home_name": "Boston Celtics",
        "away_name": "Chicago Bulls", "start_utc": START.isoformat(),
        "status": "scheduled", "postseason": False,
    }


def bookmaker(home="Boston Celtics", away="Chicago Bulls", kickoff=START_MS):
    return {
        "eventId": "sr:match:123456789", "homeTeamName": home,
        "awayTeamName": away, "estimateStartTime": kickoff,
        "markets": [
            {"id": "225", "specifier": "total=229.5",
             "outcomes": [{"id": "12", "odds": 1.88},
                          {"id": "13", "odds": 1.90}]},
            {"id": "219", "specifier": "",
             "outcomes": [{"id": "4", "odds": 1.41},
                          {"id": "5", "odds": 2.70}]},
        ],
    }


def test_exact_bookmaker_match_only_prior_to_tipoff():
    event = _event(bookmaker(), competition="NBA")
    rows = match_board([fixture()], [event], now=NOW)
    assert len(rows) == 1
    assert rows[0]["event_id"] == "sr:match:123456789"
    assert rows[0]["markets"][0]["line"] == 229.5
    assert rows[0]["markets"][0]["prices"]["12"] == 1.88
    assert match_board([fixture()], [event],
                       now=START - timedelta(minutes=5)) == []


def test_reject_alias_guess_swapped_teams_and_tipoff_mismatch():
    flipped = _event(bookmaker(home="Chicago Bulls", away="Boston Celtics"),
                     competition="NBA")
    assert match_board([fixture()], [flipped], now=NOW) == []
    late = _event(bookmaker(kickoff=START_MS + 2 * 3600 * 1000),
                  competition="NBA")
    assert match_board([fixture()], [late], now=NOW) == []
    assert _event(bookmaker(home="Boston Baskets"),
                  competition="NBA") is None


def test_duplicate_match_fail_closed_and_malformed_line_excluded():
    event = _event(bookmaker(), competition="NBA")
    with pytest.raises(ValueError, match="DUPLICATE"):
        match_board([fixture()], [event, event], now=NOW)
    wrong = bookmaker()
    wrong["markets"][0]["specifier"] = "total=unknown"
    valid = _event(wrong, competition="NBA")
    assert len(valid["markets"]) == 1
    assert valid["markets"][0]["market_id"] == "219"


def test_comparison_is_not_a_recommendation():
    board = {"games": [{"game_id": "401909870", "advanced_total": 236.6,
                         "projected_total": 230.4, "status": "upcoming"}]}
    observation = {
        "source": "sportybet_ng_basketball_read_only", "digest": "test-digest",
        "observed_at": NOW.isoformat(),
        "fixtures": match_board(
            [fixture()], [_event(bookmaker(), competition="NBA")], now=NOW),
    }
    report = compare_to_archive(board, observation)
    assert report["quoted_totals"][0]["difference"] == 7.1
    assert report["quoted_totals"][0]["over_odds"] == 1.88
    assert report["quoted_totals"][0]["model_probability"] is None
    assert report["quoted_totals"][0]["expected_value"] is None
    assert report["quoted_totals"][0]["recommendation"] == "NO_SELECTION_UNCALIBRATED"


def test_private_market_routes_auth_and_optin(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "synthetic-only-test-secret")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", "synthetic-hash")
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic/db")
    monkeypatch.setenv("NBA_ADMIN_RESEARCH_ENABLED", "true")
    monkeypatch.setenv("NBA_ADMIN_RESEARCH_MARKETS_ENABLED", "false")
    app = FastAPI()
    app.include_router(router, prefix="/api/growth")
    client = TestClient(app)
    url = "/api/growth/admin/nba-research/markets"
    assert client.get(url).status_code == 401
    assert client.post(url + "/refresh", json={}).status_code == 401
    client.cookies.set(COOKIE_NAME, issue_token())
    assert client.get(url).status_code == 404
    assert client.post(url + "/refresh", json={}).status_code == 404
    monkeypatch.setenv("NBA_ADMIN_RESEARCH_MARKETS_ENABLED", "true")
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert client.get(url).status_code == 404
    assert client.post(url + "/refresh", json={}).status_code == 404
