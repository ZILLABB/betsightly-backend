"""Simulate tomorrow's official cards from the existing staging board.

No fresh provider fetch, no publication lock, no archive, no SportyBet
booking creation and no settlement. Prints only policy/portfolio diagnostics.
Use only with the existing staging-only database preflight authorization.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from scripts.prepare_staging_board_once import preflight

TIERS = ("rollover", "banker", "2_odds", "5_odds", "10_odds", "over_1_5")


def simulate() -> dict:
    database = preflight()

    from leagues.engine import prepared_board
    from leagues.daily_feed import build_daily_accumulators

    picks, fixtures, board = prepared_board(days_ahead=7)
    if not board.get("ready") or board.get("stale"):
        raise RuntimeError("Staging board is missing or stale; preview refused")
    if not picks or not fixtures:
        raise RuntimeError("Prepared board has no evaluated fixtures or picks")

    now = datetime.now(timezone.utc)
    target_wat_date = (
        (now + timedelta(hours=1)).date() + timedelta(days=1)
    ).isoformat()
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
    print(json.dumps(simulate(), sort_keys=True, default=str))
