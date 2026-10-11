"""Logic and leak-free settlement targets for offline FT challenger."""
import math

import pytest

from leagues.goal_distribution_challenger import (
    from_grid, probabilities, score_grid, settlement_labels,
)


@pytest.mark.parametrize("home,away", [(0, 0), (0.3, 2.5), (1.4, 1.1),
                                     (3.5, 2.1), (6.1, 5.8)])
def test_grid_is_normalized_and_probability_coherent(home, away):
    grid = score_grid(home, away)
    assert sum(map(sum, grid)) == pytest.approx(1.0, abs=1e-10)
    p = from_grid(grid)
    assert p["home_win"] + p["draw"] + p["away_win"] == pytest.approx(1.0)
    assert p["home_or_draw"] == pytest.approx(p["home_win"] + p["draw"])
    assert p["away_or_draw"] == pytest.approx(p["away_win"] + p["draw"])
    assert p["btts_yes"] <= p["over_1_5"] + 1e-12
    assert p["btts_yes"] <= p["home_over_0_5"] + 1e-12
    assert p["btts_yes"] <= p["away_over_0_5"] + 1e-12
    assert (p["over_0_5"] >= p["over_1_5"] >= p["over_2_5"]
            >= p["over_3_5"] >= p["over_4_5"])
    assert p["home_over_0_5"] >= p["home_over_1_5"]
    assert p["away_over_0_5"] >= p["away_over_1_5"]
    for line in ("0_5", "1_5", "2_5", "3_5", "4_5"):
        assert p[f"under_{line}"] + p[f"over_{line}"] == pytest.approx(1.0)
    for side in ("home", "away"):
        for line in ("0_5", "1_5"):
            assert p[f"{side}_under_{line}"] + p[f"{side}_over_{line}"] == pytest.approx(1.0)
    if p["home_win"] + p["away_win"] > 1e-12:
        assert p["dnb_home"] + p["dnb_away"] == pytest.approx(1.0)


def test_zero_goal_distribution_is_deterministic():
    p = probabilities(0, 0)
    assert p["draw"] == pytest.approx(1.0)
    assert p["over_0_5"] == pytest.approx(0.0)
    assert p["under_4_5"] == pytest.approx(1.0)
    assert p["btts_yes"] == pytest.approx(0.0)
    assert p["dnb_home"] is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1])
def test_bad_expected_goals_refused(value):
    with pytest.raises(ValueError):
        score_grid(value, 1.5)


def test_bad_grid_refused():
    with pytest.raises(ValueError):
        from_grid([[0.2, 0.2], [0.2, 0.2]])
    with pytest.raises(ValueError):
        from_grid([[math.nan]])


@pytest.mark.parametrize("h,a,over15,btts,homewin", [
    (0, 0, 0, 0, 0), (1, 0, 0, 0, 1), (1, 1, 1, 1, 0),
    (3, 1, 1, 1, 1), (0, 4, 1, 0, 0),
])
def test_labels_derive_from_final_scores(h, a, over15, btts, homewin):
    labels = settlement_labels(h, a)
    assert labels["over_1_5"] == over15
    assert labels["btts_yes"] == btts
    assert labels["home_win"] == homewin
    assert labels["btts_yes"] <= labels["over_1_5"]
    assert labels["under_2_5"] == int(h + a <= 2)
    assert labels["home_over_0_5"] == int(h > 0)
    assert labels["away_over_0_5"] == int(a > 0)
    assert labels["under_0_5"] == int(h + a == 0)


def test_draw_no_bet_draw_is_push_not_loss():
    labels = settlement_labels(2, 2)
    assert labels["dnb_home"] is None
    assert labels["dnb_away"] is None
    assert labels["home_or_draw"] == labels["away_or_draw"] == 1


def test_score_labels_do_not_require_bookmaker_prices():
    assert "over_0_5" in settlement_labels(1, 0)
    assert "btts_no" in settlement_labels(1, 0)


@pytest.mark.parametrize("score", [(-1, 0), (2.0, 1), (False, 1)])
def test_invalid_settlement_scores_rejected(score):
    with pytest.raises(ValueError):
        settlement_labels(*score)
