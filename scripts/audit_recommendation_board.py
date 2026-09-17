"""Read-only recommendation/Daily audit for one WAT fixture date."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from leagues.engine import picks_for_date, run_pipeline  # noqa: E402
from leagues.fixture_ranker import canonical_fixture_recommendations  # noqa: E402
from leagues.picks import MIN_PUBLISHABLE_CONFIDENCE  # noqa: E402
from leagues.recommendation_board import build_recommendation_board  # noqa: E402
from leagues.selection import select_accumulator, select_banker  # noqa: E402


def _product(selection: tuple[list[dict], float, float]) -> dict:
    picks, odds, joint = selection
    return {
        "selected": bool(picks), "odds": odds, "legs": len(picks),
        "joint_probability": joint,
        "fixtures": [pick.get("match_id") for pick in picks],
        "markets": [pick.get("market") for pick in picks],
    }


def _accumulator(picks: list[dict], target: float, max_picks: int,
                 min_ev: float, band_low: float) -> dict:
    selected = select_accumulator(
        picks, target, max_picks, MIN_PUBLISHABLE_CONFIDENCE,
        min_ev=min_ev, band_low=band_low, canonicalize=False,
    )
    result = _product(selected)
    if result["selected"]:
        result["constraint"] = None
        return result
    ungated = select_accumulator(
        picks, target, max_picks, MIN_PUBLISHABLE_CONFIDENCE,
        min_ev=0.0, band_low=band_low, canonicalize=False,
    )
    result["constraint"] = (
        "EXPECTED_RETURN_FLOOR" if ungated[0]
        else "NO_COMBINATION_WITHIN_MARKET_EXPOSURE_AND_LEG_LIMIT"
    )
    result["ungated_best"] = _product(ungated)
    return result


def audit(date: str, days_ahead: int) -> dict:
    picks, fixtures = run_pipeline(days_ahead=days_ahead)
    board = build_recommendation_board(picks, fixtures, date=date)
    date_picks = canonical_fixture_recommendations(picks_for_date(date, picks))
    safe = [pick for pick in date_picks if pick.get("safe_tier_eligible")]
    odds = sorted(float(pick.get("odds") or 0) for pick in date_picks)
    return {
        "date": date,
        "board_summary": board["summary"],
        "market_distribution": board["market_distribution"],
        "premium_candidate_count": len(date_picks),
        "safe_tier_candidate_count": len(safe),
        "premium_market_distribution": dict(Counter(
            str(pick.get("market") or "unknown") for pick in date_picks
        )),
        "premium_market_group_distribution": dict(Counter(
            str(pick.get("market_group") or "unknown") for pick in date_picks
        )),
        "premium_odds": {
            "min": min(odds) if odds else None,
            "median": odds[len(odds) // 2] if odds else None,
            "max": max(odds) if odds else None,
        },
        "independent_products": {
            "banker": _product(select_banker(safe, canonicalize=False)),
            "2_odds": _accumulator(safe, 2.0, 4, .82, .92),
            "5_odds": _accumulator(date_picks, 5.0, 8, .72, .80),
            "10_odds": _accumulator(date_picks, 10.0, 10, .63, .80),
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date",
        default=(datetime.now(timezone.utc) + timedelta(hours=1)).date().isoformat(),
    )
    parser.add_argument("--days-ahead", type=int, default=4)
    args = parser.parse_args()
    print(json.dumps(audit(args.date, args.days_ahead), indent=2))
