"""Settlement coverage for every market the prediction engine publishes."""

import pytest

from leagues.results_checker import _evaluate_pick


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

