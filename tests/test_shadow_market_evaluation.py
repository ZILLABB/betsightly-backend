"""Chronological shadow eval must fail closed on leakage and thin evidence."""
import pytest
from leagues.shadow_market_evaluation import evaluate_paired


def row(fid="a", market="over_1_5", y=1, champion=.6, challenger=.8):
    return {
        "fixture_id": fid, "market": market,
        "observed_at": "2026-10-01T09:00:00Z",
        "kickoff": "2026-10-02T12:00:00Z",
        "settled_at": "2026-10-02T14:00:00Z",
        "outcome": y, "champion_probability": champion,
        "challenger_probability": challenger,
    }


def test_paired_brier_and_shadow_gate():
    r = evaluate_paired([row()], evaluation_start="2026-10-01T00:00:00Z")
    m = r["markets"]["over_1_5"]
    assert m["settled"] == 1
    assert m["champion_brier"] == .16
    assert m["challenger_brier"] == .04
    assert m["evidence"] == "INSUFFICIENT"
    assert r["automatic_model_promotion"] is False


def test_prior_dates_do_not_enter_holdout():
    result = evaluate_paired([row()], evaluation_start="2026-10-03T00:00:00Z")
    assert result["paired_market_count"] == 0
    assert result["excluded_pre_holdout"] == 1


@pytest.mark.parametrize("field,value", [
    ("observed_at", "2026-10-02T12:00:00Z"),
    ("settled_at", "2026-10-02T11:00:00Z"),
    ("outcome", 2),
    ("champion_probability", 1.2),
    ("challenger_probability", float("nan")),
])
def test_reject_invalid_data(field, value):
    r = row()
    r[field] = value
    with pytest.raises(ValueError):
        evaluate_paired([r], evaluation_start="2026-10-01T00:00:00Z")


def test_duplicate_fixture_market_is_not_double_counted():
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_paired([row(), row()], evaluation_start="2026-10-01T00:00:00Z")


def test_distinct_market_probabilities_not_cross_counted():
    r = evaluate_paired([row(market="over_1_5"), row(market="btts_yes")],
                        evaluation_start="2026-10-01T00:00:00Z")
    assert r["paired_market_count"] == 2
