"""Bounded, scheduler-owned same-day recovery of empty published tiers.

Each WAT hour is claimed in PostgreSQL before any SportyBet request. A deploy,
restart or competing scheduler cannot silently create duplicate bookings.
No web GET, public request or daily publication rerun can enter this path.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

logger = logging.getLogger(__name__)
WAT = timezone(timedelta(hours=1))
REFILL_TIERS = ("banker", "2_odds", "5_odds", "10_odds")


def refill_enabled() -> bool:
    environment = os.getenv("ENVIRONMENT", "development").strip().lower()
    default = "true" if environment in {"production", "prod"} else "false"
    enabled = os.getenv("BETSIGHTLY_SAME_DAY_REFILL_ENABLED", default)
    if enabled.strip().lower() not in {"true", "1", "yes", "on"}:
        return False
    # A public web process is never allowed to own a bookmaker-writing timer.
    from utils.process_roles import resolve_process_role, role_ownership
    background_enabled = os.getenv(
        "ENABLE_BACKGROUND_JOBS", "true"
    ).strip().lower() in {"true", "1", "yes", "on"}
    role = resolve_process_role(
        background_enabled, os.getenv("BETSIGHTLY_PROCESS_ROLE", "")
    )
    return bool(role_ownership(role, background_enabled)["scheduler"])


def _claim_hour(engine, key: str, day: str, now: datetime) -> bool:
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS same_day_refill_attempts ("
            "window_key VARCHAR(16) PRIMARY KEY,"
            "publish_date VARCHAR(10) NOT NULL,"
            "started_at VARCHAR(36) NOT NULL,"
            "finished_at VARCHAR(36),"
            "status VARCHAR(24),"
            "result TEXT)"
        ))
        result = conn.execute(text(
            "INSERT INTO same_day_refill_attempts"
            "(window_key,publish_date,started_at,status)"
            " VALUES (:w,:d,:t,'running')"
            " ON CONFLICT (window_key) DO NOTHING"
        ), {"w": key, "d": day, "t": now.isoformat()})
        return result.rowcount == 1


def _finish_hour(engine, key: str, status: str, report: dict) -> None:
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE same_day_refill_attempts"
            " SET status=:s,finished_at=:t,result=:r WHERE window_key=:w"
        ), {"w": key, "s": status,
            "t": datetime.now(timezone.utc).isoformat(),
            "r": json.dumps(report, default=str)[:6000]})


def run_if_due(now: datetime | None = None) -> dict:
    """Attempt missing official tiers at most once per WAT hour after 09:00."""
    if not refill_enabled():
        return {"status": "DISABLED"}
    now = now or datetime.now(timezone.utc)
    wat = now.astimezone(WAT)
    # Keep the pre-publication run and the late-night closeout undisturbed.
    if not (9 <= wat.hour < 22):
        return {"status": "OUTSIDE_WINDOW"}

    from leagues.daily_feed import _load_locked
    day = wat.date().isoformat()
    card = _load_locked(day)
    if not card:
        return {"status": "NO_LOCKED_CARD", "date": day}
    missing = [
        tier for tier in REFILL_TIERS
        if not (isinstance(card.get(tier), dict)
                and card[tier].get("selected") and card[tier].get("games"))
    ]
    if not missing:
        return {"status": "ALL_FILLED", "date": day}

    from database import engine
    key = wat.strftime("%Y-%m-%dT%H")
    if not _claim_hour(engine, key, day, now):
        return {"status": "ALREADY_ATTEMPTED", "date": day}

    try:
        from leagues.daily_feed import recover_today_empty_tiers
        result = recover_today_empty_tiers()
        tiers = result.get("tiers") or {}
        outcome = {
            "status": result.get("status"),
            "date": day, "attempted": missing,
            "recovered": [
                tier for tier, detail in tiers.items()
                if detail.get("status") == "RECOVERED"
            ],
            "tier_statuses": {
                tier: detail.get("status") for tier, detail in tiers.items()
            },
        }
        if result.get("status") == "BOARD_UNAVAILABLE":
            # The board must refresh in scheduler/background ownership only;
            # never block the daily loop or perform provider work in a GET.
            status = result.get("board") or {}
            if status.get("stale") or not status.get("ready"):
                try:
                    from leagues.engine import start_prepared_board_refresh
                    outcome["refresh_started"] = bool(
                        start_prepared_board_refresh(
                            days_ahead=7, force=True, request_triggered=False
                        )
                    )
                except Exception as exc:
                    logger.warning("same-day board refresh failed: %s", exc)
        _finish_hour(engine, key, "complete", outcome)
        if outcome["recovered"]:
            # Invalidate only this worker's in-process cache; other web
            # processes will observe the persisted card after their TTL.
            from leagues.daily_feed import _accum_cache
            _accum_cache.update({"result": None, "ts": 0})
        logger.info("same-day tier refill date=%s recovered=%s status=%s",
                    day, outcome["recovered"], outcome["status"])
        return outcome
    except Exception as exc:
        _finish_hour(engine, key, "failed", {"error": type(exc).__name__})
        logger.exception("same-day tier refill crashed")
        return {"status": "FAILED", "reason": type(exc).__name__, "date": day}
