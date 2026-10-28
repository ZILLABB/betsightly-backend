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



def _verified_editorial_source(publication: dict) -> dict | None:
    """Convert the immutable admin publication into an eligible source.

    Admin tickets are saved in editorial_tier_slips, NOT tier_bookings.
    Never guess that a category's ordinary morning booking represents this
    manual publication. Prove exact booked identities and counts before
    copying its verified legs into the separate rebooking flow.
    """
    if not isinstance(publication, dict) or publication.get("editorial_manual") is not True:
        return None
    games = publication.get("games")
    booking = publication.get("booking")
    if not isinstance(games, list) or not games or not isinstance(booking, dict):
        return None
    if not all(isinstance(g, dict) and g.get("editorial_manual") is True for g in games):
        return None
    if (booking.get("status") != "active" or
            booking.get("readback_validation") != "PASSED" or
            booking.get("booking_status") != "FULL" or
            booking.get("partial") or not booking.get("share_code")):
        return None

    from leagues.booking import leg_fingerprint
    expected = leg_fingerprint(games)
    originals = booking.get("original_legs")
    final = booking.get("final_booked_legs")
    if (not isinstance(originals, list) or not isinstance(final, list)
            or len(originals) != len(games) or len(final) != len(games)):
        return None
    if not (expected == leg_fingerprint(originals) == leg_fingerprint(final)
            == booking.get("leg_fingerprint")
            == booking.get("booking_variant_fingerprint")):
        return None
    try:
        if (int(booking.get("original_leg_count") or 0) != len(games) or
                int(booking.get("booked_leg_count") or 0) != len(games)):
            return None
    except (ValueError, TypeError, OverflowError):
        return None

    # Never mutate the archived publication or its booking. The new code
    # belongs exclusively to the reduced set and a separate generated ledger.
    return {**booking, "original_legs": list(games)}




def _verified_new_booking(games: list[dict], board: dict) -> dict | None:
    """Rebook only exact available legs, with a new or rechecked provider code."""
    from leagues.booking import create_or_reuse_generated_booking
    booked = create_or_reuse_generated_booking(
        games, board, kickoff_buffer=MANUAL_BOOKING_BUFFER)
    if not (
        booked.get("status") == "active"
        and booked.get("booking_status") in {"FULL", "REBUILT_FULL"}
        and booked.get("readback_validation") == "PASSED"
        and bool(booked.get("share_code"))
        and not booked.get("partial")
        and booked.get("booked_leg_count") == len(games)
    ):
        return None
    from leagues.booking import leg_fingerprint
    if (booked.get("booking_variant_fingerprint") and
            booked["booking_variant_fingerprint"] != leg_fingerprint(games)):
        return None
    price = booked.get("actual_sportybet_odds")
    if not isinstance(price, (float, int)) or not 1 < price < float("inf"):
        return None
    return booked



def qualified_supplemental_candidates(
    picks: list[dict], *, now: datetime | None = None,
) -> list[dict]:
    """Bounded, trusted model opinions, never scraped arbitrary high odds.

    Called only for the visitor's explicit 'closer odds' request. Eligible
    fixtures belong to today in WAT and are still outside the 10m cutoff.
    """
    from leagues.picks import to_game
    from leagues.publication_policy import filter_official_candidates
    from leagues.availability import parse_kickoff
    from leagues.selection_quality import selection_probability

    at = now or datetime.now(timezone.utc)
    approved, _ = filter_official_candidates(picks, "5_odds")
    by_fixture: dict[str, dict] = {}
    for pick in approved:
        if not pick.get("bookable") or not pick.get("match_id"):
            continue
        kickoff = parse_kickoff((pick.get("_fixture") or {}).get("commence_time"))
        if (kickoff is None or kickoff <= at + MANUAL_BOOKING_BUFFER
                or kickoff.astimezone(_WAT).date() != at.astimezone(_WAT).date()):
            continue
        try:
            if float(selection_probability(pick)) < .65:
                continue
            game = to_game(pick)
        except (KeyError, ValueError, TypeError, OverflowError):
            continue
        match_id = str(pick["match_id"])
        previous = by_fixture.get(match_id)
        if previous is None or (float(game.get("selection_probability") or
                                     game.get("confidence") or 0) >
                                float(previous.get("selection_probability") or
                                      previous.get("confidence") or 0)):
            by_fixture[match_id] = game
    return sorted(by_fixture.values(), key=lambda g: (
        -float(g.get("selection_probability") or g.get("confidence") or 0),
        str(g.get("match_id") or "")))[:60]

def _near_target_variant(
    original: dict, reduced: dict, candidate_games: list[dict], board: dict,
    *, now: datetime,
) -> dict | None:
    """Explicitly requested alternative, never a replacement official slip.

    Prefer previously published surviving legs. Add at most four independently
    model-qualified future fixtures, one market per fixture, only when a
    reasonable price close to the original can be achieved. If we cannot
    verify the whole bookmaker code, we return nothing rather than guessing.
    """
    from leagues.booking import _revalidate_games
    from math import log, prod

    remaining = reduced.get("games") or []
    if not remaining:
        return None
    try:
        target = float(original.get("total_odds") or
                       (original.get("booking") or {}).get("actual_sportybet_odds"))
    except (TypeError, ValueError, OverflowError):
        return None
    if not 1 < target <= 50:
        return None

    priced_remaining = prod(float(game.get("odds") or 0) for game in remaining)
    if priced_remaining <= 1 or priced_remaining >= target * .85:
        return None

    used = {str(g.get("sportybet_event_id") or g.get("match_id") or "")
            for g in remaining}
    used_teams = {str(g.get(key) or "").strip().casefold()
                  for g in remaining for key in ("home_team", "away_team")}
    candidates = []
    for game in candidate_games[:80]:
        identity = str(game.get("sportybet_event_id") or game.get("match_id") or "")
        teams = {str(game.get(key) or "").strip().casefold()
                 for key in ("home_team", "away_team")}
        if (not identity or identity in used or
                teams & used_teams or
                game_kickoff_lifecycle(game, now, booking_buffer=MANUAL_BOOKING_BUFFER)
                != "actionable"):
            continue
        try:
            confidence = float(game.get("selection_probability") or
                               game.get("confidence") or 0)
        except (ValueError, TypeError, OverflowError):
            continue
        if not (0.65 <= confidence <= 1):
            continue
        candidates.append(game)
    if not candidates:
        return None

    # A single board snapshot supplies both prices and bookmaker identities.
    # Recheck no more than 60 qualified alternatives to bound provider work.
    verified, _ = _revalidate_games(candidates[:60], board)
    ranked = sorted(verified, key=lambda g: (
        -float(g.get("selection_probability") or g.get("confidence") or 0),
        str(g.get("match_id") or ""), str(g.get("market") or "")))
    added = []
    running = priced_remaining
    max_additions = max(0, min(4, 20 - len(remaining)))
    for _ in range(max_additions):
        current_gap = abs(log(running / target))
        ranked_choices = []
        for game in ranked:
            event = str(game.get("sportybet_event_id") or game.get("match_id") or "")
            team_names = {str(game.get(key) or "").strip().casefold()
                          for key in ("home_team", "away_team")}
            if event in used or team_names & used_teams:
                continue
            try:
                price = float(game.get("odds") or 0)
            except (TypeError, ValueError, OverflowError):
                continue
            if not 1.05 <= price <= 3.0 or running * price > target * 1.20:
                continue
            gap = abs(log(running * price / target))
            if gap >= current_gap:
                continue
            ranked_choices.append((gap, -float(game.get("selection_probability") or
                                               game.get("confidence") or 0),
                                   event, game, price, team_names))
        if not ranked_choices:
            break
        _, _, event, best, price, names = min(
            ranked_choices, key=lambda x: (x[0], x[1], x[2]))
        used.add(event)
        used_teams.update(names)
        added.append({**best, "supplemental_model_selection": True,
                      "source": "model_qualified_supplement", "editorial_manual": False})
        running *= price
        if running >= target * .90:
            break

    if not added or running < target * .75:
        return None
    all_games = list(remaining) + added
    # One newly validated code for every displayed pick, not an unverified
    # string of selections and never the old publication's shareCode.
    booking = _verified_new_booking(all_games, board)
    if not booking:
        return None
    actual = float(booking["actual_sportybet_odds"])
    if not target * .75 <= actual <= target * 1.20:
        return None
    return {
        "selected": True,
        "source": "separate_model_augmented_option",
        "editorial_manual": False,
        "manual_remainder": False,
        "near_target_alternative": True,
        "official_publication": False,
        "result_scored": False,
        "games": all_games,
        "booking": booking,
        "total_odds": round(actual, 3),
        "target_original_odds": round(target, 3),
        "remaining_original_leg_count": len(remaining),
        "supplemental_leg_count": len(added),
        "presentation": "accumulator",
        "risk_level": "Alternative, not original ticket",
        "reason": "A different ticket combining remaining original selections with separately qualified future fixtures. Original results are unchanged.",
    }

def eligible_manual_remainder(
    record: dict,
    tier: str,
    board: dict,
    *,
    now: datetime,
) -> dict:
    """Pure selection + one booking call for an eligible manual ticket.

    One surviving leg is a separately labelled single, not a replacement
    for the original 2/5/10-odds accumulator. No surviving legs means no code.
    """
    from leagues.booking import _revalidate_games

    original = _manual_original_legs(record)
    if not original:
        return {"selected": False, "reason": "No verified manual publication for this tier."}

    min_remaining = 1
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
    new_booking = _verified_new_booking(verified, board)
    if not new_booking:
        return {
            "selected": False,
            "reason": "A new exact SportyBet code could not be verified.",
            "original_leg_count": len(original),
            "remaining_leg_count": len(verified),
            "removed_leg_count": len(original) - len(verified),
        }

    actual_odds = new_booking["actual_sportybet_odds"]

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
        "presentation": "single" if len(verified) == 1 else "accumulator",
        "single_remainder": len(verified) == 1 and tier != "banker",
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
    near_target: bool = False,
    candidate_games: list[dict] | None = None,
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
    # Admin publications are not stored by the ordinary engine booking job.
    # Read the separate, immutable publication first; old tier bookings are
    # only a compatibility fallback for legacy verified manual data.
    published = {}
    if records is None:
        from leagues.editorial_manual import list_published
        published = list_published(date)

    candidates: dict[str, dict] = {}
    reasons: dict[str, str] = {}
    for tier in _MANUAL_TIERS:
        editorial = (published or {}).get(tier)
        if editorial is not None:
            verified_source = _verified_editorial_source(editorial)
            if verified_source is None:
                reasons[tier] = "The saved manual ticket failed exact booking verification."
                # A contradictory editorial record cannot be replaced by an
                # unrelated automatic booking stored under the same tier key.
                continue
            candidates[tier] = verified_source
            continue

        current_record = (source or {}).get(tier)
        if isinstance(current_record, dict) and _manual_original_legs(current_record):
            candidates[tier] = current_record
            continue
        if records is not None:
            # Explicit fixture-injection tests must not touch the live DB.
            continue
        # Legacy manual editions may survive a newer unavailable booking.
        # Reject engine-only editions, partial readbacks and unnamed sources.
        for edition in reversed(booking_editions_for(date, tier)):
            if isinstance(edition, dict) and _manual_original_legs(edition):
                candidates[tier] = edition
                break
    if not candidates:
        return {"available": False, "tiers": {}, "date": date,
                "official_publication_unchanged": True,
                "record_is_separate": True, "tier_reasons": reasons,
                "reason": "No independently verified manual ticket is available for rebooking."}

    snapshot = board if board is not None else sportybet.fetch_board()
    results: dict[str, dict] = {}
    alternatives: dict[str, dict] = {}
    for tier, record in candidates.items():
        result = eligible_manual_remainder(record, tier, snapshot, now=current)
        if result.get("selected"):
            results[tier] = result
            if near_target and candidate_games:
                # No alternative is manufactured if qualified inventory is
                # absent; the exact reduced ticket still remains available.
                original_source = (published or {}).get(tier) or {}
                variant = _near_target_variant(
                    original_source, result, candidate_games, snapshot, now=current)
                if variant:
                    alternatives[tier] = variant
        else:
            reasons[tier] = result.get("reason") or "No eligible manual selections remain."

    return {
        "available": bool(results),
        "tiers": results,
        "date": date,
        "official_publication_unchanged": True,
        "record_is_separate": True,
        "near_target_alternatives": alternatives,
        "tier_reasons": reasons,
        **({"reason": "No remaining manual selection set passed live bookmaker verification."}
           if not results else {}),
    }
