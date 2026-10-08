"""Read-only explanation of why priced football markets fail conservative EV.

This diagnostic does not alter publication, model, market activation, booking
or confidence policy. Raw calibrated probability is NOT validated expected
edge, and a raw-positive result is not a reason to publish a wager.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from statistics import median

from scripts.prepare_staging_board_once import preflight


def value_diagnostics(picks: list[dict]) -> dict:
    from leagues.fixture_ranker import canonical_fixture_recommendations
    from leagues.publication_policy import evaluate_leg
    from leagues.selection_quality import (
        selection_probability, risk_adjusted_return,
    )

    permitted = canonical_fixture_recommendations(
        picks, include_all_eligible=True,
    )
    by_market = defaultdict(
        lambda: {"counts": Counter(), "prices": [], "conservative": [],
                 "probability_reduction": [], "risk_adjusted_returns": [],
                 "reasons": Counter()}
    )
    for pick in permitted:
        market = str(pick.get("market") or "unknown")
        row = by_market[market]
        row["counts"]["trusted_candidates"] += 1
        decision = evaluate_leg(pick, "5_odds")
        row["reasons"].update(decision["reasons"])
        if "NEGATIVE_MODEL_VALUE" in decision["reasons"]:
            row["counts"]["negative_model_value"] += 1
        if not (pick.get("odds_are_real") and pick.get("bookable")):
            row["counts"]["unverified_bookable_quote"] += 1
            continue
        try:
            quoted_odds = float(pick["odds"])
            calibrated = float(pick["confidence"])
        except (TypeError, ValueError, KeyError):
            row["counts"]["invalid_probability_or_odds"] += 1
            continue
        if (not math.isfinite(quoted_odds) or quoted_odds <= 1
                or not math.isfinite(calibrated)
                or not 0 < calibrated < 1):
            row["counts"]["invalid_probability_or_odds"] += 1
            continue
        conservative = selection_probability(pick)
        value = risk_adjusted_return(pick)
        row["counts"]["valid_exact_quote"] += 1
        row["prices"].append(quoted_odds)
        row["conservative"].append(conservative)
        row["probability_reduction"].append(calibrated - conservative)
        row["risk_adjusted_returns"].append(value)
        # A draw-no-bet push changes the payout equation, so this simple
        # raw probability × odds partition is intentionally not used for DNB.
        if market not in {"dnb_home", "dnb_away"}:
            if calibrated * quoted_odds >= 1 and value < 1:
                row["counts"]["raw_break_even_but_conservative_negative"] += 1
            elif calibrated * quoted_odds < 1 and value < 1:
                row["counts"]["raw_and_conservative_negative"] += 1
        stored = pick.get("risk_adjusted_return")
        try:
            if stored is not None and abs(float(stored) - value) > .001:
                row["counts"]["stale_stored_return"] += 1
        except (TypeError, ValueError):
            row["counts"]["invalid_stored_return"] += 1

    return {
        market: {
            **dict(sorted(row["counts"].items())),
            "median_verified_price": round(median(row["prices"]), 4)
            if row["prices"] else None,
            "median_conservative_probability": round(
                median(row["conservative"]), 4,
            ) if row["conservative"] else None,
            "median_calibrated_minus_conservative_probability": round(
                median(row["probability_reduction"]), 4,
            ) if row["probability_reduction"] else None,
            "median_conservative_expected_return": round(
                median(row["risk_adjusted_returns"]), 4,
            ) if row["risk_adjusted_returns"] else None,
            "rejection_reasons": dict(sorted(row["reasons"].items())),
        }
        for market, row in sorted(by_market.items())
    }


def audit() -> dict:
    db = preflight()
    from leagues.engine import prepared_board
    picks, fixtures, board = prepared_board(days_ahead=7)
    if not board.get("ready") or board.get("stale") or not fixtures:
        raise RuntimeError(
            "Refusing valuation diagnosis on stale board; use explicit "
            "refresh-capture, then rerun while the board is fresh"
        )
    return {
        "mode": "READ_ONLY_STAGING_MODEL_VALUE_BREAKDOWN",
        "database": db,
        "snapshot_id": board.get("board_snapshot_id"),
        "candidate_count": len(picks),
        "market_diagnostics": value_diagnostics(picks),
        "publication_or_booking": False,
        "thresholds_changed": False,
        "not_a_promotion_decision": True,
    }


if __name__ == "__main__":
    print(json.dumps(audit(), sort_keys=True))
