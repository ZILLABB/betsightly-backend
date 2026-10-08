"""Read-only staging diagnostics: where each football market loses eligibility.

This audit uses the existing evaluated 7-day board; NO provider refetch,
publication, settlement, booking, model promotion, or threshold changes.
Counts are selection-level and can overlap across fixtures and reasons.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from scripts.prepare_staging_board_once import preflight

PRODUCT = "5_odds"


def _by_date(picks: list[dict], target_date: str) -> list[dict]:
    from leagues.engine import kickoff_wat_date
    return [
        p for p in picks
        if kickoff_wat_date((p.get("_fixture") or {}).get("commence_time"))
        == target_date
    ]


def inspect_day(target_date: str, picks: list[dict]) -> dict:
    from leagues.fixture_ranker import canonical_fixture_recommendations
    from leagues.market_registry import MARKETS
    from leagues.publication_policy import evaluate_leg

    # The ranker applies market activation and trust gates, and preserves all
    # independently eligible market alternatives for *diagnostics*.
    ranked = canonical_fixture_recommendations(picks, include_all_eligible=True)
    rank_counts = Counter(str(p.get("market") or "unknown") for p in ranked)

    grouped: dict[str, list[dict]] = defaultdict(list)
    for p in picks:
        grouped[str(p.get("market") or "unknown")].append(p)

    approvals: Counter[str] = Counter()
    rejections: dict[str, Counter[str]] = defaultdict(Counter)
    qualified_ids: dict[str, set[str]] = defaultdict(set)
    for p in ranked:
        market = str(p.get("market") or "unknown")
        decision = evaluate_leg(p, PRODUCT)
        if decision["allowed"]:
            approvals[market] += 1
            if p.get("match_id"):
                qualified_ids[market].add(str(p["match_id"]))
        else:
            rejections[market].update(decision["reasons"])

    per_market = {}
    for market, candidates in sorted(grouped.items()):
        spec = MARKETS.get(market)
        raw_count = len(candidates)
        passed_ranker = rank_counts.get(market, 0)
        per_market[market] = {
            "registry_activation": spec.activation if spec else "UNKNOWN",
            "public_policy": spec.public_policy if spec else "UNKNOWN",
            "raw_candidates": raw_count,
            "real_price_candidates": sum(bool(p.get("odds_are_real")) for p in candidates),
            "bookable_candidates": sum(bool(p.get("bookable")) for p in candidates),
            "safe_evidence_candidates": sum(bool(p.get("safe_tier_eligible")) for p in candidates),
            "market_floor_candidates": sum(bool(p.get("market_floor_eligible", True)) for p in candidates),
            "retained_after_market_trust": passed_ranker,
            "lost_before_official_policy": raw_count - passed_ranker,
            "quality_qualified_selections": approvals[market],
            "quality_qualified_fixtures": len(qualified_ids[market]),
            "official_rejection_reasons": dict(sorted(rejections[market].items())),
        }

    return {
        "fixture_date_wat": target_date,
        "raw_candidates": len(picks),
        "raw_fixtures": len({str(p.get("match_id")) for p in picks if p.get("match_id")}),
        "post_market_trust_candidates": len(ranked),
        "post_official_policy_qualified": sum(approvals.values()),
        "markets": per_market,
    }


def diagnose() -> dict:
    database = preflight()
    from leagues.engine import prepared_board

    picks, fixtures, board = prepared_board(days_ahead=7)
    if not board.get("ready") or board.get("stale"):
        raise RuntimeError(
            "Read-only market diagnosis refused: staging board not fresh"
        )
    if not picks or not fixtures:
        raise RuntimeError("Staging board has no usable evaluated predictions")
    first_day = (datetime.now(timezone.utc) + timedelta(hours=1)).date()
    days = [
        inspect_day(date, _by_date(picks, date))
        for date in ((first_day + timedelta(days=offset)).isoformat()
                     for offset in range(1, 7))
    ]
    totals: dict[str, Counter[str]] = defaultdict(Counter)
    reasons: dict[str, Counter[str]] = defaultdict(Counter)
    for day in days:
        for market, metrics in day["markets"].items():
            for key in (
                "raw_candidates", "real_price_candidates",
                "bookable_candidates", "safe_evidence_candidates",
                "market_floor_candidates", "retained_after_market_trust",
                "lost_before_official_policy", "quality_qualified_selections",
            ):
                totals[market][key] += metrics[key]
            reasons[market].update(metrics["official_rejection_reasons"])
    return {
        "mode": "READ_ONLY_STAGING_MARKET_REJECTION_DIAGNOSIS",
        "database": database,
        "snapshot_id": board.get("board_snapshot_id"),
        "board_age_seconds": board.get("age_seconds"),
        "board_degraded": board.get("degraded"),
        "model_fixture_count": len(fixtures),
        "model_candidate_count": len(picks),
        "total_by_market": {
            market: {**dict(counter),
                     "official_rejection_reasons": dict(sorted(reasons[market].items()))}
            for market, counter in sorted(totals.items())
        },
        "days": days,
        "quality_thresholds_changed": False,
        "official_publication": False,
        "booking_codes_created": False,
        "source_refresh_triggered": False,
    }


if __name__ == "__main__":
    print(json.dumps(diagnose(), sort_keys=True))
