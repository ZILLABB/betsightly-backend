import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from leagues import builder_runs as runs
from leagues.booking import leg_fingerprint


def test_postgres_v2_schema_reconciliation_covers_release_context():
    sql = "\n".join(runs._postgres_v2_schema_statements())

    for expected in (
        "builder_runs ADD COLUMN IF NOT EXISTS mode",
        "builder_runs ADD COLUMN IF NOT EXISTS fill_strategy",
        "builder_runs ADD COLUMN IF NOT EXISTS requested_markets",
        "builder_runs ADD COLUMN IF NOT EXISTS selected_markets",
        "builder_runs ADD COLUMN IF NOT EXISTS requested_game_count",
        "builder_runs ALTER COLUMN target_odds DROP NOT NULL",
        "builder_predictions ADD COLUMN IF NOT EXISTS mode",
        "builder_predictions ADD COLUMN IF NOT EXISTS board_context",
        "builder_predictions ALTER COLUMN target_odds DROP NOT NULL",
    ):
        assert expected in sql


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


def test_builder_run_persists_safe_v2_request_and_selected_market_provenance(monkeypatch):
    db = create_engine("sqlite://", poolclass=StaticPool,
                       connect_args={"check_same_thread": False})
    monkeypatch.setattr(runs, "engine", db)
    runs.record_run(
        None, "7_days", False,
        _success([_game("m1", market="home_win"), _game("m2", market="over_1_5")]),
        mode="game_count", fill_strategy="selected_first_then_eligible",
        requested_markets=["home_win", "home_win"], requested_game_count=20,
    )
    with db.connect() as conn:
        stored = conn.execute(select(runs.builder_runs)).mappings().one()
    assert stored["mode"] == "game_count"
    assert stored["fill_strategy"] == "selected_first_then_eligible"
    assert json.loads(stored["requested_markets"]) == ["home_win"]
    assert json.loads(stored["selected_markets"]) == ["home_win", "over_1_5"]
    assert stored["requested_game_count"] == 20


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


def test_lost_builder_keeps_settling_other_legs_without_rewriting_verdict(monkeypatch):
    db = _memory_engine(monkeypatch)
    games = [_game("m1"), _game("m2")]
    assert runs.record_prediction(2, "today", _success(games))
    fingerprint = leg_fingerprint(games)
    first_evidence = {"provider": "espn", "home_score": 0, "away_score": 0}
    assert runs.settle_prediction(
        fingerprint, ["lost", "pending"],
        [{"settlement_evidence": first_evidence},
         {"settlement_pending_reason": "FINAL_SCORE_UNVERIFIED"}],
    ) == "lost"
    assert len(runs.pending_predictions()) == 1
    assert runs.settle_prediction(
        fingerprint, ["won", "won"],
        [{"settlement_evidence": {"provider": "untrusted"}},
         {"settlement_evidence": {"provider": "espn", "home_score": 2,
                                   "away_score": 1}}],
    ) == "lost"
    with db.begin() as conn:
        row = conn.execute(select(runs.builder_predictions)).mappings().one()
    picks = json.loads(row["picks"])
    assert [pick["status"] for pick in picks] == ["lost", "won"]
    assert picks[0]["settlement_evidence"] == first_evidence
    assert picks[1]["settlement_evidence"]["provider"] == "espn"
    assert "settlement_pending_reason" not in picks[1]
    assert row["actual_settled_return"] == 0.0


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


def test_builder_summary_covers_v2_request_dimensions(monkeypatch):
    _memory_engine(monkeypatch)

    runs.record_run(
        50,
        "7_days",
        False,
        _success(
            [
                _game("m10", market="over_1_5"),
                _game("m11", market="home_win"),
            ],
            target=50,
            actual_odds=4.2,
        ),
        mode="target_odds",
        fill_strategy="strict_selected_markets",
        requested_markets=["over_1_5"],
    )

    runs.record_run(
        None,
        "today",
        False,
        _success(
            [
                _game("m12", market="over_1_5"),
                _game("m13", market="over_1_5"),
            ],
            actual_odds=2.1,
        ),
        mode="game_count",
        fill_strategy="selected_first_then_eligible",
        requested_markets=["over_1_5", "over_2_5"],
        requested_game_count=20,
    )

    report = runs.summary(
        "2000-01-01",
        "2100-01-01",
    )

    assert report["requests"] == 2
    assert {
        item["mode"]
        for item in report["by_mode"]
    } == {
        "target_odds",
        "game_count",
    }

    assert report["by_game_count"] == [
        {
            "game_count": "20",
            "requests": 1,
            "tickets_produced": 1,
            "ticket_rate": 1.0,
            "cache_hits": 0,
        }
    ]

    requested = {
        item["market"]: item
        for item in report["by_requested_market"]
    }

    assert requested["over_1_5"]["requests"] == 2
    assert requested["over_2_5"]["requests"] == 1

    selected = {
        item["market"]: item
        for item in report["by_selected_market"]
    }

    assert selected["over_1_5"]["requests"] == 2
    assert selected["home_win"]["requests"] == 1

    assert report["contract"]["share_codes_persisted"] is False


def test_builder_performance_reports_mode_leg_and_market_presence(monkeypatch):
    _memory_engine(monkeypatch)

    target_result = _success([
        _game("p1", 1.5, "over_1_5"),
        _game("p2", 1.4, "home_win"),
    ])

    count_result = _success([
        _game("p3", 1.6, "over_1_5"),
        _game("p4", 1.3, "over_1_5"),
        _game("p5", 1.2, "away_or_draw"),
    ])

    runs.record_prediction(
        2,
        "today",
        target_result,
        mode="target_odds",
    )

    runs.record_prediction(
        None,
        "7_days",
        count_result,
        mode="game_count",
    )

    runs.settle_prediction(
        leg_fingerprint(target_result["games"]),
        ["won", "won"],
    )

    runs.settle_prediction(
        leg_fingerprint(count_result["games"]),
        ["won", "lost", "won"],
    )

    report = runs.performance(90)

    assert set(report["by_mode"]) == {
        "target_odds",
        "game_count",
    }

    assert set(report["by_leg_count"]) == {
        "2",
        "3",
    }

    assert (
        report["by_market_presence"]["over_1_5"]
        ["unique_settled_builds"]
        == 2
    )

    assert (
        report["by_market_presence"]["home_win"]
        ["unique_settled_builds"]
        == 1
    )

    assert report["pending_builds"] == 0
