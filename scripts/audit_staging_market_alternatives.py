"""Read-only staging audit: ranked two markets vs all active qualified markets.

This measures whether the Daily selector is discarding good alternative
outcomes too early. It does NOT loosen quality/evidence gates, build slips,
fetch providers, publish cards, book codes, settle or send notifications.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from scripts.prepare_staging_board_once import preflight

PRODUCTS = ("banker", "2_odds", "5_odds", "10_odds", "over_1_5")


def _date_picks(picks: list[dict], day: str) -> list[dict]:
    from leagues.engine import kickoff_wat_date
    return [
        pick for pick in picks
        if kickoff_wat_date((pick.get("_fixture") or {}).get("commence_time")) == day
    ]


def _unique_ids(picks: list[dict]) -> set[str]:
    return {str(p.get("match_id")) for p in picks if p.get("match_id")}


def _mix(picks: list[dict]) -> dict[str, int]:
    return dict(sorted(Counter(str(p.get("market") or "unknown") for p in picks).items()))


def _report_day(day: str, picks: list[dict]) -> dict:
    from leagues.fixture_ranker import canonical_fixture_recommendations
    from leagues.publication_policy import filter_official_candidates

    baseline = canonical_fixture_recommendations(picks)
    # Same trust/market-activation rules; only bypass top-two Pareto pruning.
    alternatives = canonical_fixture_recommendations(
        picks, include_all_eligible=True
    )

    products = {}
    for product in PRODUCTS:
        baseline_pool = baseline
        full_pool = alternatives
        if product == "over_1_5":
            baseline_pool = [p for p in baseline if p.get("market") == "over_1_5"]
            full_pool = [p for p in alternatives if p.get("market") == "over_1_5"]

        baseline_allowed, baseline_rejected = filter_official_candidates(
            baseline_pool, product
        )
        all_allowed, all_rejected = filter_official_candidates(full_pool, product)
        baseline_ids = _unique_ids(baseline_allowed)
        all_ids = _unique_ids(all_allowed)
        rescued_ids = all_ids - baseline_ids
        products[product] = {
            "baseline_qualified_unique": len(baseline_ids),
            "all_active_markets_qualified_unique": len(all_ids),
            "additional_qualified_fixtures": len(rescued_ids),
            "additional_qualified_market_mix": _mix(
                [p for p in all_allowed if str(p.get("match_id")) in rescued_ids]
            ),
            "baseline_rejected_selections": len(baseline_rejected),
            "all_market_rejected_selections": len(all_rejected),
            "all_active_qualified_market_mix": _mix(all_allowed),
        }

    return {
        "fixture_date_wat": day,
        "raw_fixtures": len(_unique_ids(picks)),
        "raw_market_candidates": len(picks),
        "raw_market_mix": _mix(picks),
        "ranked_two_candidate_count": len(baseline),
        "all_active_candidate_count": len(alternatives),
        "products": products,
    }


def audit() -> dict:
    database = preflight()
    from leagues.engine import prepared_board
    from leagues.market_registry import MARKETS

    picks, fixtures, board = prepared_board(days_ahead=7)
    if not board.get("ready") or board.get("stale"):
        raise RuntimeError("Refusing alternatives audit: staging board is not fresh")

    first = (datetime.now(timezone.utc) + timedelta(hours=1)).date()
    days = [
        _report_day((first + timedelta(days=offset)).isoformat(),
                    _date_picks(picks, (first + timedelta(days=offset)).isoformat()))
        for offset in range(1, 7)
    ]

    return {
        "mode": "READ_ONLY_STAGING_MARKET_ALTERNATIVES_AUDIT",
        "database": database,
        "board_snapshot_id": board.get("board_snapshot_id"),
        "board_degraded": board.get("degraded"),
        "model_fixture_count": len(fixtures),
        "model_candidate_count": len(picks),
        "total_eligible_by_product": {
            product: {
                "baseline_qualified_unique_sum": sum(
                    d["products"][product]["baseline_qualified_unique"] for d in days
                ),
                "all_markets_qualified_unique_sum": sum(
                    d["products"][product]["all_active_markets_qualified_unique"] for d in days
                ),
                "additional_qualified_fixture_sum": sum(
                    d["products"][product]["additional_qualified_fixtures"] for d in days
                ),
            }
            for product in PRODUCTS
        },
        "restricted_markets": sorted(
            key for key, spec in MARKETS.items() if spec.activation != "ACTIVE"
        ),
        "missing_requested_markets": [
            key for key in ("over_0_5",) if key not in MARKETS
        ],
        "days": days,
        "official_publication": False,
        "booking_codes_created": False,
        "quality_thresholds_changed": False,
    }


if __name__ == "__main__":
    print(json.dumps(audit(), sort_keys=True))
