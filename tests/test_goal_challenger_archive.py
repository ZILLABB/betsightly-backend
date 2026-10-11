"""Prospective challenger evidence must survive the official immutable archive."""
import json

from leagues import picks_db


def test_shadow_evidence_preserves_original_valid_forecast():
    data = picks_db.forecast_evidence_for_archive({
        "expected_home_goals": 1.75, "expected_away_goals": 0.93,
        "expected_goals": 2.68,
        "model_home_win_probability": .64,
        "model_away_win_probability": .15,
        "model_draw_probability": .21,
        "bookmaker_home_win_odds": 1.47,
        "bookmaker_away_win_odds": 7.0,
    })
    assert data["expected_home_goals"] == 1.75
    assert data["expected_away_goals"] == .93
    assert data["model_home_win_probability"] == .64
    assert data["bookmaker_home_win_odds"] == 1.47


def test_missing_or_invalid_shadow_inputs_are_not_fabricated():
    data = picks_db.forecast_evidence_for_archive({
        "expected_home_goals": float("nan"),
        "expected_away_goals": -1,
        "model_draw_probability": 2,
        "bookmaker_home_win_odds": 0.8,
    })
    assert data["expected_home_goals"] is None
    assert data["expected_away_goals"] is None
    assert data["model_draw_probability"] is None
    assert data["bookmaker_home_win_odds"] is None
    assert data["expected_goals"] is None


def test_archive_slip_writes_shadow_evidence_to_original_record(monkeypatch):
    captured = []

    class Query:
        def filter(self, *_args):
            return self

        def first(self):
            return None

    class Session:
        def query(self, *_args):
            return Query()

        def add(self, row):
            captured.append(row)

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(picks_db, "SessionLocal", Session)
    game = {
        "match_id": "fixture-10",
        "market": "over_1_5",
        "prediction": "Over 1.5 Goals",
        "home_team": "Home",
        "away_team": "Away",
        "confidence": .75,
        "odds": 1.45,
        "odds_are_real": True,
        "expected_home_goals": 1.75,
        "expected_away_goals": .93,
        "expected_goals": 2.68,
    }
    assert picks_db.archive_slip("2026-10-12", "5_odds", [game], 1.45, .75)
    assert len(captured) == 1
    stored = json.loads(captured[0].picks)[0]
    assert stored["expected_home_goals"] == 1.75
    assert stored["expected_away_goals"] == .93
    assert stored["expected_goals"] == 2.68
    assert stored["status"] == "pending"
