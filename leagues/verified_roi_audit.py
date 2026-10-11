"""Read-only official ROI audit. Shadow evidence, never an automatic betting rule.

Do not count the same fixture/market repeatedly when it appears in more than
one official product. Pending/void outcomes and estimated prices cannot be
treated as verified wins, losses or realized bookmaker returns. Settled
published prices are *hypothetical one-unit* returns, not user wager records.
"""
from __future__ import annotations

from collections import defaultdict
import math

from leagues.forecast_observations import forecast_identity

MIN_EVIDENCE_N = 100


def _price(leg):
    try:
        price = float(leg.get("odds"))
        if price <= 1.0 or not math.isfinite(price):
            return None
        # A synthetic/model-implied price must never enter measured ROI.
        if leg.get("odds_are_real") is not True:
            return None
        return price
    except (ValueError, TypeError, OverflowError):
        return None


def _probability(leg):
    for field in ("selection_probability", "confidence"):
        try:
            p = float(leg.get(field))
            if math.isfinite(p) and 0 < p < 1:
                return p
        except (ValueError, TypeError, OverflowError):
            pass
    return None


def _summary(observations):
    n = len(observations)
    wins = sum(item["won"] for item in observations)
    profit = sum(item["price"] - 1 if item["won"] else -1
                 for item in observations)
    expected = [item["probability"] for item in observations
                if item["probability"] is not None]
    return {
        "settled": n,
        "wins": wins,
        "losses": n - wins,
        "hit_rate": round(wins / n, 4) if n else None,
        "flat_one_unit_net": round(profit, 4),
        "flat_one_unit_roi": round(profit / n, 4) if n else None,
        "mean_published_probability": (
            round(sum(expected) / len(expected), 4) if expected else None
        ),
        "probability_sample": len(expected),
        "confidence_bias": (
            round(sum(expected) / len(expected) -
                  sum(i["won"] for i in observations
                      if i["probability"] is not None) / len(expected), 4)
            if expected else None
        ),
        "evidence_state": (
            "INSUFFICIENT" if n < MIN_EVIDENCE_N else "REVIEW_READY"
        ),
    }


def audited_market_roi(slips: list[dict]) -> dict:
    """Summarize exact-price settled outcomes with de-duplicated leg identity.

    Earliest archived date/time wins if the same selection was in Banker and
    Over1.5 singles; later mentions are not extra independent trials.
    For published *slips*, each original ticket is still counted independently
    for product-level hypothetical returns (except singles, which are legs).
    """
    canonical = {}
    excluded = defaultdict(int)
    for slip in sorted(slips, key=lambda r: (
        str(r.get("created_at") or r.get("date") or ""),
        str(r.get("id") or ""),
    )):
        for leg in slip.get("picks") or []:
            result = str(leg.get("status") or "").lower()
            if result not in {"won", "lost"}:
                excluded["unsettled_or_void"] += 1
                continue
            price = _price(leg)
            if price is None:
                excluded["unverified_or_missing_price"] += 1
                continue
            identity = forecast_identity(leg, str(slip.get("date") or ""))
            if identity in canonical:
                excluded["duplicate_fixture_market"] += 1
                continue
            canonical[identity] = {
                "market": str(leg.get("market_key") or leg.get("market") or "unknown"),
                "policy_version": str(slip.get("policy_version") or "legacy"),
                "won": int(result == "won"),
                "price": price,
                "probability": _probability(leg),
            }

    groups = defaultdict(list)
    for item in canonical.values():
        groups[item["market"]].append(item)

    products = defaultdict(list)
    for slip in slips:
        product = str(slip.get("category") or "unknown")
        if product == "over_1_5" or slip.get("presentation") == "singles":
            # Singles are distinct bets, not an imaginary 10-leg accumulator.
            seen = set()
            for leg in slip.get("picks") or []:
                identity = forecast_identity(leg, str(slip.get("date") or ""))
                if identity in seen:
                    continue
                seen.add(identity)
                price = _price(leg)
                status = leg.get("status")
                if status in {"won", "lost"} and price is not None:
                    products[product].append({
                        "won": int(status == "won"), "price": price,
                        "probability": _probability(leg),
                    })
            continue
        status = str(slip.get("status") or "").lower()
        try:
            price = float(slip.get("total_odds") or 0)
        except (ValueError, TypeError, OverflowError):
            price = 0
        if status not in {"won", "lost"} or not math.isfinite(price) or price <= 1:
            continue
        # Archived product odds require price provenance for every leg.
        # A mismatch cannot be called a verified accumulator return.
        legs = slip.get("picks") or []
        verified = [_price(leg) for leg in legs]
        if not legs or any(v is None for v in verified):
            excluded["product_unverified_accumulator_price"] += 1
            continue
        combined = math.prod(verified)
        if not math.isclose(combined, price, rel_tol=0.01, abs_tol=0.02):
            excluded["product_inconsistent_accumulator_price"] += 1
            continue
        products[product].append({
            "won": int(status == "won"),
            "price": price,
            "probability": None,
        })

    return {
        "status": "success",
        "mode": "SHADOW_EVIDENCE_ONLY",
        "official_publications_unchanged": True,
        "actual_wager_profit_claim": False,
        "price_basis": "original archived real price; NOT CLV or payout receipt",
        "minimum_market_evidence": MIN_EVIDENCE_N,
        "distinct_settled_fixture_markets": len(canonical),
        "excluded": dict(sorted(excluded.items())),
        "markets": {k: _summary(v) for k, v in sorted(groups.items())},
        "products": {k: _summary(v) for k, v in sorted(products.items())},
    }


def production_roi_report(days: int = 90) -> dict:
    """Read published immutable history; never modify data or product rules."""
    from leagues.picks_db import get_history
    bounded_days = max(1, min(365, int(days)))
    result = audited_market_roi(get_history(limit_days=bounded_days))
    result["lookback_days"] = bounded_days
    return result
