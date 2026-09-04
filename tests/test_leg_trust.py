import pytest

from leagues.leg_trust import evaluate_leg_trust, no_vig_probability


def _pick(**changes):
    pick = {
        "match_id": "fixture-1", "market": "over_1_5", "confidence": .74,
        "raw_confidence": .76, "calibration_group": "goals_over_1_5",
        "calibration_sample": 60, "safe_tier_eligible": True, "bookable": True,
        "market_implied_probability": .70, "ml_confidence": .72,
        "sportybet_availability": {"status": "BOOKABLE", "sportybet_available": True,
                                     "board_snapshot_id": "board-1"},
        "_fixture": {"commence_time": "2099-01-01T12:00:00Z"},
    }
    pick.update(changes)
    return pick


def test_trusted_leg_is_accepted():
    decision = evaluate_leg_trust(_pick())
    assert decision["accepted"]
    assert decision["trust_grade"] in ("A", "B")


def test_sparse_market_is_rejected_conservatively():
    decision = evaluate_leg_trust(_pick(calibration_sample=3, safe_tier_eligible=False))
    assert not decision["accepted"]
    assert "insufficient_market_evidence" in decision["rejection_reasons"]


def test_large_market_disagreement_is_rejected():
    decision = evaluate_leg_trust(_pick(market_implied_probability=.40))
    assert not decision["accepted"]
    assert "large_model_market_disagreement" in decision["rejection_reasons"]


def test_stale_or_missing_sportybet_selection_is_rejected():
    decision = evaluate_leg_trust(_pick(bookable=False,
        sportybet_availability={"status": "SELECTION_NOT_FOUND", "sportybet_available": False}))
    assert not decision["accepted"]


def test_no_vig_probability_normalizes_complete_market():
    assert no_vig_probability(2.0, [2.0, 2.0]) == pytest.approx(.5)
    assert no_vig_probability(2.0, [2.0]) is None
