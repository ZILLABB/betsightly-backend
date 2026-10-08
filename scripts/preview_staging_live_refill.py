"""Date-pinned, read-only staging simulation for rolling Available Now cards.

Runs multiple Nigerian local times against the same persisted seven-day board.
Never calls SportyBet, writes bookings, changes rollover, or locks official picks.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone

from scripts.prepare_staging_board_once import preflight

WAT = timezone(timedelta(hours=1))
TIMES_WAT = (8, 12, 16, 20)
TIERS = ("banker", "2_odds", "5_odds", "10_odds", "over_1_5")


def simulate(target_day: str) -> dict:
    database = preflight()
    requested = date.fromisoformat(target_day)
    today = datetime.now(WAT).date()
    if requested < today or requested > today + timedelta(days=6):
        raise ValueError("Requested WAT day must be in the current seven-day board")

    from leagues.engine import prepared_board
    from leagues.daily_feed import build_bookable_now

    picks, fixtures, board = prepared_board(days_ahead=7)
    if not board.get("ready") or board.get("stale"):
        raise RuntimeError("Staging prepared board is missing or stale")
    if not picks or not fixtures:
        raise RuntimeError("No staging board candidates available")

    previews = []
    for hour_wat in TIMES_WAT:
        simulated_at = datetime(
            requested.year, requested.month, requested.day,
            hour_wat, tzinfo=WAT,
        ).astimezone(timezone.utc)
        result = build_bookable_now(
            all_picks=picks, now=simulated_at, preview_only=True,
        )
        if not result or not result.get("preview_only"):
            raise RuntimeError("Live refill did not return a read-only preview")
        if not result.get("published_record_unchanged"):
            raise RuntimeError("Preview unexpectedly changed an official card")
        if result.get("booking_codes_created"):
            raise RuntimeError("Preview unexpectedly booked a code")
        summaries = {}
        ids_by_tier = {}
        for tier in TIERS:
            cat = (result.get("accumulators") or {}).get(tier) or {}
            games = cat.get("games") or []
            if cat.get("booking") or cat.get("share_code"):
                raise RuntimeError(f"Preview includes an actionable code: {tier}")
            ids = [str(g.get("match_id") or "") for g in games]
            if len(ids) != len(set(ids)):
                raise RuntimeError(f"Duplicate fixture within {tier}")
            ids_by_tier[tier] = ids
            summaries[tier] = {
                "selected": bool(cat.get("selected")),
                "legs": len(games),
                "model_odds": cat.get("total_odds"),
                "reason": cat.get("reason"),
                "fixtures": [{
                    "match_id": g.get("match_id"),
                    "home": g.get("home_team"),
                    "away": g.get("away_team"),
                    "market": g.get("market") or g.get("market_key"),
                    "kickoff": g.get("kickoff") or g.get("date"),
                } for g in games],
            }
        portfolio = result.get("_portfolio") or {}
        if not (portfolio.get("portfolio_validation") or {}).get("valid"):
            raise RuntimeError("Live portfolio invalid during staging simulation")
        # Over 1.5 remains independent singles (not a mutually exclusive
        # official accumulator tier under the current contract).
        official = [id_ for name in TIERS if name != "over_1_5"
                    for id_ in ids_by_tier[name]]
        if len(official) != len(set(official)):
            raise RuntimeError("Cross-tier fixture overlap in live accumulator")
        previews.append({
            "at_wat": simulated_at.astimezone(WAT).isoformat(),
            "lookahead_ends_at": result.get("window_ends_at"),
            "kickoffs_remaining": result.get("kickoffs_remaining"),
            "selected_tier_count": sum(bool(row["selected"])
                                       for row in summaries.values()),
            "tiers": summaries,
        })
    return {
        "database": database,
        "target_wat_date": target_day,
        "preview_only": True,
        "official_publication": False,
        "booking_codes_created": False,
        "published_record_unchanged": True,
        "board_age_seconds": board.get("age_seconds"),
        "board_snapshot_id": board.get("board_snapshot_id"),
        "wat_times": list(TIMES_WAT),
        "snapshots": previews,
        "note": ("Staging simulations use captured prices, not fresh SportyBet "
                 "readback; no results here claim a currently bookable ticket."),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="YYYY-MM-DD in Nigeria")
    args = parser.parse_args()
    print(json.dumps(simulate(args.date), sort_keys=True, default=str))
