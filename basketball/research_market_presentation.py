"""Private NBA bookmaker observation presentation, never betting advice.

Evaluate every saved pregame line rather than truncating early games. Group
the original bookmaker ladder by verified game identity and show its median
listed total purely as a neutral navigation reference. No probabilities, value
estimates, bookmaker recommendations or placed bets are produced.
"""
from __future__ import annotations

from basketball.research_market_watch import compare_to_archive

MAX_RETURNED_LINES = 600


def present_market_snapshot(board: dict, receipt: dict) -> dict:
    fixtures = receipt.get("fixtures") or []
    rows = []
    summaries = []
    for fixture in fixtures:
        isolated = {**receipt, "fixtures": [fixture]}
        related = compare_to_archive(board, isolated)["quoted_totals"]
        related = sorted(related, key=lambda item: item["line"])
        if not related:
            continue
        rows.extend(related)
        # Explicitly the middle of the offered bookmaker ladder, not the
        # bookmaker's official main line, and not a proposed wager.
        ref = related[len(related) // 2]
        summaries.append({
            "game_id": ref["game_id"],
            "event_id": ref["event_id"],
            "home": ref["home"],
            "away": ref["away"],
            "tipoff_utc": ref["tipoff_utc"],
            "observed_at": receipt["observed_at"],
            "reference_total": ref["line"],
            "over_odds": ref["over_odds"],
            "under_odds": ref["under_odds"],
            "projected_total": ref["projected_total"],
            "difference": ref["difference"],
            "paper_direction": ref["paper_direction"],
            "paper_grade": ref["paper_grade"],
            "actual_total": ref["actual_total"],
            "available_lines": len(related),
            "reference_kind": "median_offered_total_not_official_main_line",
            "recommendation": "NO_SELECTION_UNCALIBRATED",
        })
    summaries.sort(key=lambda x: (x["tipoff_utc"], x["game_id"]))
    rows.sort(key=lambda x: (x["tipoff_utc"], x["game_id"], x["line"]))
    graded = [
        x for x in summaries if x["paper_grade"] in (
            "correct", "incorrect", "push"
        )
    ]
    return {
        "status": "private_market_comparison",
        "source": receipt["source"],
        "digest": receipt["digest"],
        "observed_at": receipt["observed_at"],
        "fixture_matches": len(fixtures),
        "reference_games": summaries,
        "available_line_count": len(rows),
        "quoted_totals": rows[:MAX_RETURNED_LINES],
        "display_limit": MAX_RETURNED_LINES,
        "display_truncated": len(rows) > MAX_RETURNED_LINES,
        "paper_grade_summary": {
            "correct": sum(x["paper_grade"] == "correct" for x in graded),
            "incorrect": sum(x["paper_grade"] == "incorrect" for x in graded),
            "push": sum(x["paper_grade"] == "push" for x in graded),
            "real_bets_placed": 0,
        },
        "calibrated_betting_edge": False,
        "research_only": True,
        "not_bookable": True,
        "public_publishing_enabled": False,
    }
