"""Run BetSightly's four-part OFFLINE qualification audit on verified exports.

Usage:
  python -m scripts.audit_qualification_overhaul \
    --snapshots snapshots.json --finals verified_regulation_finals.json \
    --portfolio independent_tiers.json --review-queue review_queue.json \
    --output qualification_shadow_report.json

An empty or incomplete input reports missing evidence, never fabricated metrics.
No network requests, model training, database updates or bookmaker bookings.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from leagues.qualification_overhaul_shadow import (
    compare_market_penalties,
    independent_tier_exposure,
    score_complete_forecast_pool,
    settlement_queue_audit,
)


def _read(path: str | None, *, default):
    if not path:
        return default
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    return value


def run(snapshots: list[dict], finals: list[dict],
        portfolio: dict | None = None, queue: dict | None = None) -> dict:
    scored = score_complete_forecast_pool(snapshots, finals)
    observations = scored.pop("observations")
    cup_rows = [r for r in observations
                if r.get("competition_type") == "DOMESTIC_CUP"]
    return {
        "report_version": "qualification_shadow_v1",
        "mode": "RESEARCH_ONLY_NO_PRODUCTION_WRITE",
        "part_1_full_pool_evidence_and_settlement": scored,
        "part_2_conservative_value_calibration": compare_market_penalties(observations),
        "part_3_six_product_independent_exposure": independent_tier_exposure(
            portfolio or {}),
        "part_4_cup_verified_observations": {
            "settled_cup_market_observations": len(cup_rows),
            "unique_cup_fixtures": len({r["fixture_id"] for r in cup_rows}),
            "by_competition": {
                league: {
                    "settled_market_observations": sum(
                        r["league_slug"] == league for r in cup_rows),
                    "unique_fixtures": len({
                        r["fixture_id"] for r in cup_rows
                        if r["league_slug"] == league}),
                }
                for league in sorted({r["league_slug"] for r in cup_rows})
            },
            "nonregulation_or_unverified_finals_never_accepted": True,
            "fixture_identity_or_bookmaker_coverage_not_inferred": True,
        },
        "manual_settlement_backlog": settlement_queue_audit(queue or {}),
        "promotion_status": "NOT_AUTHORISED",
        "production_policy_changed": False,
        "note": "The settlement input must be independently source-verified "
                "before running this report. Sample backtests cannot approve "
                "bookings; every official ticket still needs real SportyBet "
                "prices and exact share-code readback.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", required=True)
    parser.add_argument("--finals", required=True)
    parser.add_argument("--portfolio")
    parser.add_argument("--review-queue")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    snapshots = _read(args.snapshots, default=[])
    finals = _read(args.finals, default=[])
    portfolio = _read(args.portfolio, default={})
    queue = _read(args.review_queue, default={})
    if not isinstance(snapshots, list) or not isinstance(finals, list):
        parser.error("snapshots and finals must contain JSON arrays")
    if not isinstance(portfolio, dict) or not isinstance(queue, dict):
        parser.error("portfolio and review queue must contain JSON objects")
    report = run(snapshots, finals, portfolio, queue)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True),
                   encoding="utf-8")
    print(json.dumps({
        "report": str(out),
        "unique_forecasts": report["part_1_full_pool_evidence_and_settlement"][
            "unique_pre_match_forecasts"],
        "verified_settled": report["part_1_full_pool_evidence_and_settlement"][
            "settled_unique_forecasts"],
        "promotion_status": report["promotion_status"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
