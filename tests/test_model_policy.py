from leagues.market_registry import MARKETS
from leagues.model_policy import evaluate_market, market_policy


def _row(index, *, cutoff="2025-01-01", probability=.7,
         challenger=.8, outcome=1):
    return {
        "fixture_id": f"fixture-{index}", "date": "2026-09-01",
        "market": "home_win", "outcome": outcome, "league": "test",
        "model_probabilities": {"base_model": probability,
                                "xgboost": challenger},
        "training_cutoffs": {"base_model": cutoff, "xgboost": cutoff},
    }


def test_every_market_keeps_existing_champion_without_validated_promotion():
    assert {market_policy(key)["champion"] for key in MARKETS} == {"base_model"}
    assert market_policy("under_3_5")["challengers"] == []
    assert "xgboost" in market_policy("home_win")["challengers"]
    assert evaluate_market("home_win", [])["automatic_promotion"] is False


def test_missing_provenance_and_training_overlap_fail_closed():
    rows = [_row(1, cutoff="2026-09-01"), _row(2), _row(2)]
    rows[1]["training_cutoffs"].pop("xgboost")
    report = evaluate_market("home_win", rows)
    assert report["metrics"]["xgboost"]["n"] == 0
    assert report["rejected"]["TRAINING_OVERLAP"] >= 1
    assert report["rejected"]["DUPLICATE_OR_MISSING_FIXTURE"] == 1
    assert report["comparisons"]["xgboost"]["status"] == "NO_OOS_EVIDENCE"


def test_small_apparent_win_cannot_promote_challenger():
    report = evaluate_market("home_win", [_row(i) for i in range(20)])
    assert report["comparisons"]["xgboost"]["n"] == 20
    assert report["comparisons"]["xgboost"]["status"] == "KEEP_CHAMPION"
    assert report["automatic_promotion"] is False


def test_unsupported_market_has_no_fake_ml_comparison():
    rows = [{**_row(1), "market": "under_4_5"}]
    report = evaluate_market("under_4_5", rows)
    assert report["policy"]["challengers"] == []
    assert report["comparisons"] == {}
