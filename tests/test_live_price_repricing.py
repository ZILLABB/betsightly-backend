from leagues.leg_trust import evaluate_leg_trust, reprice_for_live_sportybet
from leagues.ml_models import feature_provenance

def test_dalin_like_sparse_live_price_is_repriced_before_trust():
    pick={"confidence":.71,"raw_confidence":.71,"market":"home_or_draw","bookable":True,"match_id":"d","calibration_sample":0,"competition_historical_sample":0,"base_rate_source":"global_default","_fixture":{"commence_time":"2099-01-01T12:00:00Z"},"sportybet_availability":{"status":"BOOKABLE","sportybet_available":True,"sportybet_odds":4.9}}
    reprice_for_live_sportybet(pick)
    trust=evaluate_leg_trust(pick)
    assert pick["market_implied_probability"] == round(1/4.9,6)
    assert "EXTREME_PRICE_MODEL_DISAGREEMENT" in pick["price_quality_reason_codes"]
    assert "SPARSE_COMPETITION_EVIDENCE" in pick["price_quality_reason_codes"]
    assert trust["trust_grade"] != "A"
    assert trust["accepted"] is False
    assert trust["evidence_adjusted_probability"] < pick["confidence"]


def test_neutral_ml_vector_is_not_treated_as_independent_agreement():
    pick={"confidence":.71,"market":"home_or_draw","bookable":True,"match_id":"d","calibration_sample":0,"competition_historical_sample":0,"base_rate_source":"global_default","ml_confidence":.10,"ml_provenance":"NEUTRAL_FALLBACK","_fixture":{"commence_time":"2099-01-01T12:00:00Z"},"sportybet_availability":{"status":"BOOKABLE","sportybet_available":True,"sportybet_odds":4.9}}
    reprice_for_live_sportybet(pick)
    trust=evaluate_leg_trust(pick)
    assert trust["internal_model_agreement"] is None
    assert "large_internal_model_disagreement" not in trust["rejection_reasons"]


def test_feature_provenance_distinguishes_real_partial_and_neutral_history():
    class Index:
        by_team = {("CLUB", "Home"): [1, 2, 3], ("CLUB", "Away"): [1, 2, 3]}
    fixture = {"home": {"name": "Home"}, "away": {"name": "Away"}}
    assert feature_provenance(fixture, Index()) == "REAL"
    Index.by_team.pop(("CLUB", "Away"))
    assert feature_provenance(fixture, Index()) == "PARTIAL"
    Index.by_team.clear()
    assert feature_provenance(fixture, Index()) == "NEUTRAL_FALLBACK"
