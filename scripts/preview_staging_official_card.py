"""Simulate tomorrow's official cards from the existing staging board.

No fresh provider fetch, no publication lock, no archive, no SportyBet
booking creation and no settlement. Prints only policy/portfolio diagnostics.
Use only with the existing staging-only database preflight authorization.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone

from scripts.prepare_staging_board_once import preflight

TIERS = ("rollover", "banker", "2_odds", "5_odds", "10_odds", "over_1_5")


def simulate(*, target_date_wat: str | None = None) -> dict:
    database = preflight()

    from leagues.engine import prepared_board
    from leagues.daily_feed import build_daily_accumulators

    picks, fixtures, board = prepared_board(days_ahead=7)
    if not board.get("ready") or board.get("stale"):
        raise RuntimeError("Staging board is missing or stale; preview refused")
    if not picks or not fixtures:
        raise RuntimeError("Prepared board has no evaluated fixtures or picks")

    now = datetime.now(timezone.utc)
    today_wat = (now + timedelta(hours=1)).date()
    if target_date_wat is None:
        target_wat_date = (today_wat + timedelta(days=1)).isoformat()
    else:
        try:
            target = date.fromisoformat(target_date_wat)
        except ValueError as exc:
            raise ValueError("Target date must be YYYY-MM-DD") from exc
        if target < today_wat or target > today_wat + timedelta(days=6):
            raise ValueError("Target date must be within the current 7-day staging board")
        target_wat_date = target.isoformat()
    # The preview pathway is intentionally not a publication path:
    # no existing-card load, no pre-publication booking, no archive, no lock.
    card = build_daily_accumulators(preview={
        "captured_at": now.isoformat(),
        "target_wat_date": target_wat_date,
        "picks": picks,
        "fixtures": fixtures,
    })
    if not card:
        raise RuntimeError("No eligible staging official-card preview produced")
    if card.get("locked"):
        raise RuntimeError("Preview unexpectedly locked an official card")

    accumulators = card.get("accumulators") or {}
    fixture_ids = []
    products = {}
    for tier in TIERS:
        data = accumulators.get(tier) or {}
        games = data.get("games") or []
        selected = bool(data.get("selected"))
        if not selected and games:
            raise RuntimeError(f"{tier} has games but is not selected")
        for game in games:
            mid = str(game.get("match_id") or "")
            if not mid:
                raise RuntimeError(f"{tier} has a fixture without match_id")
            fixture_ids.append(mid)
        if data.get("booking") or data.get("share_code"):
            raise RuntimeError(f"{tier} preview contains a booking code")
        products[tier] = {
            "selected": selected,
            "legs": len(games),
            "odds": data.get("total_odds"),
            "presentation": data.get("presentation"),
            "reason": data.get("reason") if not selected else None,
            "proposed_games": [
                {
                    "fixture_id": game.get("match_id"),
                    "home": game.get("home_team"),
                    "away": game.get("away_team"),
                    "kickoff": game.get("kickoff") or game.get("date"),
                    "market": game.get("market") or game.get("market_key"),
                    "quoted_odds_at_capture": game.get("odds"),
                    "model_confidence": game.get("confidence"),
                }
                for game in games
            ],
        }
    # Portfolio exposure contract is hard-cap one fixture per official tier.
    if len(fixture_ids) != len(set(fixture_ids)):
        raise RuntimeError("Duplicate fixture found across official preview tiers")

    summary = {
        "database": database,
        "preview_only": True,
        "official_publication": False,
        "booking_codes_created": False,
        "locked": False,
        "target_wat_date": target_wat_date,
        "fixture_target_date": card.get("fixture_target_date"),
        "requested_date_matched": card.get("fixture_target_date") == target_wat_date,
        "warning": (
            "Staging only; NOT an official published slip or verified booking. "
            "Bookmaker prices require live readback before betting. "
            "A false requested_date_matched means the selector used another fixture date."
        ),
        "board_snapshot_id": board.get("board_snapshot_id"),
        "board_complete": board.get("complete"),
        "board_degraded": board.get("degraded"),
        "board_age_seconds": board.get("age_seconds"),
        "evaluated_fixtures": len(fixtures),
        "model_candidate_picks": len(picks),
        "official_product_preview": products,
        "duplicate_fixture_count": 0,
        "publication_policy": card.get("publication_policy"),
    }
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date", dest="target_date_wat", metavar="YYYY-MM-DD",
        help="Explicit match-day in Nigeria (prevents midnight rollover)",
    )
    args = parser.parse_args()
    print(json.dumps(
        simulate(target_date_wat=args.target_date_wat),
        sort_keys=True, default=str,
    ))
