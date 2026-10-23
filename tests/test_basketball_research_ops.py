"""Private NBA research operations — persistence, idempotence and local UI."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from basketball.research_data import write_games
from basketball.research_dashboard import render_dashboard
from basketball.research_store import (
    list_forecasts, open_ledger, performance_report, save_forecasts, settle_forecasts,
)


def valid_prediction():
    now = datetime.now(timezone.utc) - timedelta(seconds=10)
    kickoff = now + timedelta(hours=3)
    return {
        "game_id": "future-nba-501",
        "date": kickoff.date().isoformat(),
        "home_team_id": "21", "away_team_id": "22",
        "home_team": "<script>alert('x')</script> Home",
        "away_team": "Research Away",
        "start_utc": kickoff.isoformat(),
        "generated_at": now.isoformat(),
        "home_win_probability": 0.62,
        "away_win_probability": 0.38,
        "model_version": "nba-moneyline-offline-v1",
        "feature_schema": "nba-pregame-v1",
        "research_only": True,
        "not_for_betting": True,
        "bookmaker_odds_verified": False,
        "booking_code": None,
    }


def test_sqlite_forecast_records_are_append_only(tmp_path):
    connection = open_ledger(tmp_path / "private.sqlite")
    try:
        prediction = valid_prediction()
        assert save_forecasts(connection, [prediction])["inserted"] == 1
        assert save_forecasts(connection, [prediction])["unchanged"] == 1
        changed = {**prediction, "home_win_probability": 0.97,
                   "away_win_probability": 0.03}
        with pytest.raises(ValueError, match="cannot be changed"):
            save_forecasts(connection, [changed])
        assert len(list_forecasts(connection)) == 1
        assert list_forecasts(connection)[0]["home_win_probability"] == 0.62

        game = {
            "game_id": prediction["game_id"], "date": prediction["date"],
            "home_id": "21", "away_id": "22", "status": "final",
            "home_score": 115, "away_score": 108,
            "source": "sportsdataverse:espn_nba_schedules:v1",
        }
        assert settle_forecasts(connection, [game])["newly_settled"] == 1
        assert settle_forecasts(connection, [game])["already_settled"] == 1
        report = performance_report(connection)
        assert report["settled"] == 1 and report["pending"] == 0
        assert report["accuracy"] == 1 and report["betting_roi"] is None
        with pytest.raises(ValueError, match="changed after settlement"):
            settle_forecasts(connection, [{**game, "home_score": 113}])
    finally:
        connection.close()


def test_paper_rejects_invalid_and_backdated_predictions(tmp_path):
    connection = open_ledger(tmp_path / "private.sqlite")
    try:
        p = valid_prediction()
        for changed in (
            {**p, "booking_code": "INVALID"},
            {**p, "research_only": False},
            {**p, "home_win_probability": float("nan")},
            {**p, "start_utc": p["generated_at"]},
        ):
            with pytest.raises(ValueError):
                save_forecasts(connection, [changed])
        assert performance_report(connection)["forecast_count"] == 0
    finally:
        connection.close()


def test_atlantic_dashboard_escapes_provider_html():
    forecast = {
        "game_id": "NBA-22", "fixture_date": "2026-10-25",
        "home_team": '<img src=x onerror=alert(1)>',
        "away_team": "Other", "home_win_probability": 0.61,
        "home_score": None, "away_score": None, "home_won": None,
        "recorded_at": None,
    }
    dashboard = render_dashboard(
        {"forecast_count": 1, "settled": 0, "pending": 1},
        [forecast], [{"occurred_at": "2026-10-23", "kind": "cycle",
                      "message": "<b>danger</b>"}],
    )
    assert '<img src=x' not in dashboard
    assert "&lt;img src=x" in dashboard
    assert "&lt;b&gt;danger&lt;/b&gt;" in dashboard
    assert "PRIVATE · OFFLINE · NO BETTING" in dashboard


def test_offline_cycle_retains_model_and_does_not_invent_picks(tmp_path):
    pytest.importorskip("sklearn")
    from basketball.research_cycle import run_cycle
    from basketball.research_store import open_ledger, performance_report

    start = date(2024, 1, 1)
    games = []
    for i in range(360):
        when = (start + timedelta(days=i)).isoformat()
        wins = i % 3 != 0
        games.append({
            "game_id": str(i + 1000), "date": when, "season": 2023,
            "status": "final", "home_id": "1", "away_id": "2",
            "home_name": "Example One", "away_name": "Example Two",
            "home_score": 120 if wins else 100,
            "away_score": 107 if wins else 110,
            "start_utc": when + "T23:00:00Z", "postseason": False,
            "source": "balldontlie:nba:v1", "retrieved_at": when + "T00:00:00Z",
        })
    write_games(games, tmp_path / "nba_games.jsonl")
    first = run_cycle(home=tmp_path, offline=True, days_ahead=2)
    assert first["model_retrained"] is True
    assert first["new_forecasts"] == 0
    assert first["public_publishing_enabled"] is False
    assert (tmp_path / "nba_moneyline.joblib").exists()
    second = run_cycle(home=tmp_path, offline=True)
    assert second["model_retrained"] is False
    assert second["performance"]["forecast_count"] == 0
    with open_ledger(tmp_path / "nba_paper.sqlite") as connection:
        assert performance_report(connection)["settled"] == 0

def test_score_models_use_true_labels_and_later_holdout(tmp_path):
    pytest.importorskip("sklearn")
    from basketball.research_market_models import train_score_baselines
    from basketball.research_data import read_games
    from basketball.research_model import train_offline
    start = date(2024, 1, 1)
    data = []
    for i in range(350):
        when = (start + timedelta(days=i)).isoformat()
        data.append({
            "game_id": str(3000 + i), "date": when, "season": 2023,
            "status": "final", "home_id": "1", "away_id": "2",
            "home_name": "A", "away_name": "B",
            "home_score": 105 + i % 17, "away_score": 100 + (i * 3) % 21,
            "start_utc": when + "T20:00:00Z", "postseason": False,
            "source": "balldontlie:nba:v1",
            "retrieved_at": "2026-10-23T00:00:00Z",
        })
    report = train_score_baselines(data, tmp_path / "scores.joblib")
    assert set(report["targets"]) == {"total_points", "home_margin"}
    assert report["historical_test_period"]["games"] >= 20
    assert report["betting_roi_computed"] is False
    assert report["research_only"] is True
    assert report["targets"]["total_points"]["test"]["mae"] >= 0
    assert report["targets"]["home_margin"]["test"]["rmse"] >= 0
    assert (tmp_path / "scores.joblib").is_file()
