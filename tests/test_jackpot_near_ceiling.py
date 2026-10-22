"""Regression for false 'unreachable' decisions near the raw odds ceiling."""
import math

import growth.jackpot_optimizer as optimizer


def test_8000_reference_target_with_8049_ceiling_is_not_falsely_unreachable():
    price = 8049.56 ** (1 / 30)
    rows = [
        {"match_id": f"f{i}", "selection_id": f"f{i}:home_win",
         "market": "home_win", "odds": price,
         "selection_probability": .69, "lower_reliability_bound": .67}
        for i in range(30)
    ]
    assert math.isclose(optimizer.capacity(rows)["maximum_reference_odds"], 8049.56, rel_tol=1e-5)
    proposal = optimizer.optimize(rows, 8000)
    assert proposal["status"] == "PROPOSED_NOT_BOOKED"
    assert proposal["indicative_odds"] >= 8000
    assert len(proposal["selection_ids"]) == 30
    assert len(set(proposal["selection_ids"])) == 30


def test_bucket_search_missing_feasible_path_can_still_return_exact_witness(monkeypatch):
    rows = [
        {"match_id": f"f{i}", "selection_id": f"f{i}:away_win",
         "market": "away_win", "odds": 2.1,
         "selection_probability": .67}
        for i in range(3)
    ]
    monkeypatch.setattr(optimizer, "_frontier", lambda _: [])
    result = optimizer.optimize(rows, 8)
    assert result["status"] == "PROPOSED_NOT_BOOKED"
    assert result["portfolio_type"] == "HIGH_RISK_CEILING_EXPERIMENT"
    assert result["legs"] == 3
    assert result["indicative_odds"] > 8


def test_no_false_positive_when_highest_price_has_no_model_probability():
    rows = [
        {"match_id": "a", "selection_id": "a:over_2_5", "market": "over_2_5",
         "odds": 12, "selection_probability": None},
        {"match_id": "a", "selection_id": "a:over_1_5", "market": "over_1_5",
         "odds": 1.5, "selection_probability": .70},
        {"match_id": "b", "selection_id": "b:home_win", "market": "home_win",
         "odds": 4, "selection_probability": .70},
    ]
    result = optimizer.optimize(rows, 20)
    assert result["status"] == "INSUFFICIENT_MODEL_EVIDENCE"
    assert result["maximum_reference_odds"] == 48
    assert result["maximum_model_eligible_reference_odds"] == 6
    assert result["selection_ids"] == []


def test_model_ceiling_obeys_max_leg_limit_and_one_market_per_fixture():
    rows = [
        {"match_id": "a", "selection_id": "a:big", "market": "away_win",
         "odds": 6, "selection_probability": .60},
        {"match_id": "a", "selection_id": "a:medium", "market": "over_2_5",
         "odds": 3, "selection_probability": .70},
        {"match_id": "b", "selection_id": "b:big", "market": "away_win",
         "odds": 4, "selection_probability": .70},
    ]
    outcome = optimizer.optimize(rows, 5, limit=1)
    assert outcome["status"] == "PROPOSED_NOT_BOOKED"
    assert outcome["legs"] == 1
    assert outcome["selection_ids"] == ["a:big"]
