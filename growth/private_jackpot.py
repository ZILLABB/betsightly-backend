"""Private admin-only, exact-selection SportyBet jackpot preparation and booking.

No predictions, codes, or model results are invented here. All selectable legs
come from BetSightly's already approved, bookmaker-bookable V2 candidate pool.
This module does not publish to the public frontend or modify calibration.
Authentication is enforced by growth.api before invoking these functions.
"""
from __future__ import annotations

from math import isfinite, prod
from typing import Any

MAX_LEGS = 50
MIN_ODDS = 2.0
MAX_TARGET = 100_000.0
ALLOWED_HORIZONS = {"today", "3_days", "7_days"}
ALLOWED_GRADES = {"A", "B"}


def filters_for(payload: dict) -> dict:
    horizon = str(payload.get("horizon") or "today")
    grade = str(payload.get("min_trust_grade") or "B").upper()
    if horizon not in ALLOWED_HORIZONS or grade not in ALLOWED_GRADES:
        raise ValueError("Invalid date horizon or trust grade.")
    markets = [str(v).strip() for v in (payload.get("markets") or [])]
    if len(markets) > 24 or any(not v or len(v) > 40 or v.startswith("under_") for v in markets):
        raise ValueError("Invalid market filter or under-goals market requested.")
    return {
        "horizon": horizon,
        "markets": markets,
        "min_trust_grade": grade,
        "min_probability": max(.65, float(payload.get("min_probability") or .65)),
        "require_bookable": True,
    }


def candidate_board(payload: dict) -> dict:
    from leagues.builder_v2 import list_candidates
    options = filters_for(payload)
    data = list_candidates(options)
    if data.get("status") != "success":
        return {
            "status": data.get("status") or "unavailable",
            "reason": data.get("reason") or "The approved bookmaker board is unavailable.",
            "board": data.get("board"),
        }
    candidates: list[dict] = []
    for value in data.get("candidates") or []:
        market = str(value.get("market") or "")
        price = float(value.get("odds") or 0)
        if market.startswith("under_") or price <= 1 or not isfinite(price):
            continue
        if not value.get("bookable") or not value.get("selection_id"):
            continue
        candidates.append({
            "selection_id": str(value["selection_id"]),
            "match_id": str(value.get("match_id") or ""),
            "home_team": value.get("home_team"),
            "away_team": value.get("away_team"),
            "league": value.get("league"),
            "kickoff": value.get("kickoff"),
            "market": market,
            "odds": price,
            "selection_probability": value.get("selection_probability"),
            "lower_reliability_bound": value.get("lower_reliability_bound"),
            "trust_grade": value.get("trust_grade"),
            "expected_value": value.get("expected_value"),
            "recommended_for_fixture": bool(value.get("recommended_for_fixture")),
        })
    from growth.jackpot_optimizer import capacity
    return {
        "status": "success",
        **capacity(candidates),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "board": data.get("board"),
        "selection_diagnostics": data.get("selection_diagnostics"),
        "note": "Model probabilities are estimates, not assurances. One market per fixture.",
    }


def optimize_request(payload: dict) -> dict:
    """Dry run only: no SportyBet share operation or public publication."""
    from growth.jackpot_optimizer import optimize
    target = float(payload.get("target_odds") or MIN_ODDS)
    if not isfinite(target) or not MIN_ODDS <= target <= MAX_TARGET:
        raise ValueError("Target odds must be between 2x and 100,000x.")
    state = candidate_board(payload)
    if state.get("status") != "success":
        return {**state, "selection_ids": [], "booking_code_created": False}
    return {
        **optimize(
            state["candidates"], target,
            limit=int(payload.get("max_legs") or MAX_LEGS),
        ),
        "board": state.get("board"),
    }


def booking_request(payload: dict) -> dict:
    from leagues.builder_v2 import manual_build
    target = float(payload.get("target_odds") or MIN_ODDS)
    if not isfinite(target) or not MIN_ODDS <= target <= MAX_TARGET:
        raise ValueError("Target odds must be between 2x and 100,000x.")
    ids = [str(v) for v in (payload.get("selection_ids") or [])]
    if not 1 <= len(ids) <= MAX_LEGS or len(set(ids)) != len(ids):
        raise ValueError("Choose 1 to 50 distinct selections.")

    # Re-read server-side approved IDs immediately before any bookmaker write.
    state = candidate_board(payload)
    if state.get("status") != "success":
        return state
    known = {row["selection_id"]: row for row in state["candidates"]}
    if any(key not in known for key in ids):
        return {"status": "SELECTIONS_CHANGED", "reason": "One or more picks are no longer approved/bookable.", "share_code": None}
    selected = [known[key] for key in ids]
    fixture_ids = [row["match_id"] for row in selected]
    if any(not item for item in fixture_ids) or len(set(fixture_ids)) != len(ids):
        return {"status": "SELECTIONS_CHANGED", "reason": "Only one market per distinct fixture is permitted.", "share_code": None}
    indicative = prod(row["odds"] for row in selected)
    if not isfinite(indicative) or indicative < target:
        return {
            "status": "BELOW_TARGET",
            "reason": "Approved reference prices do not reach the requested target. No bookmaker code was requested.",
            "indicative_odds": round(indicative, 3),
            "share_code": None,
        }

    # Uses existing exact event/market/outcome mapper and FULL readback policy.
    result = manual_build({**filters_for(payload), "selection_ids": ids})
    booking = result.get("booking") or {}
    exact = (
        result.get("status") == "success"
        and booking.get("status") == "active"
        and booking.get("booking_status") in {"FULL", "REBUILT_FULL"}
        and booking.get("readback_validation") == "PASSED"
        and int(booking.get("booked_leg_count") or 0) == len(ids)
        and bool(booking.get("share_code"))
    )
    if not exact:
        return {
            "status": result.get("status") or "BOOKING_UNAVAILABLE",
            "reason": result.get("reason") or booking.get("reason") or "Exact SportyBet readback failed.",
            "share_code": None,
            "invalid_selections": result.get("invalid_selections") or [],
        }
    actual = float(booking.get("actual_sportybet_odds") or 0)
    if not isfinite(actual) or actual < target:
        return {
            "status": "BELOW_TARGET",
            "reason": "The verified bookmaker odds dropped below the required target. No code is released.",
            "verified_odds": actual,
            "share_code": None,
        }
    return {
        "status": "success",
        "share_code": booking["share_code"],
        "share_url": booking.get("share_url"),
        "verified_odds": round(actual, 3),
        "legs": len(ids),
        "readback_status": "PASSED",
        "priced_at": booking.get("priced_at"),
        "expires_at": booking.get("expires_at"),
        "estimated_all_leg_probability": result.get("estimated_all_leg_probability"),
        "probability_assumption": "approximate_independence",
        "publication_status": "PRIVATE_NOT_PUBLISHED",
        "note": "This verified share code does not place a bet or publish to BetSightly.",
    }
