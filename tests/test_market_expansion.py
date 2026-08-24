"""
The markets added once the Poisson's per-team goals were exposed, and the
guard that came with them.

The guard matters more than the markets. Real prices reached markets ESPN
never quoted, and immediately showed the model claiming a 76% edge on Over 2.5
in leagues it has no market signal for. Those picks were always wrong — an
estimated price is our own probability plus a flat margin, so it agrees with
us by construction and could never expose them. Selection would then rank them
first, because it sorts on expected value and they scored highest.
"""

import pytest

from leagues.picks import (CALIBRATION_GROUP, MARKET_GROUP, MARKET_LABELS,
                           MAX_CREDIBLE_EV, MIN_CONFIDENCE_BY_GROUP,
                           REAL_ODDS_KEY)
from leagues.predictor import predict


# ── Vocabulary consistency ─────────────────────────────────

def test_every_market_has_a_label_group_and_calibration_group():
    """A market missing from any of these fails somewhere far from the cause."""
    for market in MARKET_LABELS:
        assert market in MARKET_GROUP, f"{market} has no market group"
        assert market in CALIBRATION_GROUP, f"{market} has no calibration group"


def test_every_calibration_group_has_a_floor():
    groups = set(CALIBRATION_GROUP.values())
    missing = groups - set(MIN_CONFIDENCE_BY_GROUP)
    assert not missing, f"groups with no floor: {sorted(missing)}"


def test_team_totals_are_tracked_apart_from_match_totals():
    """Folding them together would average two accuracies into one correction."""
    assert CALIBRATION_GROUP["home_over_0_5"] == "team_goals_home"
    assert CALIBRATION_GROUP["away_over_0_5"] == "team_goals_away"
    assert CALIBRATION_GROUP["over_1_5"] == "goals_over"
    assert len({CALIBRATION_GROUP["home_over_0_5"],
                CALIBRATION_GROUP["away_over_0_5"],
                CALIBRATION_GROUP["over_1_5"]}) == 3


def test_new_groups_start_no_looser_than_the_blanket_floor():
    """They have no record yet, so they may not start below the default."""
    for group in ("team_goals_home", "team_goals_away", "dnb"):
        assert MIN_CONFIDENCE_BY_GROUP[group] >= 0.65, group


def test_draw_no_bet_floor_sits_above_the_match_result_floor():
    """Removing the draw inflates the number without adding information.

    The same opinion that reads 0.55 as a straight win reads about 0.70 with
    the draw taken out, so an unchanged floor would fill the tier with picks
    that only look safer than the pick they came from.
    """
    assert MIN_CONFIDENCE_BY_GROUP["dnb"] > MIN_CONFIDENCE_BY_GROUP["match_result"]


def test_every_published_market_can_carry_a_real_price():
    missing = sorted(set(MARKET_LABELS) - set(REAL_ODDS_KEY))
    assert not missing, f"no real-price key for: {missing}"


# ── The model actually emits them ──────────────────────────

def _fixture():
    return {"match_id": "t1", "home": {"name": "Home"}, "away": {"name": "Away"},
            "league": "Test", "league_slug": "test", "commence_time": "2026-08-24T19:00:00Z",
            "odds": {}}


def _base():
    return {"home_win": 0.45, "draw": 0.27, "away_win": 0.28,
            "over_1_5": 0.75, "over_2_5": 0.52, "btts": 0.50,
            "avg_goals": 2.6}


def test_predictor_emits_the_new_markets():
    out = predict(_fixture(), _base(), None)
    probs = out["probabilities"]
    for market in ("home_over_0_5", "away_over_0_5", "home_over_1_5",
                   "away_over_1_5", "under_1_5", "under_4_5",
                   "dnb_home", "dnb_away"):
        assert market in probs, market
        assert 0.0 <= probs[market] <= 1.0, market


def test_probabilities_stay_coherent():
    probs = predict(_fixture(), _base(), None)["probabilities"]
    # A team scoring at all is at least as likely as it scoring twice.
    assert probs["home_over_0_5"] >= probs["home_over_1_5"]
    assert probs["away_over_0_5"] >= probs["away_over_1_5"]
    # More goals is never more likely than fewer.
    assert probs["over_1_5"] >= probs["over_2_5"] >= probs["over_3_5"]
    # Draw no bet splits a decisive result between the two sides.
    assert probs["dnb_home"] + probs["dnb_away"] == pytest.approx(1.0, abs=0.02)
    # Complements.
    assert probs["under_1_5"] == pytest.approx(1 - probs["over_1_5"], abs=0.02)


def test_draw_no_bet_is_never_less_confident_than_the_straight_win():
    probs = predict(_fixture(), _base(), None)["probabilities"]
    assert probs["dnb_home"] >= probs["home_win"]
    assert probs["dnb_away"] >= probs["away_win"]


# ── The credibility guard ──────────────────────────────────

# A fit that leaves probabilities alone, so these assert the guard rather than
# whatever correction happens to be fitted from live results at the time.
NEUTRAL_FIT = {"n": 0, "global": 0.0, "groups": {}}

def test_a_pick_disagreeing_wildly_with_a_real_price_is_dropped():
    """Over 2.5 quoted at 2.60 is the market saying 38%. We said 67.5%."""
    from leagues.picks import build_picks
    fx = _fixture()
    fx["odds"] = {"provider": "SportyBet", "over_2_5": 2.60,
                  "margins": {"over_2_5": 0.05}}
    model = predict(fx, _base(), None)
    model["probabilities"] = {"over_2_5": 0.675}
    picks = build_picks(fx, model, min_confidence=0.50, fit=NEUTRAL_FIT)
    assert not [p for p in picks if p["market"] == "over_2_5"]


def test_a_believable_edge_survives():
    from leagues.picks import build_picks
    fx = _fixture()
    fx["odds"] = {"provider": "SportyBet", "over_1_5": 1.45,
                  "margins": {"over_1_5": 0.04}}
    model = predict(fx, _base(), None)
    model["probabilities"] = {"over_1_5": 0.72}   # EV 1.04 — plausible
    picks = build_picks(fx, model, min_confidence=0.50, fit=NEUTRAL_FIT)
    assert [p for p in picks if p["market"] == "over_1_5"]


def test_the_guard_only_applies_to_real_prices():
    """An estimated price agrees with us by construction and proves nothing."""
    from leagues.picks import build_picks
    fx = _fixture()
    model = predict(fx, _base(), None)
    model["probabilities"] = {"over_1_5": 0.80}
    picks = build_picks(fx, model, min_confidence=0.50, fit=NEUTRAL_FIT)
    over = [p for p in picks if p["market"] == "over_1_5"]
    assert over and not over[0]["odds_are_real"]


def test_guard_threshold_is_above_any_real_edge():
    """Line shopping is worth a few percent, never a quarter."""
    assert 1.05 <= MAX_CREDIBLE_EV < 1.50
