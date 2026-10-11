"""Read-only, provable daily-tier feasibility and counterfactual diagnostics.

No selector is changed by this module. A relaxed-cap multiplier is an
optimistic *upper bound*, not evidence the slip would win, satisfy the EV
contract, or survive SportyBet readback. This distinction prevents empty
tiers being blamed on missing fixtures when a market-exposure cap alone
makes them mathematically impossible.
"""
from __future__ import annotations

from collections import Counter
from math import prod

DEFAULT_CAP = 3


def optimistic_ceiling(picks: list[dict], *, max_legs: int = 20,
                       market_cap: int = DEFAULT_CAP) -> dict:
    """Upper bound on obtainable odds using independently approved legs.

    Drops fixture uniqueness and cross-tier exposure constraints on purpose:
    that can only increase this bound. If even this bound is below target,
    no valid real-world ticket can attain the target under these caps.
    """
    by_group: dict[str, list[float]] = {}
    for p in picks:
        try:
            odds = float(p.get("odds") or 0)
        except (ValueError, TypeError):
            continue
        if odds <= 1 or not p.get("bookable") or not p.get("odds_are_real"):
            continue
        group = str(p.get("market_group") or p.get("market") or "unknown")
        by_group.setdefault(group, []).append(odds)
    ranked = sorted(
        (price for prices in by_group.values()
         for price in sorted(prices, reverse=True)[:max(0, market_cap)]),
        reverse=True,
    )[:max(0, max_legs)]
    cap = prod(ranked) if ranked else 0.0
    return {"maximum_optimistic_odds": round(cap, 3),
            "usable_leg_limit": len(ranked),
            "groups": dict(sorted((k, len(v)) for k, v in by_group.items())),
            "market_cap": market_cap, "max_legs": max_legs}


def tier_supply_diagnostics(
    qualified: list[dict],
    *,
    used: dict[str, list[dict]] | None = None,
    market_cap: int = DEFAULT_CAP,
) -> dict:
    """Explain cap-bound infeasibility without changing published choices."""
    used = used or {}
    used_ids = {
        str(p.get("match_id") or "")
        for legs in used.values() for p in legs if p.get("match_id")
    }
    remaining = [
        p for p in qualified
        if str(p.get("match_id") or "") not in used_ids
    ]
    unique = {str(p.get("match_id")) for p in qualified if p.get("match_id")}
    remain_unique = {str(p.get("match_id")) for p in remaining if p.get("match_id")}
    markets = Counter(str(p.get("market") or "unknown") for p in qualified)
    groups = Counter(str(p.get("market_group") or "unknown") for p in qualified)

    products = {}
    for tier, target in (("5_odds", 5.0), ("10_odds", 10.0)):
        baseline = optimistic_ceiling(
            qualified, market_cap=market_cap)
        unreserved = optimistic_ceiling(
            remaining, market_cap=market_cap)
        alternative = {
            str(cap): optimistic_ceiling(
                qualified, market_cap=cap)["maximum_optimistic_odds"]
            for cap in (3, 6, 8, 12)
        }
        blocked_by_cap = baseline["maximum_optimistic_odds"] < target
        after_reservations = unreserved["maximum_optimistic_odds"] < target
        products[tier] = {
            "target": target,
            "policy_market_cap": market_cap,
            "optimistic_with_policy_cap": baseline["maximum_optimistic_odds"],
            "optimistic_after_existing_reservations":
                unreserved["maximum_optimistic_odds"],
            "policy_cap_proves_unreachable": blocked_by_cap,
            "reservation_cap_proves_unreachable": after_reservations,
            "relaxed_caps_shadow_only": alternative,
            "reason_code": (
                "MARKET_GROUP_CAP_UPPER_BOUND" if blocked_by_cap
                else "RESERVED_EXPOSURE_UPPER_BOUND" if after_reservations
                else "REQUIRES_FULL_SELECTION_AND_VALUE_CHECK"
            ),
        }
    return {
        "diagnostic_version": "tier_supply_bounds_v1",
        "shadow_only": True,
        "qualified_selections": len(qualified),
        "qualified_fixtures": len(unique),
        "reserved_fixtures": len(used_ids),
        "remaining_qualified_fixtures": len(remain_unique),
        "by_market": dict(sorted(markets.items())),
        "by_market_group": dict(sorted(groups.items())),
        "products": products,
    }
