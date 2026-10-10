"""Transactional, fill-only recovery for an empty published daily tier.

This is intentionally separate from normal publication.  It never rewrites a
selected tier and it only promotes a candidate which has already passed the
prepared-board selector and exact SportyBet readback.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from math import prod

from sqlalchemy import text
from sqlalchemy.orm import Session

from database import engine
from leagues.booking import leg_fingerprint
from leagues.picks_db import DailyCard, PublishedSlip
from leagues.policy_version import PUBLISHED_SELECTION_POLICY_VERSION

logger = logging.getLogger(__name__)
_RECOVERY_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_RECOVERY_LOCKS_GUARD = threading.Lock()


def _lock_for(publish_date: str, tier: str) -> threading.Lock:
    """Serialize same-process recovery attempts before the database lock."""
    with _RECOVERY_LOCKS_GUARD:
        return _RECOVERY_LOCKS.setdefault((publish_date, tier), threading.Lock())


def _selected(data: object) -> bool:
    return isinstance(data, dict) and bool(data.get("selected") and data.get("games"))


RECOVERABLE_TIERS = frozenset({"banker", "2_odds", "5_odds", "10_odds"})


def _validate_candidate(tier: str, candidate: dict, booking: dict) -> None:
    """Fail closed even when a repair endpoint calls this function directly."""
    from leagues.availability import all_games_actionable
    from leagues.publication_policy import evaluate_slip

    if tier not in RECOVERABLE_TIERS:
        raise ValueError("tier is not eligible for automatic recovery")
    games = candidate.get("games") or []
    if not games or not all_games_actionable(games):
        raise ValueError("every recovery fixture must be safely before kickoff")
    fixture_ids = [str(game.get("match_id") or "") for game in games]
    if not all(fixture_ids) or len(fixture_ids) != len(set(fixture_ids)):
        raise ValueError("recovery must use unique identified fixtures")
    policy = evaluate_slip(games, tier)
    if not policy["allowed"]:
        raise ValueError("official publication policy rejected recovery: "
                         + ",".join(policy["reasons"]))

    if not (booking.get("status") == "active"
            and booking.get("booking_status") in {"FULL", "REBUILT_FULL"}
            and booking.get("readback_validation") == "PASSED"
            and booking.get("share_code")):
        raise ValueError("exact SportyBet booking/readback is required")
    if (int(booking.get("booked_leg_count") or 0) != len(games)
            or int(booking.get("excluded_leg_count") or 0) != 0
            or int(booking.get("replacement_count") or 0) != 0):
        raise ValueError("booked leg count or replacements differ from recovery")
    booked_games = booking.get("final_booked_legs")
    if (not isinstance(booked_games, list)
            or leg_fingerprint(booked_games) != leg_fingerprint(games)):
        raise ValueError("SportyBet readback legs differ from the published recovery")

    try:
        actual = float(booking.get("actual_sportybet_odds") or 0)
        selected = prod(float(game.get("odds") or 0) for game in games)
    except (TypeError, ValueError):
        raise ValueError("recovery price is invalid") from None
    # Never turn a genuine 10 Odds publication into a cheaper 9x ticket.
    # The other product bands follow the same existing selector floor.
    lower = {"banker": 1.0, "2_odds": 1.84,
             "5_odds": 4.0, "10_odds": 10.0}[tier]
    if actual < lower or actual < selected * 0.98:
        raise ValueError("SportyBet readback odds are below the allowed price")
    if tier == "10_odds" and len(games) > 20:
        raise ValueError("10 Odds recovery exceeds the 20-leg cap")



def _ensure_provenance_table(conn) -> None:
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS tier_recovery_provenance ("
        "publish_date VARCHAR(10) NOT NULL, "
        "tier VARCHAR(24) NOT NULL, "
        "created_at VARCHAR(32) NOT NULL, "
        "snapshot_id VARCHAR(64), "
        "detail TEXT NOT NULL, "
        "PRIMARY KEY (publish_date, tier)"
        ")"
    ))


def _store_booking(conn, publish_date: str, tier: str, record: dict) -> None:
    from leagues.booking import _ensure_table
    _ensure_table(conn)
    conn.execute(text(
        "INSERT INTO tier_bookings (publish_date,tier,share_code,share_url,legs,status,detail,created_at,booking_status,original_leg_count,booked_leg_count,excluded_leg_count,replacement_count,predicted_odds,actual_sportybet_odds,board_snapshot_id) "
        "VALUES (:d,:t,:c,:u,:l,:s,:detail,:at,:bs,:ol,:bl,:el,:rc,:po,:ao,:snap)"), {
            "d": publish_date, "t": tier, "c": record.get("share_code"),
            "u": record.get("share_url"), "l": record.get("legs") or 0,
            "s": record.get("status", "failed"), "detail": json.dumps(record),
            "at": datetime.now(timezone.utc).isoformat(),
            "bs": record.get("booking_status"),
            "ol": record.get("original_leg_count"), "bl": record.get("booked_leg_count"),
            "el": record.get("excluded_leg_count"), "rc": record.get("replacement_count"),
            "po": record.get("predicted_tier_odds"), "ao": record.get("actual_sportybet_odds"),
            "snap": record.get("board_snapshot_id"),
        })


def recover_empty_tier(*, publish_date: str, tier: str, candidate: dict,
                       booking: dict, decision_snapshot_id: str | None = None) -> dict:
    """Atomically add one exact-bookable candidate to a genuinely empty tier.

    Booking is deliberately obtained and read back before this function is
    called.  No database-visible recovery state is committed unless the card,
    archived slip, tier booking and recovery provenance all succeed together.
    """
    if not _selected(candidate):
        return {"status": "UNREACHABLE", "best_reachable": candidate.get("best_reachable"),
                "reason": candidate.get("reason")}
    try:
        _validate_candidate(tier, candidate, booking)
    except ValueError as exc:
        return {"status": "BLOCKED", "reason": str(exc)}
    games = list(candidate.get("games") or [])

    # The row lock below covers multiple workers; this small local lock avoids
    # SQLite and single-process deployments producing a lock-timeout instead
    # of the useful idempotent ALREADY_FILLED result.
    with _lock_for(publish_date, tier):
        try:
            with engine.begin() as conn:
                _ensure_provenance_table(conn)
                session = Session(bind=conn)
                try:
                    card = (session.query(DailyCard)
                            .filter(DailyCard.publish_date == publish_date)
                            .with_for_update().first())
                    if not card:
                        return {"status": "NO_CARD"}
                    payload = json.loads(card.payload or "{}")
                    # Another repair or the morning run can reserve fixtures
                    # while the bookmaker request is in flight. Recheck after
                    # taking the card's row lock, not only during selection.
                    claimed = {
                        str(game.get("match_id"))
                        for name, value in payload.items()
                        if name != tier and isinstance(value, dict)
                        and value.get("selected")
                        for game in (value.get("games") or [])
                        if game.get("match_id")
                    }
                    if claimed.intersection(
                        str(game.get("match_id")) for game in games
                    ):
                        return {"status": "FIXTURE_CONFLICT",
                                "reason": "a fixture is already published on another tier"}
                    current = payload.get(tier)
                    if _selected(current):
                        return {"status": "ALREADY_FILLED"}
                    fingerprints = {
                        name: leg_fingerprint(value.get("games") or [])
                        for name, value in payload.items() if _selected(value)
                    }
                    fingerprint = leg_fingerprint(games)
                    existing = (session.query(PublishedSlip)
                                .filter(PublishedSlip.date == publish_date,
                                        PublishedSlip.category == tier).first())
                    if existing:
                        return {"status": "ALREADY_FILLED"}
                    session.add(PublishedSlip(
                        date=publish_date, category=tier, picks=json.dumps(games),
                        total_odds=round(float(booking["actual_sportybet_odds"]), 2),
                        hit_probability=float(candidate.get("hit_probability") or 0),
                        presentation=candidate.get("presentation", "accumulator"),
                        policy_version=PUBLISHED_SELECTION_POLICY_VERSION,
                        selection_fingerprint=fingerprint, status="pending",
                    ))
                    session.flush()
                    _store_booking(conn, publish_date, tier, booking)
                    conn.execute(text(
                        "INSERT INTO tier_recovery_provenance (publish_date,tier,created_at,snapshot_id,detail) VALUES (:d,:t,:at,:snap,:detail)"),
                        {"d": publish_date, "t": tier,
                         "at": datetime.now(timezone.utc).isoformat(), "snap": decision_snapshot_id,
                         "detail": json.dumps({"candidate": candidate, "booking": booking,
                                               "existing_tier_fingerprints": fingerprints})})
                    candidate = {**candidate,
                                 "total_odds": round(
                                     float(booking["actual_sportybet_odds"]), 2),
                                 "result_status": "SAME_DAY_RECOVERED",
                                 "recovered_at": datetime.now(timezone.utc).isoformat()}
                    payload[tier] = candidate
                    payload["_card_revision"] = int(payload.get("_card_revision", 1)) + 1
                    payload["_last_updated_at"] = datetime.now(timezone.utc).isoformat()
                    card.payload = json.dumps(payload)
                    session.flush()
                    return {"status": "RECOVERED", "tier": tier,
                            "selection_fingerprint": fingerprint}
                finally:
                    session.close()
        except Exception as exc:
            logger.warning("empty tier recovery rolled back %s/%s: %s", publish_date, tier, exc)
            return {"status": "FAILED", "reason": type(exc).__name__}
