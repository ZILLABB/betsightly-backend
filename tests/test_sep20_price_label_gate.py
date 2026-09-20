"""Regressions for the September 20 price-versus-confidence labelling defect."""
from leagues import recommendation_board as board


def candidate(probability, odds, *, real=True, market="under_4_5"):
    return {
        "match_id": "m1", "market": market, "confidence": probability,
        "odds": odds, "odds_are_real": real,
        "market_trust_state": "TRUSTED", "market_floor_eligible": True,
        "safe_tier_eligible": True, "public_rank": 1,
    }


def test_high_confidence_negative_price_is_not_strong():
    pick = candidate(.91, 1.07)
    assert not board._price_eligible(pick)
    assert board.recommendation_classification(pick) == "LEAN"


def test_estimated_price_is_never_premium():
    pick = candidate(.90, 1.30, real=False)
    assert not board._price_eligible(pick)
    assert board.recommendation_classification(pick) == "LEAN"


def test_strong_still_possible_with_real_positive_conservative_price():
    pick = candidate(.80, 1.40)
    assert board._price_eligible(pick)
    assert board.recommendation_classification(pick) == "STRONG"


def test_dnb_draw_refund_uses_push_aware_return():
    pick = candidate(.70, 1.40, market="dnb_home")
    pick["_model"] = {"probabilities": {"draw": .30}}
    # A 70% conditional win chance at 1.40 is below break-even with a push.
    assert not board._price_eligible(pick)


def test_board_premium_and_safe_flags_cannot_ignore_negative_price(monkeypatch):
    pick = candidate(.91, 1.07)
    monkeypatch.setattr(board, "kickoff_wat_date", lambda _: "2026-09-20")
    monkeypatch.setattr(board, "canonical_fixture_recommendations",
                        lambda picks, **kwargs: picks)
    monkeypatch.setattr(board, "to_game", lambda p: dict(p))
    fixture = {"match_id": "m1", "home": {"name": "A"},
               "away": {"name": "B"}, "commence_time": "2026-09-20T14:00:00+01:00"}
    result = board.build_recommendation_board([pick], [fixture], date="2026-09-20")
    row = result["recommendations"][0]
    assert row["classification"] == "LEAN"
    assert row["premium_eligible"] is False
    assert row["safe_tier_eligible"] is False
    assert row["best_pick"]["market"] == "under_4_5"  # Never rewrite published bet.
