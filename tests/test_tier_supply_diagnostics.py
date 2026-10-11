"""Provable upper bounds are diagnostics only: never publish unsafe odds."""
from leagues.tier_supply_diagnostics import optimistic_ceiling, tier_supply_diagnostics


def _pick(match_id, odds, group="goals", market="over_1_5"):
    return {"match_id": str(match_id), "odds": odds, "market_group": group,
            "market": market, "bookable": True, "odds_are_real": True}


def test_twenty_three_all_goals_proves_both_tiers_impossible_at_cap_three():
    picks = [_pick(i, 1.29 + (i % 17) * 0.01) for i in range(23)]
    diagnostic = tier_supply_diagnostics(picks)
    assert diagnostic["qualified_selections"] == 23
    assert diagnostic["qualified_fixtures"] == 23
    assert diagnostic["by_market_group"] == {"goals": 23}
    for tier in ("5_odds", "10_odds"):
        record = diagnostic["products"][tier]
        assert record["policy_cap_proves_unreachable"]
        assert record["reason_code"] == "MARKET_GROUP_CAP_UPPER_BOUND"
        assert record["optimistic_with_policy_cap"] < record["target"]
    assert diagnostic["products"]["10_odds"]["relaxed_caps_shadow_only"]["12"] > 10


def test_bounds_are_optimistic_not_an_approval_to_publish():
    picks = [_pick(i, 1.5, "goals") for i in range(10)]
    diagnostic = tier_supply_diagnostics(picks)
    assert diagnostic["products"]["5_odds"]["reason_code"] == (
        "MARKET_GROUP_CAP_UPPER_BOUND")
    assert not diagnostic["products"]["10_odds"][
        "relaxed_caps_shadow_only"].get("3", 0) >= 10
    assert diagnostic["shadow_only"] is True


def test_distinct_market_groups_and_reservations():
    picks = ([_pick(i, 1.50, "goals") for i in range(5)]
             + [_pick(i + 5, 1.60, "double_chance", "home_or_draw")
                for i in range(5)])
    baseline = tier_supply_diagnostics(picks)
    assert baseline["products"]["5_odds"][
        "policy_cap_proves_unreachable"] is False
    reserved = tier_supply_diagnostics(
        picks, used={"banker": picks[:5], "2_odds": picks[5:9]})
    assert reserved["remaining_qualified_fixtures"] == 1
    assert reserved["products"]["5_odds"][
        "reservation_cap_proves_unreachable"] is True
    assert reserved["products"]["5_odds"][
        "reason_code"] == "RESERVED_EXPOSURE_UPPER_BOUND"


def test_duplicate_fixture_markets_not_counted_as_distinct_fixtures():
    picks = [_pick("same", 1.45, "goals"),
             _pick("same", 1.35, "double_chance", "home_or_draw")]
    diag = tier_supply_diagnostics(picks)
    assert diag["qualified_selections"] == 2
    assert diag["qualified_fixtures"] == 1
    # Upper bound may overstate attainable odds due to repeated fixture,
    # but must never understate them.
    assert optimistic_ceiling(picks)["maximum_optimistic_odds"] >= 1.45


def test_no_estimated_or_unbookable_prices_allowed_in_bounds():
    picks = [_pick(1, 1.40)]
    picks += [{**_pick(2, 1.99), "odds_are_real": False},
              {**_pick(3, 2.99), "bookable": False}]
    assert optimistic_ceiling(picks)["maximum_optimistic_odds"] == 1.4
    assert optimistic_ceiling([], market_cap=3)["maximum_optimistic_odds"] == 0.0


def test_supplied_policy_cap_is_never_overwritten_by_shadow():
    picks = [_pick(i, 1.45) for i in range(9)]
    d = tier_supply_diagnostics(picks, market_cap=2)
    assert d["products"]["10_odds"]["policy_market_cap"] == 2
    assert d["products"]["10_odds"]["policy_cap_proves_unreachable"] is True
    assert d["products"]["10_odds"]["relaxed_caps_shadow_only"]["12"] > 10
