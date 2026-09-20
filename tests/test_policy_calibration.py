from leagues import calibrator
from leagues.forecast_observations import deduplicate_forecasts
from leagues.policy_version import PUBLISHED_SELECTION_POLICY_VERSION


def _leg(match, market, probability, status="won"):
    return {
        "match_id": match, "market": market, "confidence": probability,
        "raw_confidence": probability, "status": status,
        "commence_time": "2026-09-08T18:00:00Z",
    }


def _slip(category, leg, created, policy=None):
    return {
        "date": "2026-09-08", "category": category, "picks": [leg],
        "created_at": created, "policy_version": policy,
    }


def test_identical_forecast_across_products_and_rollover_counts_once():
    slips = [
        _slip("over_1_5", _leg("m1", "over_1_5", .71), "2026-09-08T08:00:00"),
        _slip("2_odds", _leg("m1", "over_1_5", .82), "2026-09-08T08:01:00"),
    ]
    rollover = [{
        "date": "2026-09-08", "created_at": "2026-09-08T08:02:00",
        "picks": [_leg("m1", "over_1_5", .90)],
    }]
    rows = deduplicate_forecasts(slips, rollover)
    assert len(rows) == 1
    assert rows[0]["probability"] == .71
    assert rows[0]["duplicate_count"] == 3
    assert rows[0]["categories"] == ["over_1_5", "2_odds", "rollover"]


def test_different_markets_on_same_fixture_remain_separate():
    rows = deduplicate_forecasts([
        _slip(
            "2_odds", _leg("m1", "over_1_5", .72),
            "2026-09-08T08:00:00",
        ),
        _slip(
            "5_odds", _leg("m1", "home_or_draw", .80),
            "2026-09-08T08:01:00",
        ),
    ])
    assert len(rows) == 2


def _observation(index, won, policy):
    return {
        "identity": str(index), "market": "over_1_5",
        "raw_probability": .70, "probability": .70, "won": won,
        "policy_version": policy, "categories": ["2_odds"],
        "duplicate_count": 1,
    }


def _fit(current_n):
    historical = [_observation(i, i % 5 < 3, None) for i in range(100)]
    current = [_observation(100 + i, i % 5 < 4,
                            PUBLISHED_SELECTION_POLICY_VERSION)
               for i in range(current_n)]
    return calibrator._fit_observations(historical + current, 1.0)


def test_policy_weight_grows_continuously_without_manual_switch():
    expected = {0: 0.0, 5: 5 / 35, 30: .5, 50: .625, 200: 200 / 230}
    shifts = []
    for sample, weight in expected.items():
        fit = _fit(sample)
        assert fit["policy"]["weight"] == round(weight, 4)
        assert fit["policy"]["settled_unique_forecasts"] == sample
        shifts.append(fit["global"])
    assert shifts == sorted(shifts)


def test_null_version_rows_remain_historical_prior_and_readiness_is_reported():
    fit = _fit(5)
    assert fit["historical"]["n"] == 100
    assert fit["current_policy"]["n"] == 5
    assert fit["policy"]["readiness"] == "VERY_THIN"
    group = fit["groups"]["goals_over_1_5"]
    assert group["historical_sample"] == 100
    assert group["current_policy_sample"] == 5
    assert group["current_policy_weight"] == round(5 / 35, 4)
