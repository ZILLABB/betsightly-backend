"""Compare OFFICIAL SLIP outcomes in guarded staging preview (zero writes).

This checks whether retaining all *already active* market alternatives helps
real 2x/5x/10x slip construction, not merely counting more candidates.
Production branch, actual publication, bookings and notifications untouched.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone

from scripts.prepare_staging_board_once import preflight

TIERS = ("rollover", "banker", "2_odds", "5_odds", "10_odds", "over_1_5")
FLAG = "BETSIGHTLY_PREVIEW_ALL_MARKETS"


def _overview(card: dict | None) -> dict:
    if not card:
        return {"available": False, "tiers": {}, "fixture_overlap_count": None}
    data = card.get("accumulators") or {}
    fixtures: list[str] = []
    products = {}
    for tier in TIERS:
        entry = data.get(tier) or {}
        games = entry.get("games") or []
        selected = bool(entry.get("selected") and games)
        if selected:
            fixtures.extend(str(game.get("match_id") or "") for game in games)
        products[tier] = {
            "selected": selected,
            "legs": len(games) if selected else 0,
            "odds": entry.get("total_odds") if selected else None,
            "market_mix": dict(Counter(game.get("market") for game in games))
                          if selected else {},
            "reason": None if selected else entry.get("reason"),
        }
    repeated = len(fixtures) - len(set(fixtures))
    if repeated:
        raise RuntimeError("Official preview duplicated a fixture across tiers")
    return {
        "available": True,
        "fixture_target_date": card.get("fixture_target_date"),
        "tiers": products,
        "fixture_overlap_count": repeated,
    }


def compare() -> dict:
    database = preflight()
    from leagues.engine import prepared_board
    from leagues.daily_feed import build_daily_accumulators

    picks, fixtures, board = prepared_board(days_ahead=7)
    if not board.get("ready") or board.get("stale"):
        raise RuntimeError("Refusing official-card comparison: staging board stale")
    captured = datetime.now(timezone.utc)
    date_wat = ((captured + timedelta(hours=1)).date()
                + timedelta(days=1)).isoformat()
    arguments = {"preview": {
        "captured_at": captured.isoformat(),
        "target_wat_date": date_wat,
        "picks": picks,
        "fixtures": fixtures,
    }}
    previous = os.environ.get(FLAG)
    try:
        os.environ[FLAG] = "0"
        baseline = _overview(build_daily_accumulators(**arguments))
        os.environ[FLAG] = "1"
        expanded = _overview(build_daily_accumulators(**arguments))
    finally:
        if previous is None:
            os.environ.pop(FLAG, None)
        else:
            os.environ[FLAG] = previous

    gain = {}
    for tier in TIERS:
        before = baseline["tiers"].get(tier) or {}
        after = expanded["tiers"].get(tier) or {}
        gain[tier] = {
            "baseline_selected": bool(before.get("selected")),
            "expanded_selected": bool(after.get("selected")),
            "baseline_legs": before.get("legs", 0),
            "expanded_legs": after.get("legs", 0),
            "additional_legs": after.get("legs", 0) - before.get("legs", 0),
        }

    return {
        "database": database,
        "mode": "READ_ONLY_STAGING_OFFICIAL_MARKET_ALTERNATIVES_PREVIEW",
        "board_snapshot_id": board.get("board_snapshot_id"),
        "board_degraded": board.get("degraded"),
        "model_fixture_count": len(fixtures),
        "model_candidate_count": len(picks),
        "target_wat_date": date_wat,
        "quality_thresholds_changed": False,
        "official_publication": False,
        "booking_codes_created": False,
        "baseline": baseline,
        "expanded": expanded,
        "gain": gain,
    }


if __name__ == "__main__":
    print(json.dumps(compare(), sort_keys=True, default=str))
