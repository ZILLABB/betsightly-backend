"""Admin-only generation of exact, externally researched SportyBet slips.

No public request can call the bookmaker's share endpoint through this route.
All input legs must resolve to an active selection on one COMPLETE, freshly
retrieved SportyBet board. Partial accumulator codes are never returned.
This creates a share code, NOT a wager.
"""

import os
from datetime import datetime, timezone

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from utils.security import require_api_key


# Only supported, non-under markets. Keep in sync with sportybet.py's canonical
# market mapping rather than trusting user-supplied bookmaker IDs.
ALLOWED_MARKETS = frozenset({
    "home_win", "draw", "away_win",
    "home_or_draw", "away_or_draw", "home_or_away",
    "over_1_5", "over_2_5", "over_3_5",
    "btts_yes", "dnb_home", "dnb_away",
})


class CuratedBookingLeg(BaseModel):
    home_team: str = Field(min_length=2, max_length=120)
    away_team: str = Field(min_length=2, max_length=120)
    league: str = Field(min_length=2, max_length=120)
    kickoff: datetime
    market: str = Field(min_length=3, max_length=32)


class CuratedBookingRequest(BaseModel):
    legs: list[CuratedBookingLeg] = Field(min_length=1, max_length=20)


def require_curated_booking_key(request: Request) -> None:
    """Unlike generic development auth, this expensive write is always locked."""
    if not os.getenv("API_KEY"):
        raise HTTPException(status_code=503, detail="admin_api_key_not_configured")
    require_api_key(request)


def generate_curated_booking(request: CuratedBookingRequest) -> dict:
    """Generate one validated code, or return a precise refusal and NO code."""
    from leagues.availability import kickoff_lifecycle
    from leagues.booking import create_or_reuse_generated_booking
    from leagues.sportybet import availability_for, board_metadata, fetch_board

    now = datetime.now(timezone.utc)
    games = []
    invalid = []
    seen_input = set()
    for i, leg in enumerate(request.legs):
        market = str(leg.market).strip().lower()
        if market not in ALLOWED_MARKETS:
            invalid.append({"leg": i + 1, "reason": "unsupported_market"})
            continue
        if leg.kickoff.tzinfo is None or leg.kickoff.utcoffset() is None:
            invalid.append({"leg": i + 1, "reason": "kickoff_timezone_required"})
            continue
        kickoff = leg.kickoff.astimezone(timezone.utc)
        if kickoff_lifecycle(kickoff, now) != "actionable":
            invalid.append({"leg": i + 1, "reason": "fixture_not_bookable_before_kickoff"})
            continue
        key = (leg.home_team.casefold().strip(), leg.away_team.casefold().strip())
        if key in seen_input:
            invalid.append({"leg": i + 1, "reason": "duplicate_fixture"})
            continue
        seen_input.add(key)
        games.append({
            "home_team": leg.home_team.strip(),
            "away_team": leg.away_team.strip(),
            "league": leg.league.strip(),
            "kickoff": kickoff.isoformat(),
            "market": market,
        })

    if invalid:
        return {"status": "unavailable", "share_code": None,
                "reason": "invalid_or_unbookable_legs", "failures": invalid,
                "requested_legs": len(request.legs)}

    # A partial or stale board must not be used to assert that a leg exists.
    # Admin calls are intentional and infrequent; force fresh bookmaker prices.
    board = fetch_board(force=True)
    meta = board_metadata(board)
    if meta.get("is_complete") is not True:
        return {"status": "unavailable", "share_code": None,
                "reason": "sportybet_board_incomplete",
                "board_snapshot_id": meta.get("snapshot_id")}

    failures = []
    event_ids = set()
    for i, game in enumerate(games):
        availability = availability_for(
            board, game["home_team"], game["away_team"], game["kickoff"],
            game["league"], game["market"],
        )
        if not availability.get("sportybet_available"):
            failures.append({
                "leg": i + 1, "match": game["home_team"] + " vs " + game["away_team"],
                "market": game["market"],
                "reason": availability.get("status") or "selection_unavailable",
                "detail": availability.get("failure_reason"),
            })
            continue
        event_id = str(availability.get("event_id") or "")
        if not event_id or event_id in event_ids:
            failures.append({"leg": i + 1,
                             "reason": "duplicate_or_missing_bookmaker_event"})
            continue
        event_ids.add(event_id)
        game["sportybet_availability"] = availability

    if failures:
        return {"status": "unavailable", "share_code": None,
                "reason": "not_all_legs_match_live_bookmaker_board",
                "requested_legs": len(games),
                "board_snapshot_id": meta.get("snapshot_id"),
                "failures": failures}

    booking = create_or_reuse_generated_booking(games, board)
    if (booking.get("status") != "active"
            or booking.get("readback_validation") != "PASSED"
            or booking.get("booking_status") not in ("FULL", "REBUILT_FULL")
            or int(booking.get("booked_leg_count") or 0) != len(games)
            or booking.get("partial")
            or not booking.get("share_code")):
        return {
            "status": "unavailable", "share_code": None,
            "reason": booking.get("failure_category") or
                      booking.get("reason") or "booking_readback_failed",
            "requested_legs": len(games),
            "board_snapshot_id": meta.get("snapshot_id"),
        }

    return {
        "status": "success", "share_code": booking["share_code"],
        "share_url": booking.get("share_url"),
        "actual_sportybet_odds": booking.get("actual_sportybet_odds"),
        "odds_source": booking.get("actual_sportybet_odds_source"),
        "readback_validation": "PASSED", "legs": len(games),
        "expires_at": booking.get("expires_at"),
        "board_snapshot_id": meta.get("snapshot_id"),
        "selections": [
            {"home_team": game["home_team"], "away_team": game["away_team"],
             "kickoff": game["kickoff"], "market": game["market"],
             "sportybet_odds": game["sportybet_availability"].get("sportybet_odds")}
            for game in games
        ],
        "note": "A booking code shares selections; it does not place a bet.",
    }
