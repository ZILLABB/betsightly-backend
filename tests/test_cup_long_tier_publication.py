"""Cup evidence tier policy regression: keep safe tiers strict, help longer tiers.

The positive fixture examples are intentionally synthetic. Real cup legs still
must pass bookmaker identity, current price, trusted calibration, value,
exposure and slip validation before publication.
"""
from copy import deepcopy
import pytest

from leagues.publication_policy import (
    evaluate_leg, evaluate_slip, filter_official_candidates,
)


def cup(**updates):
    item = {
        "match_id": "esp-cup-101",
        "market": "over_1_5", "market_key": "over_1_5",
        "market_group": "goals",
        "prediction": "Over 1.5",
        "confidence": .78,
        "odds": 1.55,
        "odds_are_real": True,
        "bookable": True,
        "market_floor_eligible": True,
        "safe_tier_eligible": False,
        "calibration_sample": 32,
        "competition_historical_sample": 8,
        "base_rate_source": "competition_type:DOMESTIC_CUP",
        "market_trust_state": "TRUSTED",
        "trust": {
            "accepted": True, "trust_grade": "A",
            "evidence_state": "SUPPORTED",
            "lower_reliability_bound": .73,
            "evidence_adjusted_probability": .78,
            "evidence_strength": .90,
        },
        "_fixture": {
            "league_slug": "esp.copa_del_rey",
            "competition_type": "DOMESTIC_CUP",
            "competition_historical_sample": 8,
            "commence_time": "2026-10-29T20:00:00Z",
        },
    }
    item.update(updates)
    return item


def test_confirmed_cup_can_reach_only_long_tiers_with_own_market_evidence():
    pick = cup()
    assert not evaluate_leg(pick, "2_odds")["allowed"]
    assert not evaluate_leg(pick, "banker")["allowed"]
    assert not evaluate_leg(pick, "over_1_5")["allowed"]
    assert not evaluate_leg(pick, "rollover")["allowed"]
    assert evaluate_leg(pick, "5_odds")["allowed"]
    assert evaluate_leg(pick, "10_odds")["allowed"]


def test_long_cup_pool_does_not_leak_into_two_odds_pool():
    p = cup()
    long_good, _ = filter_official_candidates([p], "5_odds")
    two_good, reasons = filter_official_candidates([p], "2_odds")
    assert long_good == [p]
    assert two_good == []
    assert "INSUFFICIENT_SETTLED_EVIDENCE" in reasons[0]["reasons"]


@pytest.mark.parametrize("changes", [
    {"calibration_sample": 24},
    {"competition_historical_sample": 0},
    {"competition_historical_sample": 20},
    {"base_rate_source": "global_default"},
    {"market_trust_state": "RESTRICTED"},
    {"bookable": False},
    {"odds_are_real": False},
    {"trust": {"accepted": False, "trust_grade": "A",
               "evidence_state": "SUPPORTED", "lower_reliability_bound": .8}},
    {"trust": {"accepted": True, "trust_grade": "C",
               "evidence_state": "SUPPORTED", "lower_reliability_bound": .8}},
    {"trust": {"accepted": True, "trust_grade": "A",
               "evidence_state": "SHADOW", "lower_reliability_bound": .8}},
    {"trust": {"accepted": True, "trust_grade": "A",
               "evidence_state": "SUPPORTED", "lower_reliability_bound": .59}},
])
def test_missing_injury_or_calibration_evidence_cannot_reach_long_tiers(changes):
    p = cup(**changes)
    assert not evaluate_leg(p, "5_odds")["allowed"]
    assert not evaluate_leg(p, "10_odds")["allowed"]


def test_unregistered_competition_cannot_get_cup_allowance():
    p = cup()
    p["_fixture"]["league_slug"] = "esp.1"
    assert not evaluate_leg(p, "5_odds")["allowed"]


def test_empty_settled_cup_history_still_denied():
    p = cup(competition_historical_sample=0)
    p["_fixture"]["competition_historical_sample"] = 0
    assert not evaluate_leg(p, "5_odds")["allowed"]


def test_under_goals_and_negative_quote_still_blocked():
    under = cup(market="under_2_5", market_key="under_2_5")
    assert not evaluate_leg(under, "10_odds")["allowed"]
    bad_price = cup(odds=1.08)
    assert "NEGATIVE_MODEL_VALUE" in evaluate_leg(bad_price, "5_odds")["reasons"]


def test_final_slip_guard_still_evaluates_every_cup_leg():
    game = cup()
    base = evaluate_slip([game], "5_odds")
    assert base["allowed"] is True
    mutated = deepcopy(game)
    mutated["market_trust_state"] = "SHADOW"
    assert evaluate_slip([mutated], "5_odds")["allowed"] is False


def test_non_cup_markets_never_bypass_safe_tier():
    league = cup()
    league["_fixture"]["league_slug"] = "eng.1"
    league["_fixture"]["competition_type"] = "LEAGUE"
    assert "INSUFFICIENT_SETTLED_EVIDENCE" in evaluate_leg(
        league, "10_odds")["reasons"]
