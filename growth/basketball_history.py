"""Durable, admin-only basketball bookmaker code ledger.

Claim BEFORE any bookmaker POST. Ambiguous network outcomes are retained as
review-required; a retry cannot silently create another SportyBet code.
Only a fully verified code is disclosed by the history API.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _iso():
    return datetime.now(timezone.utc).isoformat()


def fingerprint(selections):
    keys = sorted((str(x.get("eventId", "")), str(x.get("marketId", "")),
                   str(x.get("specifier") or ""), str(x.get("outcomeId", "")))
                  for x in selections)
    return hashlib.sha256(json.dumps(keys, separators=(",", ":")).encode()).hexdigest()


def _ensure(conn):
    from sqlalchemy import text
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS basketball_private_bookings (
            fingerprint VARCHAR(64) PRIMARY KEY,
            share_code VARCHAR(32),
            status VARCHAR(24) NOT NULL,
            target_odds FLOAT NOT NULL,
            verified_odds FLOAT,
            verified_odds_source VARCHAR(64),
            expires_at TEXT,
            legs_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_checked_at TEXT,
            detail TEXT
        )"""))


def _record(row, *, include_sensitive=False):
    result = dict(row)
    result["legs"] = json.loads(result.pop("legs_json") or "[]")
    result["detail"] = json.loads(result.pop("detail") or "{}")
    if not include_sensitive and result["status"] not in {"active", "won", "lost", "void"}:
        result["share_code"] = None
    result["leg_count"] = len(result["legs"])
    return result


def get(fingerprint_value, *, private=False):
    from sqlalchemy import text
    from database import engine
    with engine.begin() as conn:
        _ensure(conn)
        row = conn.execute(text(
            "SELECT * FROM basketball_private_bookings WHERE fingerprint=:f"
        ), {"f": fingerprint_value}).mappings().first()
    return _record(row, include_sensitive=private) if row else None


def claim(selections, matched_legs, target_odds, snapshot_id):
    """Database uniqueness is the idempotency gate for uncertain requests."""
    from sqlalchemy import text
    from database import engine
    fp = fingerprint(selections)
    now = _iso()
    data = json.dumps([dict(leg, result="pending", score=None, score_source=None)
                       for leg in matched_legs], separators=(",", ":"))
    detail = json.dumps({"snapshot_id": snapshot_id, "ticket_status": "pending",
                         "odds_source": None, "booking_status": "creating"})
    with engine.begin() as conn:
        _ensure(conn)
        result = conn.execute(text("""
            INSERT INTO basketball_private_bookings
              (fingerprint, status, target_odds, legs_json, detail, created_at, updated_at)
            VALUES (:f, 'creating', :target, :legs, :detail, :now, :now)
            ON CONFLICT (fingerprint) DO NOTHING
        """), {"f": fp, "target": target_odds, "legs": data,
               "detail": detail, "now": now})
        won = result.rowcount == 1
        row = conn.execute(text(
            "SELECT * FROM basketball_private_bookings WHERE fingerprint=:f"
        ), {"f": fp}).mappings().first()
    return won, _record(row)


def mark(fingerprint_value, *, status, share_code=None,
         verified_odds=None, odds_source=None, expires_at=None,
         detail_update=None):
    """No unverified code is shown to the browser, but it is retained privately."""
    from sqlalchemy import text
    from database import engine
    with engine.begin() as conn:
        _ensure(conn)
        row = conn.execute(text(
            "SELECT detail FROM basketball_private_bookings WHERE fingerprint=:f"
        ), {"f": fingerprint_value}).first()
        if row is None:
            raise RuntimeError("Basketball booking intent not found.")
        detail = json.loads(row[0] or "{}")
        detail.update(detail_update or {})
        detail["booking_status"] = status
        conn.execute(text("""
            UPDATE basketball_private_bookings SET status=:s,
              share_code=COALESCE(:code, share_code),
              verified_odds=COALESCE(:odds, verified_odds),
              verified_odds_source=COALESCE(:source, verified_odds_source),
              expires_at=COALESCE(:expiry, expires_at),
              detail=:detail, updated_at=:now
            WHERE fingerprint=:f
        """), {"f": fingerprint_value, "s": status, "code": share_code,
               "odds": verified_odds, "source": odds_source, "expiry": expires_at,
               "detail": json.dumps(detail), "now": _iso()})


def list_recent(limit=30):
    from sqlalchemy import text
    from database import engine
    limit = max(1, min(100, int(limit)))
    with engine.begin() as conn:
        _ensure(conn)
        rows = conn.execute(text(
            "SELECT * FROM basketball_private_bookings ORDER BY created_at DESC LIMIT :limit"
        ), {"limit": limit}).mappings().all()
    items = [_record(row) for row in rows]
    return {"status": "success", "tickets": items,
            "count": len(items), "source": "persistent_database"}


def update_results(fingerprint_value, revised_legs, checked_at, summary):
    """Preserve all already-verified final leg results; refuse to update failures."""
    from sqlalchemy import text
    from database import engine
    with engine.begin() as conn:
        _ensure(conn)
        row = conn.execute(text("""
            SELECT status, legs_json, detail FROM basketball_private_bookings
            WHERE fingerprint=:f
        """), {"f": fingerprint_value}).mappings().first()
        if row is None or row["status"] not in {"active", "won", "lost", "void"}:
            return
        existing = json.loads(row["legs_json"])
        if len(existing) != len(revised_legs):
            raise ValueError("Cannot change stored ticket leg count.")
        for old, new in zip(existing, revised_legs):
            if (old["event_id"], old["market_id"], old["outcome_id"], old["specifier"]) != (
                    new["event_id"], new["market_id"], new["outcome_id"], new["specifier"]):
                raise ValueError("Cannot replace a stored bookmaker selection.")
            if old.get("result") in {"won", "lost", "void"} and new.get("result") != old["result"]:
                raise ValueError("Final basketball result cannot be silently overwritten.")
        detail = json.loads(row["detail"] or "{}")
        detail["ticket_status"] = summary
        conn.execute(text("""
            UPDATE basketball_private_bookings SET
              status=:status, legs_json=:legs, detail=:detail,
              last_checked_at=:checked, updated_at=:now
            WHERE fingerprint=:f
        """), {"f": fingerprint_value, "status": (
                   summary if summary in {"won", "lost", "void"} else "active"),
               "legs": json.dumps(revised_legs), "detail": json.dumps(detail),
               "checked": checked_at, "now": _iso()})
