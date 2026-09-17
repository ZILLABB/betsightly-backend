import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from leagues import builder_runs as runs
from leagues.booking import leg_fingerprint


def test_builder_runs_record_server_outcome_without_code(monkeypatch):
    db = create_engine("sqlite://", poolclass=StaticPool,
                       connect_args={"check_same_thread": False})
    monkeypatch.setattr(runs, "engine", db)
    runs.record_run(10, "today", False, {
        "status": "success", "legs": 4, "odds": 10.2,
        "booking": {"status": "active", "booking_status": "REBUILT_FULL",
                    "share_code": "SECRET-CODE", "actual_sportybet_odds": 10.1,
                    "readback_validation": "PASSED",
                    "sportybet_selection_fingerprint": "variant-1"},
    })
    result = runs.summary("2000-01-01", "2100-01-01")
    assert result["requests"] == 1
    assert result["tickets_produced"] == 1
    with db.begin() as conn:
        stored = conn.execute(runs.builder_runs.select()).mappings().one()
    assert "share_code" not in stored
    assert "SECRET-CODE" not in str(dict(stored))


def test_builder_runs_categorizes_no_code(monkeypatch):
    db = create_engine("sqlite://", poolclass=StaticPool,
                       connect_args={"check_same_thread": False})
    monkeypatch.setattr(runs, "engine", db)
    runs.record_run(50, "week", True, {
        "status": "success", "legs": 7,
        "booking": {"status": "unavailable", "booking_status": "UNAVAILABLE"},
    })
    result = runs.summary("2000-01-01", "2100-01-01")
    assert result["ticket_rate"] == 0
    assert result["failures"] == [{"category": "UNAVAILABLE", "count": 1}]


def _game(match_id, odds=1.5, market="over_1_5"):
    return {
        "match_id": match_id, "home_team": f"Home {match_id}",
        "away_team": f"Away {match_id}", "market": market,
        "odds": odds, "confidence": .72,
        "evidence_adjusted_probability": .70,
        "trust": {"trust_score": 82},
        "kickoff": "2026-09-08T18:00:00Z",
    }


def _success(games, target=2.0, actual_odds=None):
    odds = 1.0
    probability = 1.0
    for game in games:
        odds *= game["odds"]
        probability *= game["evidence_adjusted_probability"]
    booking = {"status": "unavailable"}
    if actual_odds is not None:
        booking = {
            "status": "active", "booking_status": "CREATED",
            "share_code": "never-persist-this-code",
            "actual_sportybet_odds": actual_odds,
            "readback_validation": "PASSED",
        }
    return {
        "status": "success", "games": games, "legs": len(games),
        "odds": odds, "hit_probability": probability,
        "target_hit_probability": probability,
        "no_loss_probability": probability,
        "expected_return": odds * probability,
        "avg_confidence": .72, "avg_evidence_probability": .70,
        "minimum_trust_score": 82, "booking": booking,
    }


def _memory_engine(monkeypatch):
    db = create_engine("sqlite://", poolclass=StaticPool,
                       connect_args={"check_same_thread": False})
    monkeypatch.setattr(runs, "engine", db)
    return db


def test_repeated_builder_clicks_are_operational_runs_but_one_prediction(monkeypatch):
    db = _memory_engine(monkeypatch)
    result = _success([_game("m1"), _game("m2")])
    runs.record_run(2, "today", False, result)
    runs.record_run(2, "today", True, result, cached=True)

    with db.begin() as conn:
        assert len(conn.execute(select(runs.builder_runs)).all()) == 2
        predictions = conn.execute(select(runs.builder_predictions)).mappings().all()
    assert len(predictions) == 1
    assert predictions[0]["selection_fingerprint"] == leg_fingerprint(result["games"])
    assert "never-persist-this-code" not in str(dict(predictions[0]))


@pytest.mark.parametrize(
    "outcomes, expected_status, expected_return, all_win",
    [
        (["won", "won"], "won", 2.1, True),
        (["won", "void"], "won", 1.5, False),
        (["won", "lost"], "lost", 0.0, False),
        (["void", "void"], "void", 1.0, False),
    ],
)
def test_builder_prediction_settlement_and_push_accounting(
        monkeypatch, outcomes, expected_status, expected_return, all_win):
    db = _memory_engine(monkeypatch)
    games = [_game("m1", 1.5), _game("m2", 1.4, "dnb_home")]
    result = _success(games, actual_odds=2.2)
    assert runs.record_prediction(2, "today", result)
    fingerprint = leg_fingerprint(games)

    assert runs.settle_prediction(fingerprint, outcomes) == expected_status
    with db.begin() as conn:
        row = conn.execute(select(runs.builder_predictions)).mappings().one()
    assert row["actual_settled_return"] == expected_return
    assert row["all_win"] is all_win
    assert [pick["status"] for pick in json.loads(row["picks"])] == outcomes
    if "void" in outcomes and expected_status == "won":
        assert row["sportybet_settled_return"] is None


def test_builder_performance_uses_unique_predictions_and_reports_calibration(monkeypatch):
    _memory_engine(monkeypatch)
    first = _success([_game("m1", 1.5), _game("m2", 1.4)], actual_odds=2.2)
    second = _success([_game("m3", 1.8), _game("m4", 1.3)])
    runs.record_run(2, "today", False, first)
    runs.record_run(2, "today", True, first)
    runs.record_run(2, "week", False, second)
    runs.settle_prediction(leg_fingerprint(first["games"]), ["won", "won"])
    runs.settle_prediction(leg_fingerprint(second["games"]), ["won", "lost"])

    report = runs.performance(90)
    assert report["builds_generated"] == 2
    assert report["unique_settled_builds"] == 2
    assert report["won"] == 1 and report["lost"] == 1
    assert report["bookable_record"]["settled"] == 1
    assert report["bookable_record"]["coverage"] == .5
    assert report["average_predicted_hit_probability"] is not None
    assert report["actual_all_win_rate"] == .5
    assert report["brier_score"] is not None
    assert set(report["by_horizon"]) == {"today", "week"}
