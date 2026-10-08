"""Counterfactual never turns unproven outcomes into real official recommendations."""
import pytest

from scripts import audit_staging_evidence_gate_counterfactual as audit


def _pick(market, match_id, reasons):
    return {"market": market, "match_id": match_id, "_test_reasons": reasons}


def test_counts_evidence_only_separately_from_other_rejections(monkeypatch):
    candidates = [
        _pick("over_1_5", "a", []),
        _pick("home_or_draw", "b", ["INSUFFICIENT_SETTLED_EVIDENCE"]),
        _pick("home_or_draw", "c", [
            "INSUFFICIENT_SETTLED_EVIDENCE", "ESTIMATED_PRICE"
        ]),
        _pick("btts_yes", "d", ["INSUFFICIENT_SETTLED_EVIDENCE"]),
    ]
    original = [dict(p) for p in candidates]

    monkeypatch.setattr(
        audit, "canonical_fixture_recommendations",
        lambda rows, *, include_all_eligible: [
            r for r in rows if r["market"] != "btts_yes"
        ],
    )
    monkeypatch.setattr(
        audit, "evaluate_leg",
        lambda pick, product: {
            "allowed": not pick["_test_reasons"],
            "reasons": list(pick["_test_reasons"]),
        },
    )

    result = audit.inspect_market_picks(candidates, "5_odds")
    assert result["over_1_5"]["official_qualified_unique_fixtures"] == 1
    assert result["home_or_draw"]["evidence_only_blocked_unique_fixtures"] == 1
    assert result["home_or_draw"]["other_rules_blocked_unique_fixtures"] == 1
    assert result["home_or_draw"]["counterfactual_without_evidence_gate_unique_fixtures"] == 1
    assert result["home_or_draw"]["official_qualified_unique_fixtures"] == 0
    assert "btts_yes" not in result
    assert candidates == original


def test_over15_product_remains_single_market_only(monkeypatch):
    monkeypatch.setattr(
        audit, "canonical_fixture_recommendations",
        lambda rows, *, include_all_eligible: rows,
    )
    monkeypatch.setattr(
        audit, "evaluate_leg",
        lambda pick, product: {"reasons": pick["_test_reasons"]},
    )
    result = audit.inspect_market_picks(
        [_pick("over_1_5", "a", []), _pick("home_or_draw", "b", [])],
        "over_1_5",
    )
    assert set(result) == {"over_1_5"}


def test_unknown_product_refused():
    with pytest.raises(ValueError, match="Unknown official product"):
        audit.inspect_market_picks([], "all_markets")


def test_live_snapshot_must_be_fresh(monkeypatch):
    from leagues import engine

    monkeypatch.setattr(
        audit, "preflight", lambda: "betsightly_db_staging"
    )
    monkeypatch.setattr(
        engine, "prepared_board", lambda days_ahead: (
            [], [], {"ready": True, "stale": True}
        ),
    )
    with pytest.raises(RuntimeError, match="must be fresh"):
        audit.audit()
