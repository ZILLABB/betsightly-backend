"""Worker-owned, versioned Available Now editions (opt-in rollout).

Public GET only reads these snapshots. They never overwrite published cards,
settlement records, or the morning booking editions. An expired snapshot is
unavailable, not permission for a web worker to fetch or create a new code.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from leagues.availability import BOOKING_BUFFER, parse_kickoff

logger = logging.getLogger(__name__)
MAX_AGE = timedelta(minutes=13)


def enabled() -> bool:
    return os.getenv("BETSIGHTLY_LIVE_REFILL_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _wat_date(now: datetime) -> str:
    return (now.astimezone(timezone.utc) + timedelta(hours=1)).date().isoformat()


def _ensure(conn) -> None:
    from sqlalchemy import text
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS live_bookable_editions ("
        "wat_date VARCHAR(10) NOT NULL, revision INTEGER NOT NULL,"
        "fingerprint VARCHAR(64) NOT NULL,"
        "created_at VARCHAR(40) NOT NULL, expires_at VARCHAR(40) NOT NULL,"
        "payload TEXT NOT NULL,"
        "PRIMARY KEY (wat_date, revision))"
    ))


def _fingerprint(card: dict) -> str:
    identity = []
    for tier, data in sorted((card.get("accumulators") or {}).items()):
        if not isinstance(data, dict):
            continue
        code = (data.get("booking") or {}).get("share_code")
        legs = sorted((
            str(g.get("match_id") or ""),
            str(g.get("market") or g.get("market_key") or ""),
            str(g.get("prediction") or ""),
            str(g.get("odds") or ""),
        ) for g in (data.get("games") or []))
        identity.append((tier, bool(data.get("selected")), code, legs))
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def _expiry(card: dict, now: datetime) -> datetime:
    expiry = now + MAX_AGE
    for category in (card.get("accumulators") or {}).values():
        if not isinstance(category, dict) or not category.get("selected"):
            continue
        for game in category.get("games") or []:
            kickoff = parse_kickoff(game.get("kickoff") or game.get("date"))
            if kickoff:
                expiry = min(expiry, kickoff - BOOKING_BUFFER)
    return expiry


def save(card: dict, now: datetime | None = None) -> dict:
    from sqlalchemy import text
    from database import engine
    current = now or datetime.now(timezone.utc)
    wat_date = _wat_date(current)
    expiry = _expiry(card, current)
    if expiry <= current:
        return {"status": "expired_during_generation", "stored": False}
    fp = _fingerprint(card)
    raw = json.dumps(card, default=str, sort_keys=True)
    with engine.begin() as conn:
        _ensure(conn)
        row = conn.execute(text(
            "SELECT revision, fingerprint FROM live_bookable_editions "
            "WHERE wat_date=:d ORDER BY revision DESC LIMIT 1"
        ), {"d": wat_date}).first()
        if row is not None and row[1] == fp:
            revision = int(row[0])
            conn.execute(text(
                "UPDATE live_bookable_editions SET expires_at=:expiry, payload=:payload "
                "WHERE wat_date=:d AND revision=:revision"
            ), {"expiry": expiry.isoformat(), "payload": raw,
                "d": wat_date, "revision": revision})
            change = "refreshed"
        else:
            revision = int(row[0]) + 1 if row else 1
            conn.execute(text(
                "INSERT INTO live_bookable_editions "
                "(wat_date, revision, fingerprint, created_at, expires_at, payload) "
                "VALUES (:d,:revision,:fp,:created,:expiry,:payload)"
            ), {"d": wat_date, "revision": revision, "fp": fp,
                "created": current.isoformat(), "expiry": expiry.isoformat(),
                "payload": raw})
            change = "new_revision"
    return {"status": change, "stored": True, "revision": revision,
            "wat_date": wat_date, "expires_at": expiry.isoformat()}


def load(now: datetime | None = None) -> dict:
    from sqlalchemy import text
    from database import engine
    current = now or datetime.now(timezone.utc)
    date = _wat_date(current)
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT revision, created_at, expires_at, payload "
                "FROM live_bookable_editions WHERE wat_date=:d "
                "ORDER BY revision DESC LIMIT 1"
            ), {"d": date}).first()
    except Exception as exc:
        logger.warning("read-only live snapshot unavailable: %s", type(exc).__name__)
        return {"status": "success", "available": False, "date": date,
                "reason": "Rolling ticket storage not initialized."}
    if not row:
        return {"status": "success", "available": False, "date": date,
                "reason": "No prevalidated rolling ticket edition is ready yet."}
    revision, created, expires, raw = row
    expiry = datetime.fromisoformat(expires)
    if expiry <= current:
        return {"status": "success", "available": False, "date": date,
                "revision": revision, "reason": "Rolling ticket edition expired; next validated refresh pending."}
    card = json.loads(raw)
    # An upstream clock or provider anomaly must not serve already-started legs.
    for category in (card.get("accumulators") or {}).values():
        if not isinstance(category, dict) or not category.get("selected"):
            continue
        if any((kickoff := parse_kickoff(g.get("kickoff") or g.get("date"))) is None
               or kickoff - BOOKING_BUFFER <= current
               for g in category.get("games") or []):
            return {"status": "success", "available": False, "date": date,
                    "revision": revision, "reason": "A stored ticket reached its kickoff buffer."}
    card.update(
        live_revision=revision, live_revision_created_at=created,
        live_revision_expires_at=expires,
        prevalidated_booking_edition=True,
        published_record_unchanged=True,
    )
    return card


def refresh() -> dict:
    """Run on the sole background scheduler process, never from a GET."""
    if not enabled():
        return {"status": "disabled"}
    from leagues.engine import prepared_board
    from leagues.daily_feed import build_bookable_now
    picks, _, board = prepared_board(days_ahead=2)
    if not board.get("ready") or board.get("stale"):
        return {"status": "board_unavailable"}
    now = datetime.now(timezone.utc)
    card = build_bookable_now(all_picks=picks, now=now)
    if not card:
        card = {"status": "success", "available": False,
                "date": _wat_date(now), "accumulators": {}}
    return save(card, now)
