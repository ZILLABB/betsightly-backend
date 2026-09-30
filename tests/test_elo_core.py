import pytest
from leagues import elo_core, elo_engine


def test_shared_elo_core_uses_live_contract():
    assert elo_core.DEFAULT_RATING == 1500.0
    assert elo_core.K_FACTOR == 20.0
    assert elo_core.HOME_ADVANTAGE == 60.0
    assert elo_core.MIN_MATCHES == 3
    assert elo_core.HISTORY_DAYS == 240


def test_goal_difference_multiplier_matches_previous_live_rule():
    assert elo_core.goal_difference_multiplier(1, 0) == 1.0
    assert elo_core.goal_difference_multiplier(2, 0) == 1.5
    assert elo_core.goal_difference_multiplier(3, 0) == 1.75
    assert elo_core.goal_difference_multiplier(4, 0) == 1.875


def test_live_run_elo_delegates_to_shared_core():
    matches = [
        {"home": "A", "away": "B", "hs": 3, "as": 0, "neutral": False},
        {"home": "B", "away": "A", "hs": 1, "as": 1, "neutral": False},
    ]
    expected = elo_core.run_elo(matches)
    actual = elo_engine._run_elo(matches)
    assert actual[0] == pytest.approx(expected[0])
    assert actual[1] == expected[1]


def test_three_way_probability_contract_preserves_neutral_symmetry():
    result = elo_core.three_way_probabilities(1600, 1600, neutral=True)
    assert result["home_win"] == result["away_win"]
    assert result["home_advantage_applied"] == 0.0
