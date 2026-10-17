"""Scheduled, fail-closed late Rollover recovery after verified settlement.

The 08:00 card is immutable, but yesterday's manual Rollover may not settle
until after today's publication job. Existing recovery handles ordinary tiers
only. This worker-only helper can start a *new* rollover day, strictly when
the persisted chain state allows it; it does not rewrite archived tickets or
relax risk/market or bookmaker validation rules.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


def recover_once(*, at: datetime | None = None) -> dict:
    """Attempt a safe new day from an evaluated board; called only by scheduler."""
    from leagues import daily_feed as feed
    from leagues.rollover_db import load_chain
    from leagues.rollover_lifecycle import chain_state

    now = at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        return {"status": "INVALID_CLOCK"}
    now = now.astimezone(timezone.utc)
    if feed._wat_now(now).hour < feed.PUBLISH_HOUR_WAT:
        return {"status": "BEFORE_PUBLICATION"}
    day = feed._publish_date()
    if day != feed._wat_now(now).date().isoformat():
        return {"status": "PUBLICATION_DATE_MISMATCH"}

    # Never rebuild, reprice or change today's already-published model card.
    locked = feed._load_locked(day)
    if not locked:
        return {"status": "NO_PUBLISHED_CARD", "date": day}

    previous = load_chain(day)
    decision = chain_state(previous.get("days") or [], day, feed.TARGET_DAYS)
    if not decision["can_generate"]:
        return {"status": "CHAIN_BLOCKED", "date": day,
                "reason": decision["status"]}
    # Other concurrent scheduler workers race safely at append_day(), whose
    # DB advisory lock guards a single WAT date across all active chains.

    from leagues.engine import (
        prepared_board_status, prepared_pipeline, kickoff_wat_date,
    )
    board = prepared_board_status(days_ahead=7)
    if not board.get("ready") or board.get("age_seconds", 999999) > 6 * 3600:
        return {"status": "PREPARED_BOARD_UNAVAILABLE", "date": day}

    picks, _ = prepared_pipeline(days_ahead=7)
    from leagues.booking import bookings_for
    from leagues.availability import parse_kickoff
    from leagues.fixture_ranker import canonical_fixture_recommendations

    reserved_fixtures: set[str] = set()
    reserved_teams: set[str] = set()
    for category in (locked or {}).values():
        if not isinstance(category, dict):
            continue
        for fixture in category.get("games") or []:
            if not isinstance(fixture, dict):
                continue
            if fixture.get("match_id"):
                reserved_fixtures.add(str(fixture["match_id"]))
            for key in ("home_team", "away_team"):
                label = str(fixture.get(key) or "").strip().casefold()
                if label:
                    reserved_teams.add(label)
    for booked in bookings_for(day).values():
        for fixture in (booked.get("final_booked_legs") or []):
            if fixture.get("match_id"):
                reserved_fixtures.add(str(fixture["match_id"]))
            for key in ("home_team", "away_team"):
                label = str(fixture.get(key) or "").strip().casefold()
                if label:
                    reserved_teams.add(label)

    cutoff = now + feed.BOOKING_BUFFER
    eligible = []
    for pick in picks:
        if not isinstance(pick, dict) or not isinstance(pick.get("_fixture"), dict):
            continue
        fixture = pick["_fixture"]
        kickoff = parse_kickoff(fixture.get("commence_time"))
        if (not kickoff or kickoff <= cutoff
                or kickoff_wat_date(fixture.get("commence_time")) != day
                or str(pick.get("match_id") or "") in reserved_fixtures
                or feed._pick_teams(pick) & reserved_teams
                or not pick.get("bookable")
                or not pick.get("safe_tier_eligible")):
            continue
        eligible.append(pick)

    if not eligible:
        return {"status": "NO_SAFE_BOOKABLE_PICKS", "date": day}
    ranked = canonical_fixture_recommendations(
        eligible, include_all_eligible=True,
    )
    source, _ = feed.filter_official_candidates(ranked, "rollover")
    if not source:
        return {"status": "PUBLICATION_POLICY_BLOCKED", "date": day}
    # Uses the canonical 2–4x selection and append_day advisory lock:
    # no next stage after pending, no duplicate WAT-day, no forced odds.
    created = feed._build_rollover(source, day)
    if not created.get("selected") or not created.get("games"):
        return {"status": "NO_QUALIFYING_ROLLOVER", "date": day,
                "reason": created.get("reason")}

    from leagues.booking import book_card
    booking = book_card(day, {"rollover": created})
    # Never show a stale, pre-settlement roll-over card for another 15 min.
    feed._accum_cache.update({"result": None, "ts": 0})
    logger.info("Late rollover recovery published a new stage for %s", day)
    return {"status": "PUBLISHED", "date": day,
            "day_number": (created.get("chain") or [{}])[-1].get("day_number"),
            "games": len(created["games"]),
            "booking_created": bool(booking.get("booked")),
            "booking_failures": booking.get("failed") or []}
