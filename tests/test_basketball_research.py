"""Offline NBA research safety and regression tests.

Synthetic fixtures are used ONLY here as unit-test inputs. They must never
become training data for an actual research model or public prediction.
"""
from __future__ import annotations

from datetime import date, timedelta
import json

import pytest

from basketball.research_data import normalize_game, read_games, write_games
from basketball.research_features import FEATURE_COLUMNS, make_rows, quality_report
from basketball.research_model import chronological_split, paper_forecasts, train_offline


def fixture(day: str, number: int, status: str = "final", home_win: bool = True):
    return {
        "game_id": str(number), "date": day, "season": 2023, "status": status,
        "home_id": "1", "away_id": "2",
        "home_name": "Test Home", "away_name": "Test Away",
        "home_score": 120 if home_win else 105,
        "away_score": 101 if home_win else 121,
        "start_utc": day + "T20:00:00Z", "postseason": False,
        "source": "balldontlie:nba:v1", "retrieved_at": "2024-01-01T00:00:00+00:00",
    }


def fixture_days(n: int, upcoming: bool = False):
    start = date(2024, 1, 1)
    games = [fixture((start + timedelta(days=i)).isoformat(), i + 100,
                     home_win=(i % 3 != 0)) for i in range(n)]
    if upcoming:
        day = (start + timedelta(days=n)).isoformat()
        games.append(fixture(day, n + 100, status="scheduled"))
        games[-1]["home_score"] = None
        games[-1]["away_score"] = None
    return games


def test_normalize_only_final_game_scores():
    raw = {
        "id": 42, "date": "2024-01-01", "season": 2023,
        "status_state": "final", "home_team_score": 111,
        "visitor_team_score": 108, "home_team": {"id": 1, "full_name": "A"},
        "visitor_team": {"id": 2, "full_name": "B"},
    }
    good = normalize_game(raw)
    assert good["status"] == "final" and good["home_score"] == 111
    raw["status_state"] = "scheduled"
    assert normalize_game(raw)["home_score"] is None
    raw["status_state"] = "final"
    raw["visitor_team_score"] = 111
    with pytest.raises(ValueError, match="tied"):
        normalize_game(raw)


def test_snapshot_roundtrip_and_duplicate_fail_closed(tmp_path):
    games = fixture_days(7)
    path = tmp_path / "nba.jsonl"
    assert write_games(games, path) == 7
    assert len(read_games(path)) == 7
    with pytest.raises(ValueError, match="Duplicate"):
        path.write_text(path.read_text() + path.read_text().splitlines()[0] + "\n")
        read_games(path)
    with pytest.raises(ValueError, match="empty"):
        write_games([], path)


def test_features_only_use_earlier_days_and_are_deterministic():
    games = fixture_days(12, upcoming=True)
    rows = make_rows(games)
    assert rows[0]["date"] == games[5]["date"]
    assert len(rows[0]["features"]) == len(FEATURE_COLUMNS)
    assert rows == make_rows(games)
    target = games[7].copy()
    altered = list(games)
    altered[7] = {**target, "home_score": 1, "away_score": 190}
    x_original = next(r for r in rows if r["game_id"] == target["game_id"])
    x_altered = next(r for r in make_rows(altered) if r["game_id"] == target["game_id"])
    assert x_original["features"] == x_altered["features"]
    assert x_original["home_win"] != x_altered["home_win"]
    assert quality_report(games)["eligible_model_rows"] > 0


def test_same_day_results_cannot_leak_into_other_games():
    games = fixture_days(5)
    games += [fixture("2024-01-06", 900), fixture("2024-01-06", 901)]
    rows = make_rows(games)
    first = next(r for r in rows if r["game_id"] == "900")
    second = next(r for r in rows if r["game_id"] == "901")
    assert first["features"] == second["features"]


def test_chronological_split_and_paper_model_only(tmp_path):
    pytest.importorskip("sklearn")
    pytest.importorskip("joblib")
    games = fixture_days(180, upcoming=True)
    rows = make_rows(games)
    train, val, test = chronological_split(rows, min_games=120)
    assert max(r["date"] for r in train) < min(r["date"] for r in val)
    assert max(r["date"] for r in val) < min(r["date"] for r in test)
    path = tmp_path / "model.joblib"
    result = train_offline(games, path, min_games=120)
    assert result["research_only"] is True
    assert result["publishing_enabled"] is False
    assert result["betting_roi_measured"] is False
    forecasts = paper_forecasts(games, path, games[-1]["date"])
    assert len(forecasts) == 1
    assert forecasts[0]["booking_code"] is None
    assert 0 <= forecasts[0]["home_win_probability"] <= 1
    with pytest.raises(ValueError, match="after model training"):
        paper_forecasts(games, path, result["splits"]["training"]["through"])
