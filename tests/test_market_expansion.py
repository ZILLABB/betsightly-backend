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


def test_a_group_without_a_floor_falls_back_to_the_blanket_default():
    """A missing floor is the correct state for a market with no record.

    Only groups with settled evidence carry a tailored floor; everything else
    inherits MIN_PUBLISHABLE_CONFIDENCE until MIN_EVIDENCE_LEGS is satisfied.
    Requiring an entry for every group would mean inventing a number for
    markets that have never settled a leg.
    """
    from leagues.picks import MIN_PUBLISHABLE_CONFIDENCE, min_confidence_for
    for market, group in CALIBRATION_GROUP.items():
        if group in MIN_CONFIDENCE_BY_GROUP:
            continue
        assert min_confidence_for(market, fit={"n": 0, "groups": {}}) ==             MIN_PUBLISHABLE_CONFIDENCE, market


def test_no_floor_is_looser_than_the_default_without_evidence():
    """A tailored floor below the default must be earned, never assumed."""
    from leagues.picks import MIN_PUBLISHABLE_CONFIDENCE, min_confidence_for
    thin = {"n": 0, "groups": {}}
    for market in CALIBRATION_GROUP:
        assert min_confidence_for(market, fit=thin) >= MIN_PUBLISHABLE_CONFIDENCE, market


def test_team_totals_are_tracked_apart_from_match_totals():
    """Folding them together would average two accuracies into one correction."""
    assert CALIBRATION_GROUP["home_over_0_5"] == "team_goals_home"
    assert CALIBRATION_GROUP["away_over_0_5"] == "team_goals_away"
    assert CALIBRATION_GROUP["over_1_5"] == "goals_over_1_5"
    assert len({CALIBRATION_GROUP["home_over_0_5"],
                CALIBRATION_GROUP["away_over_0_5"],
                CALIBRATION_GROUP["over_1_5"]}) == 3


def test_each_goal_line_is_calibrated_on_its_own_record():
    """A shift fitted on under 2.5 has no business steering under 4.5.

    The whole under record is 13 legs, all under_2_5, sitting near 55%. Under
    4.5 sits near 85%. Sharing one logit correction between them corrects
    neither.
    """
    lines = ["over_1_5", "over_2_5", "over_3_5",
             "under_1_5", "under_2_5", "under_3_5", "under_4_5"]
    cells = {CALIBRATION_GROUP[m] for m in lines}
    assert len(cells) == len(lines), f"goal lines sharing a cell: {cells}"


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


def test_unseen_market_gets_no_global_calibration_boost():
    """A correction earned by other markets cannot lift a new goal line."""
    from leagues.calibrator import calibrate
    fit = {"n": 100, "global": 0.4, "groups": {}}
    assert calibrate(0.755, "goals_under_4_5", fit) == pytest.approx(0.755)


def test_pick_reports_its_own_evidence_and_real_model_count():
    from leagues.picks import build_picks, to_game
    fx = _fixture()
    fx["odds"] = {"provider": "SportyBet", "under_4_5": 1.30,
                  "margins": {"under_4_5": 0.05}}
    model = predict(fx, _base(), None)
    model["probabilities"] = {"under_4_5": 0.75}
    model["ml"] = None
    fit = {"n": 100, "global": 0.2, "groups": {}}
    picks = build_picks(fx, model, min_confidence=0.50, fit=fit)
    pick = picks[0]
    game = to_game(pick)
    assert pick["calibration_sample"] == 0
    assert not pick["safe_tier_eligible"]
    assert game["models_agreed"] == 1
    assert game["model_sources"] == ["league base + Poisson"]


def test_ml_can_veto_a_severe_disagreement(monkeypatch):
    from leagues.picks import build_picks
    fx = _fixture()
    fx["odds"] = {"provider": "SportyBet", "over_1_5": 1.35,
                  "margins": {"over_1_5": 0.04}}
    model = predict(fx, _base(), None)
    model["probabilities"] = {"over_1_5": 0.75}
    model["ml"] = {"over_1_5": 0.50}
    monkeypatch.setattr("leagues.picks._ml_for", lambda *_: 0.50)
    assert not build_picks(fx, model, min_confidence=0.50, fit=NEUTRAL_FIT)


# ── Team totals inherit BTTS's caution ─────────────────────

def test_team_totals_are_not_published_more_freely_than_btts():
    """They are BTTS taken apart, so they cannot have an easier bar.

    The model's btts_yes is (1 - e^-λh)(1 - e^-λa) — precisely
    home_over_0_5 multiplied by away_over_0_5. Publishing each half at 0.65
    while holding the product at 0.70 would let the same error back in
    through a door already shut, and BTTS is the worst-calibrated market
    there is: 28 legs promising 58% and delivering 50%.
    """
    btts = MIN_CONFIDENCE_BY_GROUP["btts_yes"]
    assert MIN_CONFIDENCE_BY_GROUP["team_goals_home"] >= btts
    assert MIN_CONFIDENCE_BY_GROUP["team_goals_away"] >= btts


def test_btts_really_is_the_product_of_the_two_team_totals():
    """If this stops holding, the floor above is guarding the wrong thing."""
    import math
    probs = predict(_fixture(), _base(), None)["probabilities"]
    eg = predict(_fixture(), _base(), None)["expected_goals"]
    raw_product = (1 - math.exp(-eg["home"])) * (1 - math.exp(-eg["away"]))
    # btts is blended toward the league base rate, so this is a family
    # resemblance rather than an identity — but a distant one would mean the
    # two are no longer the same claim.
    assert abs(probs["btts_yes"] - raw_product) < 0.15
    assert abs(probs["home_over_0_5"] - (1 - math.exp(-eg["home"]))) < 0.01
