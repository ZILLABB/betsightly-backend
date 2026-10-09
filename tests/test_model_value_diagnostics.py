"""Model-value diagnostics must not elevate selections into official tickets."""
from leagues.model_value_diagnostics import summarize_value


def _candidate(mid, market="over_1_5", confidence=.8, odds=1.4, **extra):
    return {
        "match_id": mid, "market": market, "confidence": confidence,
        "odds": odds, "odds_are_real": True, "bookable": True, **extra,
    }


def test_price_negative_is_distinct_from_evidence_shrinkage():
    picks = [
        _candidate("good"),
        _candidate("book_short", odds=1.1),
        _candidate(
            "reliability_shrink", odds=1.4,
            lower_reliability_bound=.60, evidence_strength=0,
        ),
        _candidate("unpriced", odds=1.5, odds_are_real=False),
    ]
    report = summarize_value(picks)
    counts = report["counts"]
    assert counts["candidates"] == 4
    assert counts["real_bookable"] == 3
    assert counts["raw_return_ge_one"] == 2
    assert counts["conservative_return_ge_one"] == 1
    assert counts["negative_before_and_after_evidence"] == 1
    assert counts["positive_to_negative_after_evidence"] == 1
    assert counts["without_exact_real_price"] == 1
    assert report["production_unchanged"] is True


def test_stored_risk_value_mismatch_is_reported_not_used():
    report = summarize_value([
        _candidate("stale", risk_adjusted_return=1.5),
    ])
    assert report["counts"]["stored_return_mismatches"] == 1
    row = report["stored_return_mismatch_samples"][0]
    assert row["stored"] == 1.5
    assert row["recomputed"] == 1.12


def test_draw_no_bet_uses_push_aware_price_equation():
    p = _candidate("dnb", market="dnb_home", odds=1.5, confidence=.72)
    p["_model"] = {"probabilities": {"draw": .35}}
    report = summarize_value([p])
    assert report["counts"]["raw_return_ge_one"] == 1
    assert report["counts"]["conservative_return_ge_one"] == 1
    assert "stored_return_mismatches" not in report["counts"]


def test_diagnostics_do_not_mutate_inputs():
    pick = _candidate("immutable")
    before = dict(pick)
    summarize_value([pick])
    assert pick == before
