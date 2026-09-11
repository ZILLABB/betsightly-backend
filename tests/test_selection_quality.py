import pytest

from leagues.selection import select_accumulator
from leagues.selection_quality import (
    price_quality,
    risk_adjusted_return,
    selection_probability,
)


def _pick(match_id="one", confidence=.80, odds=1.30, **changes):
    pick = {
        "match_id": match_id,
        "market": "over_1_5",
        "market_group": "goals_over_1_5",
        "confidence": confidence,
        "odds": odds,
        "odds_are_real": True,
        "bookable": True,
        "expected_value": confidence * odds - 1,
    }
    pick.update(changes)
    return pick


def test_positive_evidence_never_inflates_calibrated_probability():
    pick = _pick(
        confidence=.72,
        evidence_adjusted_probability=.85,
        lower_reliability_bound=.68,
        evidence_strength=1,
    )
    assert selection_probability(pick) <= .72


def test_negative_evidence_and_lower_bound_reduce_selection_probability():
    pick = _pick(
        confidence=.82,
        evidence_adjusted_probability=.70,
        lower_reliability_bound=.58,
        evidence_strength=.5,
    )
    probability = selection_probability(pick)
    assert .58 < probability < .70
    assert probability < pick["confidence"]


def test_grade_b_uses_lower_bound_instead_of_point_estimate():
    pick = _pick(confidence=.80, trust={
        "trust_grade": "B",
        "evidence_adjusted_probability": .76,
        "lower_reliability_bound": .61,
        "evidence_strength": .9,
    })
    assert selection_probability(pick) == pytest.approx(.61)


def test_unsupported_bookmaker_disagreement_is_continuously_penalized():
    agreed = _pick(confidence=.78, market_implied_probability=.76)
    disagreed = _pick(confidence=.78, market_implied_probability=.55)
    assert selection_probability(disagreed) < selection_probability(agreed)


def test_risk_adjusted_return_uses_conservative_probability():
    pick = _pick(
        confidence=.85,
        odds=1.4,
        evidence_adjusted_probability=.74,
        lower_reliability_bound=.64,
        evidence_strength=.5,
    )
    assert risk_adjusted_return(pick) == pytest.approx(
        selection_probability(pick) * 1.4
    )


def test_price_quality_uses_conservative_probability_and_marks_negative_price():
    pick = _pick(
        confidence=.85, odds=1.32,
        evidence_adjusted_probability=.73,
        lower_reliability_bound=.69, evidence_strength=.5,
    )
    quality = price_quality(pick)
    assert quality["selection_probability"] < pick["confidence"]
    assert quality["selection_probability"] < quality["raw_break_even_probability"]
    assert quality["price_quality_reason_codes"] == ["PRICE_NEGATIVE"]


def test_dnb_price_quality_is_push_aware():
    pick = _pick(
        market="dnb_home", confidence=.75, odds=1.23,
        _model={"probabilities": {"draw": .25}},
    )
    quality = price_quality(pick)
    assert quality["raw_break_even_probability"] is None
    assert quality["push_aware_expected_return"] == pytest.approx(
        .75 * .75 * 1.23 + .25
    )
    assert "DNB_PUSH_AWARE" in quality["price_quality_reason_codes"]


def test_accumulator_prefers_stronger_conservative_leg_over_hot_raw_confidence():
    uncertain = _pick(
        "uncertain", confidence=.90, odds=2.0,
        evidence_adjusted_probability=.68,
        lower_reliability_bound=.52,
        evidence_strength=.2,
    )
    supported = _pick(
        "supported", confidence=.76, odds=2.0,
        evidence_adjusted_probability=.75,
        lower_reliability_bound=.72,
        evidence_strength=.9,
    )
    chosen, _, joint = select_accumulator(
        [uncertain, supported], target_odds=2, max_picks=1,
        min_confidence=.50, min_ev=0, max_leg_ev=2,
        canonicalize=False,
    )
    assert chosen[0]["match_id"] == "supported"
    assert joint == pytest.approx(selection_probability(supported), abs=1.1e-4)
