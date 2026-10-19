"""Opt-in, verified rebooking of the *remaining* legs of today's manual tickets.

The daily manual publication and its stored bookmaker code are immutable.
A subset is a DIFFERENT wager: this module never reuses the old booking code,
writes to tier_bookings, overwrites an official card, or changes model metrics.
Only the exact surviving set is newly booked and validated by SportyBet.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from leagues.availability import game_kickoff_lifecycle

_MANUAL_TIERS = ("banker", "2_odds", "5_odds", "10_odds", "over_1_5")
_WAT = timezone(timedelta(hours=1))
# Only this opt-in rebooking feature uses 10 minutes. Official publishing,
# Rollover and ordinary Builder retain their default 20-minute safety rule.
MANUAL_BOOKING_BUFFER = timedelta(minutes=10)


def _wat_day(now: datetime) -> str:
    return now.astimezone(_WAT).date().isoformat()


def _manual_original_legs(record: dict) -> list[dict]:
    """Only trust an original manually curated ticket with verified readback."""
    if record.get("status") not in (None, "active"):
        return []
    # Editions use "code" while the current booking uses "share_code".
    if (record.get("readback_validation") != "PASSED" or
            not (record.get("share_code") or record.get("code"))):
        return []
    legs = record.get("original_legs") or []
    if not isinstance(legs, list) or not legs:
        return []
    # Never infer manual status from the category name: the morning auto card
    # may use the same tier key as an admin publication.
    if not all(isinstance(g, dict) and g.get("editorial_manual") is True for g in legs):
        return []
    return legs


def eligible_manual_remainder(
    record: dict,
    tier: str,
    board: dict,
    *,
    now: datetime,
) -> dict:
    """Pure selection + one booking call for an eligible manual ticket.

    An accumulator with fewer than two legs left is not portrayed as a
    replacement of a multi-leg tier. Such bets can be explored in Builder.
    """
    from leagues.booking import _revalidate_games, create_or_reuse_generated_booking

    original = _manual_original_legs(record)
    if not original:
        return {"selected": False, "reason": "No verified manual publication for this tier."}

    min_remaining = 1 if tier == "banker" else 2
    timed = [g for g in original if game_kickoff_lifecycle(
        g, now, booking_buffer=MANUAL_BOOKING_BUFFER) == "actionable"]
    rejected_at_kickoff = len(original) - len(timed)
    if len(timed) < min_remaining:
        return {
            "selected": False,
            "reason": "Too few unstarted manual selections remain.",
            "original_leg_count": len(original),
            "remaining_leg_count": len(timed),
            "removed_leg_count": rejected_at_kickoff,
        }

    # Recheck each original selection against the CURRENT SportyBet board.
    # Old odds, outdated availability flags and the old original shareCode are
    # not evidence that a new smaller bet is actually still placeable.
    verified, excluded = _revalidate_games(timed, board)
    if len(verified) < min_remaining:
        return {
            "selected": False,
            "reason": "The remaining selections cannot be verified on SportyBet.",
            "original_leg_count": len(original),
            "remaining_leg_count": len(verified),
            "removed_leg_count": rejected_at_kickoff + len(excluded),
        }

    # Only after pruning exactly to verified legs do we create/reuse a booking.
    # The booking utility enforces precise selection mapping and live readback.
    new_booking = create_or_reuse_generated_booking(
        verified, board, kickoff_buffer=MANUAL_BOOKING_BUFFER)
    valid = (
        new_booking.get("status") == "active"
        and new_booking.get("booking_status") in {"FULL", "REBUILT_FULL"}
        and new_booking.get("readback_validation") == "PASSED"
        and bool(new_booking.get("share_code"))
        and not new_booking.get("partial")
        and new_booking.get("booked_leg_count", len(verified)) == len(verified)
    )
    if not valid:
        return {
            "selected": False,
            "reason": "A new exact SportyBet code could not be verified.",
            "original_leg_count": len(original),
            "remaining_leg_count": len(verified),
            "removed_leg_count": len(original) - len(verified),
        }

    actual_odds = new_booking.get("actual_sportybet_odds")
    if not isinstance(actual_odds, (int, float)) or actual_odds <= 1.0:
        return {"selected": False, "reason": "Current bookmaker odds could not be confirmed."}

    return {
        "selected": True,
        "source": "admin_curated",
        "editorial_manual": True,
        "manual_remainder": True,
        "official_publication": False,
        "result_scored": False,
        "games": verified,
        "total_odds": round(float(actual_odds), 3),
        "risk_level": "Manual remainder",
        "presentation": "accumulator",
        "booking": new_booking,
        "original_leg_count": len(original),
        "remaining_leg_count": len(verified),
        "removed_leg_count": len(original) - len(verified),
        "reason": (
            f"Freshly booked {len(verified)} of {len(original)} original manual selections. "
            "This reduced slip is independent of the official published ticket."
        ),
    }


def build_manual_remainders(
    *,
    now: datetime | None = None,
    records: dict[str, dict] | None = None,
    board: dict | None = None,
) -> dict[str, Any]:
    """Assemble only currently validated manual tickets; do not edit storage.

    Optional inputs are injectable in tests. No bookmaker call or board fetch
    occurs when today's store contains no independently verified manual legs.
    """
    from leagues.booking import bookings_for, booking_editions_for
    from leagues import sportybet

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    date = _wat_day(current)
    source = records if records is not None else bookings_for(date)
    candidates: dict[str, dict] = {}
    for tier in _MANUAL_TIERS:
        current_record = (source or {}).get(tier)
        if isinstance(current_record, dict) and _manual_original_legs(current_record):
            candidates[tier] = current_record
            continue
        if records is not None:
            # Explicit fixture-injection tests must not touch the live DB.
            continue
        # A tier's current booking can be marked unavailable as soon as its
        # FIRST leg starts, while a later manual leg is still actionable.
        # The append-only validated booking edition retains the original
        # manual selections. Never trust an edition without its passed readback.
        for edition in reversed(booking_editions_for(date, tier)):
            if isinstance(edition, dict) and _manual_original_legs(edition):
                candidates[tier] = edition
                break
    if not candidates:
        return {"available": False, "tiers": {}, "date": date,
                "official_publication_unchanged": True}

    snapshot = board if board is not None else sportybet.fetch_board()
    results: dict[str, dict] = {}
    for tier, record in candidates.items():
        result = eligible_manual_remainder(record, tier, snapshot, now=current)
        if result.get("selected"):
            results[tier] = result

    return {
        "available": bool(results),
        "tiers": results,
        "date": date,
        "official_publication_unchanged": True,
        "record_is_separate": True,
    }
