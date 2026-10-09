"""Staging report must not count the same market/fixture six times."""
from datetime import datetime, timedelta, timezone

from scripts.preview_staging_official_card import (
    TIERS, diagnose_supply, disjoint_one_leg_capacity,
)


def _pick(fid, market="home_win"):
    return {"match_id": fid, "market": market}


def test_two_shared_fixtures_are_not_six_independent_tier_opportunities():
    choices = {
        product: [_pick("a"), _pick("b")] for product in TIERS
    }
    choices["banker"] = []
    report = disjoint_one_leg_capacity(choices)
    assert report["distinct_approved_fixture_union"] == 2
    assert report["max_products_with_one_unique_fixture_each"] == 2
    assert report["all_six_one_leg_capacity_possible"] is False
    assert report["products_with_zero_approved_fixtures"] == ["banker"]
    assert len(set(report["one_leg_distinct_assignments"].values())) == 2
    assert report["complete_slip_targets_verified"] is False


def test_bipartite_matching_avoids_greedy_fixture_blockage():
    choices = {product: [] for product in TIERS}
    choices["banker"] = [_pick("only-banker")]
    choices["2_odds"] = [_pick("only-banker"), _pick("other")]
    report = disjoint_one_leg_capacity(choices)
    assert report["max_products_with_one_unique_fixture_each"] == 2
    assert report["one_leg_distinct_assignments"]["banker"] == "only-banker"
    assert report["one_leg_distinct_assignments"]["2_odds"] == "other"


def test_six_unique_fixtures_suffice_for_one_leg_only_not_finished_slips():
    choices = {
        product: [_pick(f"unique-{product}")] for product in TIERS
    }
    report = disjoint_one_leg_capacity(choices)
    assert report["max_products_with_one_unique_fixture_each"] == 6
    assert report["all_six_one_leg_capacity_possible"] is True
    assert report["complete_slip_targets_verified"] is False


def test_over15_diagnostic_excludes_unrelated_valid_market(monkeypatch):
    from leagues import engine, fixture_ranker, publication_policy
    date_now = datetime.now(timezone(timedelta(hours=1)))
    tomorrow = (date_now + timedelta(days=1)).replace(
        hour=17, minute=0, second=0, microsecond=0,
    )
    day = tomorrow.date().isoformat()
    picks = [
        {"match_id": "win", "market": "home_win",
         "_fixture": {"commence_time": tomorrow.isoformat()}},
        {"match_id": "goals", "market": "over_1_5",
         "_fixture": {"commence_time": tomorrow.isoformat()}},
    ]
    monkeypatch.setattr(
        fixture_ranker, "canonical_fixture_recommendations",
        lambda rows, **kwargs: rows,
    )
    monkeypatch.setattr(
        publication_policy, "filter_official_candidates",
        lambda rows, product: (list(rows), []),
    )
    monkeypatch.setattr(
        publication_policy, "rejection_summary",
        lambda rows: {},
    )
    report = diagnose_supply(picks, day, date_now.astimezone(timezone.utc))
    assert report["products"]["over_1_5"]["approved_legs"] == 1
    assert report["products"]["over_1_5"]["evaluated_market_legs"] == 1
    assert report["products"]["5_odds"]["approved_legs"] == 2
    assert report["products"]["rollover"]["approved_legs"] == 2
    assert report["cross_tier_feasibility"]["distinct_approved_fixture_union"] == 2
