"""Read-only EV attribution catches price weakness vs excess shrinkage."""
import pytest

from scripts import audit_staging_market_value as audit


def pick(market, prob, odds, lower, fixture):
    return {
        "market": market, "match_id": fixture, "confidence": prob,
        "odds": odds, "odds_are_real": True, "bookable": True,
        "trust": {"lower_reliability_bound": lower, "evidence_strength": 0},
    }


def test_value_diagnostics_split_raw_unprofitable_from_conservative(monkeypatch):
    from leagues import fixture_ranker

    monkeypatch.setattr(
        fixture_ranker, "canonical_fixture_recommendations",
        lambda rows, *, include_all_eligible: list(rows),
    )
    picks = [
        pick("over_1_5", .80, 1.50, .60, "a"),  # raw positive, conservative negative
        pick("over_1_5", .60, 1.20, .60, "b"),  # raw and conservative negative
        pick("under_4_5", .75, 1.50, .75, "c"), # profitable counterfactual only
    ]
    report = audit.value_diagnostics(picks)
    goals = report["over_1_5"]
    assert goals["trusted_candidates"] == 2
    assert goals["valid_exact_quote"] == 2
    assert goals["negative_model_value"] == 2
    assert goals["raw_break_even_but_conservative_negative"] == 1
    assert goals["raw_and_conservative_negative"] == 1
    assert goals["median_verified_price"] == pytest.approx(1.35)
    assert report["under_4_5"]["negative_model_value"] == 0


def test_never_claims_estimated_price_as_verified(monkeypatch):
    from leagues import fixture_ranker
    monkeypatch.setattr(
        fixture_ranker, "canonical_fixture_recommendations",
        lambda rows, *, include_all_eligible: list(rows),
    )
    item = pick("home_or_draw", .80, 1.5, .60, "x")
    item["odds_are_real"] = False
    result = audit.value_diagnostics([item])["home_or_draw"]
    assert result["unverified_bookable_quote"] == 1
    assert "valid_exact_quote" not in result
    assert result["median_verified_price"] is None


def test_read_only_audit_rejects_stale_snapshot(monkeypatch):
    from leagues import engine

    monkeypatch.setattr(audit, "preflight", lambda: "betsightly_db_staging")
    monkeypatch.setattr(
        engine, "prepared_board",
        lambda days_ahead: ([], [], {"ready": True, "stale": True}),
    )
    with pytest.raises(RuntimeError, match="stale board"):
        audit.audit()
