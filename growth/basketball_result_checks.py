"""Private, capped receipts for NBA basketball bookmaker-code result checks.

An HTTP 200 from a scheduler is not evidence of a verified final. Each
scheduled evaluation stores a bounded operational receipt, not personal data,
tickets, betting codes, scores or model/prediction modifications.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text

MAX_EVENTS = 96
MAX_AGE_MINUTES = 35


def _ensure(conn):
    primary_key = ("BIGSERIAL PRIMARY KEY" if conn.dialect.name=="postgresql"
                   else "INTEGER PRIMARY KEY AUTOINCREMENT")
    conn.execute(text("""
      CREATE TABLE IF NOT EXISTS basketball_private_result_checks (
        id """ + primary_key + """,
        checked_at TIMESTAMPTZ NOT NULL,
        state VARCHAR(32) NOT NULL,
        tickets_updated INTEGER NOT NULL,
        final_legs INTEGER NOT NULL,
        issue VARCHAR(80)
      )
    """))


def record(result: dict, *, engine=None, now=None):
    if engine is None:
        from database import engine as live_engine
        engine = live_engine
    status = result.get("status")
    count = result.get("nba_final_legs", 0)
    updated = result.get("tickets_updated", 0)
    if status not in ("success", "unavailable") or (
        type(count) is not int or type(updated) is not int or
        count < 0 or updated < 0 or count > 1000 or updated > 1000
    ):
        raise ValueError("BASKETBALL_RESULT_RECEIPT_INVALID")
    issue = str(result.get("reason") or "")[:80] or None
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("BASKETBALL_RESULT_RECEIPT_TIME_UNVERIFIED")
    with engine.begin() as conn:
        _ensure(conn)
        conn.execute(text("""
          INSERT INTO basketball_private_result_checks
            (checked_at, state, tickets_updated, final_legs, issue)
          VALUES (:checked, :state, :updated, :legs, :issue)
        """), {"checked":timestamp,"state":status,"updated":updated,
               "legs":count,"issue":issue})
        conn.execute(text("""
          DELETE FROM basketball_private_result_checks
          WHERE id NOT IN (
            SELECT id FROM basketball_private_result_checks
            ORDER BY id DESC LIMIT :limit
          )
        """), {"limit":MAX_EVENTS})


def snapshot(*, engine=None, now=None):
    if engine is None:
        from database import engine as live_engine
        engine = live_engine
    instant = now or datetime.now(timezone.utc)
    try:
      with engine.connect() as conn:
        rows = conn.execute(text("""
          SELECT checked_at, state, tickets_updated, final_legs, issue
          FROM basketball_private_result_checks
          ORDER BY id DESC LIMIT 12
        """)).mappings().all()
    except Exception:
      return {"status":"not_observed","state":"not_observed",
              "last_checked_at":None,"recent_checks":0,
              "verified_final_legs":0,"tickets_updated":0}
    if not rows:
        return {"status":"not_observed","state":"not_observed",
                "last_checked_at":None,"recent_checks":0,
                "verified_final_legs":0,"tickets_updated":0}
    latest = rows[0]
    last = latest["checked_at"]
    if isinstance(last, str):
        last = datetime.fromisoformat(last.replace("Z", "+00:00"))
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    minutes = max(0, (instant-last.astimezone(timezone.utc)).total_seconds()/60)
    state = ("stale" if minutes > MAX_AGE_MINUTES else
             "degraded" if latest["state"]!="success" else "observed")
    return {"status":"success","state":state,
            "last_checked_at":last.isoformat(),
            "last_status":latest["state"],
            "age_minutes":round(minutes,1),
            "recent_checks":len(rows),
            "verified_final_legs":sum(r["final_legs"] for r in rows),
            "tickets_updated":sum(r["tickets_updated"] for r in rows),
            "last_issue":latest["issue"],
            "note":"A successful empty cycle is not evidence that a game finished. Only verified finals count."}
