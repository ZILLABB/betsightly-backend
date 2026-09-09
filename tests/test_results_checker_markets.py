"""Settlement coverage for every market the prediction engine publishes."""

import json
from datetime import datetime, timezone

import pytest

from leagues.results_checker import (
    _evaluate_pick, _lookup_score, _missing_result_expired, _rollover_day_status,
    settle_builder_predictions,
)


@pytest.mark.parametrize(
    "market,score,expected",
    [
        ("home_win", (2, 1), "won"),
        ("away_win", (2, 1), "lost"),
        ("draw", (1, 1), "won"),
        ("home_or_draw", (1, 1), "won"),
        ("away_or_draw", (2, 1), "lost"),
        ("home_or_away", (0, 0), "lost"),
        ("over_1_5", (1, 1), "won"),
        ("over_2_5", (1, 1), "lost"),
        ("under_1_5", (1, 0), "won"),
        ("under_2_5", (1, 1), "won"),
        ("under_3_5", (2, 1), "won"),
        ("under_4_5", (3, 1), "won"),
        ("home_over_0_5", (1, 0), "won"),
        ("home_over_1_5", (1, 0), "lost"),
        ("away_over_0_5", (0, 1), "won"),
        ("away_over_1_5", (0, 1), "lost"),
        ("btts_yes", (1, 1), "won"),
        ("btts_no", (1, 0), "won"),
        ("dnb_home", (2, 1), "won"),
        ("dnb_away", (2, 1), "lost"),
        ("dnb_home", (1, 1), "void"),
    ],
)
def test_specific_market_keys_settle_correctly(market, score, expected):
    pick = {"market": market, "home_team": "Home", "away_team": "Away"}
    assert _evaluate_pick(pick, *score) == expected


def test_score_lookup_prefers_the_exact_fixture_date():
    scores = {
        "home|away|2026-09-01": {"home_score": 1, "away_score": 0},
        "home|away|2026-09-08": {"home_score": 0, "away_score": 2},
        "home|away": {"home_score": 1, "away_score": 0},
    }
    assert _lookup_score(scores, "Home", "Away", "2026-09-08") == {
        "home_score": 0,
        "away_score": 2,
    }


def test_score_lookup_with_date_never_uses_a_different_fixture_date():
    scores = {
        "home|away|2026-09-01": {"home_score": 1, "away_score": 0},
        "home|away": {"home_score": 1, "away_score": 0},
    }
    assert _lookup_score(scores, "Home", "Away", "2026-09-08") is None


def test_score_lookup_without_date_can_use_legacy_pair_key():
    scores = {
        "home|away": {"home_score": 2, "away_score": 1},
    }
    assert _lookup_score(scores, "Home", "Away") == {
        "home_score": 2,
        "away_score": 1,
    }


def test_score_lookup_uses_known_alias_on_the_same_date():
    scores = {
        "united states|canada|2026-09-08": {
            "home_score": 2,
            "away_score": 0,
        },
    }
    assert _lookup_score(scores, "USA", "Canada", "2026-09-08") == {
        "home_score": 2,
        "away_score": 0,
    }


def test_rollover_market_key_takes_precedence_over_diversity_group():
    pick = {
        "market": "goals",
        "market_key": "under_4_5",
        "prediction": "Under 4.5 Goals",
    }
    assert _evaluate_pick(pick, 3, 1) == "won"
    assert _evaluate_pick(pick, 4, 1) == "lost"


def test_legacy_goals_row_can_still_settle_from_its_label():
    pick = {"market": "goals", "prediction": "Under 3.5 Goals"}
    assert _evaluate_pick(pick, 2, 1) == "won"


def test_missing_result_only_voids_after_the_reporting_grace():
    pick = {"commence_time": "2026-08-30T20:00:00Z"}
    assert not _missing_result_expired(
        pick, datetime(2026, 9, 1, 19, 59, tzinfo=timezone.utc))
    assert _missing_result_expired(
        pick, datetime(2026, 9, 1, 20, 0, tzinfo=timezone.utc))


@pytest.mark.parametrize(
    "legs,expected",
    [
        (["won", "won"], "won"),
        (["won", "void"], "won"),
        (["void", "void"], "void"),
        (["won", "pending"], "pending"),
        (["won", "lost", "void"], "lost"),
    ],
)
def test_rollover_day_settlement_handles_void_legs(legs, expected):
    assert _rollover_day_status(legs) == expected


def test_builder_settlement_routes_through_canonical_market_evaluator(monkeypatch):
    picks = [
        {"home_team": "Alpha", "away_team": "Beta", "market": "dnb_home",
         "kickoff": "2026-09-08T18:00:00Z"},
        {"home_team": "Gamma", "away_team": "Delta", "market": "under_2_5",
         "kickoff": "2026-09-08T19:00:00Z"},
    ]
    monkeypatch.setattr(
        "leagues.builder_runs.pending_predictions",
        lambda: [{"selection_fingerprint": "build-1", "picks": json.dumps(picks)}],
    )
    settled = {}

    def capture(fingerprint, outcomes):
        settled.update(fingerprint=fingerprint, outcomes=outcomes)
        return "won"

    monkeypatch.setattr("leagues.builder_runs.settle_prediction", capture)
    scores = {
        "alpha|beta|2026-09-08": {"home_score": 1, "away_score": 1},
        "gamma|delta|2026-09-08": {"home_score": 1, "away_score": 1},
    }
    result = settle_builder_predictions(
        scores=scores, now=datetime(2026, 9, 9, tzinfo=timezone.utc)
    )
    assert settled == {"fingerprint": "build-1", "outcomes": ["void", "won"]}
    assert result["won"] == 1
