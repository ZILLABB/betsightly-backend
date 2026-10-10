"""Central API-Football quota and request gateway."""

import json
import logging
import os
import threading
from datetime import datetime, timezone

import requests
from sqlalchemy import Boolean, Column, DateTime, Integer, String

from database import Base, SessionLocal, engine

logger = logging.getLogger(__name__)

BASE_URL = "https://v3.football.api-sports.io"

_TABLE_LOCK = threading.Lock()
_TABLE_READY = False


class APIFootballQuota(Base):
    __tablename__ = "api_football_quota"

    usage_date = Column(String(10), primary_key=True)
    used = Column(Integer, nullable=False, default=0)
    minute_bucket = Column(String(16), nullable=False, default="")
    minute_used = Column(Integer, nullable=False, default=0)

    provider_daily_remaining = Column(Integer, nullable=True)
    provider_minute_remaining = Column(Integer, nullable=True)

    blocked = Column(Boolean, nullable=False, default=False)
    block_reason = Column(String(120), nullable=True)

    last_request_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False)


def _bounded_int(name, default, minimum, maximum):
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default

    return max(
        minimum,
        min(maximum, value),
    )


def daily_budget():
    # Provider ceiling is 100/day.
    return _bounded_int(
        "API_FOOTBALL_DAILY_BUDGET",
        90,
        1,
        99,
    )


def minute_budget():
    # Provider ceiling is 10/minute.
    return _bounded_int(
        "API_FOOTBALL_MINUTE_BUDGET",
        8,
        1,
        9,
    )


def provider_reserve():
    return _bounded_int(
        "API_FOOTBALL_PROVIDER_RESERVE",
        10,
        1,
        99,
    )


def api_football_key():
    """Canonical name plus temporary compatibility aliases."""
    return (
        os.getenv("API_FOOTBALL_API_KEY")
        or os.getenv("APIFOOTBALL_API_KEY")
        or os.getenv("API_FOOTBALL_KEY")
        or ""
    ).strip()


def process_role():
    environment = os.getenv(
        "ENVIRONMENT",
        "development",
    ).strip().lower()

    default_background = (
        "true"
        if environment in {"production", "prod"}
        else "false"
    )

    background = os.getenv(
        "ENABLE_BACKGROUND_JOBS",
        default_background,
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    role = os.getenv(
        "BETSIGHTLY_PROCESS_ROLE",
        "",
    ).strip().lower()

    if role:
        return role

    return (
        "all"
        if background
        else "web"
    )


def deployed_role_allows_provider():
    """A deployed web process may never spend provider quota."""
    environment = os.getenv(
        "ENVIRONMENT",
        "development",
    ).strip().lower()

    if environment not in {
        "production",
        "prod",
        "staging",
    }:
        return True

    return process_role() in {
        "scheduler",
        "all",
    }


def ensure_table():
    global _TABLE_READY

    if _TABLE_READY:
        return

    with _TABLE_LOCK:
        if _TABLE_READY:
            return

        Base.metadata.create_all(
            bind=engine,
            tables=[
                APIFootballQuota.__table__
            ],
        )

        _TABLE_READY = True


def _utc_now():
    return datetime.now(timezone.utc)


def _row_for_update(db, current):
    day = current.date().isoformat()

    row = (
        db.query(APIFootballQuota)
        .filter(
            APIFootballQuota.usage_date
            == day
        )
        .with_for_update()
        .one_or_none()
    )

    if row is None:
        row = APIFootballQuota(
            usage_date=day,
            used=0,
            minute_bucket="",
            minute_used=0,
            blocked=False,
            updated_at=current,
        )

        db.add(row)
        db.flush()

    return row


def reserve_request(now=None):
    """Reserve one call before touching API-Football."""
    if not deployed_role_allows_provider():
        return (
            False,
            "provider_disabled_for_process_role",
        )

    ensure_table()

    current = now or _utc_now()
    minute = current.strftime(
        "%Y-%m-%dT%H:%M"
    )

    db = SessionLocal()

    try:
        row = _row_for_update(
            db,
            current,
        )

        if row.minute_bucket != minute:
            row.minute_bucket = minute
            row.minute_used = 0

        if row.blocked:
            db.commit()

            return (
                False,
                row.block_reason
                or "provider_blocked",
            )

        if (
            row.provider_daily_remaining
            is not None
            and row.provider_daily_remaining
            <= provider_reserve()
        ):
            row.blocked = True
            row.block_reason = (
                "provider_daily_reserve_reached"
            )
            row.updated_at = current

            db.commit()

            return (
                False,
                row.block_reason,
            )

        if row.used >= daily_budget():
            row.blocked = True
            row.block_reason = (
                "local_daily_budget_reached"
            )
            row.updated_at = current

            db.commit()

            return (
                False,
                row.block_reason,
            )

        if row.minute_used >= minute_budget():
            db.commit()

            return (
                False,
                "local_minute_budget_reached",
            )

        row.used += 1
        row.minute_used += 1
        row.last_request_at = current
        row.updated_at = current

        db.commit()

        return (
            True,
            "reserved",
        )

    except Exception:
        db.rollback()

        logger.exception(
            "API-Football quota reservation "
            "failed closed"
        )

        return (
            False,
            "quota_store_error",
        )

    finally:
        db.close()


def _header_int(headers, name):
    value = headers.get(name)

    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def record_response(
    response,
    payload=None,
    now=None,
):
    """Record provider counters and circuit-breaker state."""
    ensure_table()

    current = now or _utc_now()

    daily_remaining = _header_int(
        response.headers,
        "x-ratelimit-requests-remaining",
    )

    minute_remaining = _header_int(
        response.headers,
        "X-RateLimit-Remaining",
    )

    try:
        raw_errors = (
            payload.get("errors") or {}
            if isinstance(payload, dict)
            else payload or ""
        )

        error_text = json.dumps(
            raw_errors,
            default=str,
        ).lower()

    except Exception:
        error_text = ""

    db = SessionLocal()

    try:
        row = _row_for_update(
            db,
            current,
        )

        if daily_remaining is not None:
            row.provider_daily_remaining = (
                daily_remaining
            )

        if minute_remaining is not None:
            row.provider_minute_remaining = (
                minute_remaining
            )

        reason = None

        if (
            daily_remaining is not None
            and daily_remaining
            <= provider_reserve()
        ):
            reason = (
                "provider_daily_reserve_reached"
            )

        elif "suspended" in error_text:
            reason = (
                "provider_account_suspended"
            )

        elif (
            (
                "daily limit" in error_text
                or "request limit" in error_text
                or "quota" in error_text
            )
            and (
                "reached" in error_text
                or "exceeded" in error_text
            )
        ):
            reason = (
                "provider_daily_limit_reported"
            )

        elif (
            response.status_code == 429
            and daily_remaining == 0
        ):
            reason = (
                "provider_daily_limit_reported"
            )

        if reason:
            row.blocked = True
            row.block_reason = reason

        elif response.status_code == 429:
            # Minute throttle only.
            row.minute_bucket = (
                current.strftime(
                    "%Y-%m-%dT%H:%M"
                )
            )
            row.minute_used = minute_budget()
            row.provider_minute_remaining = 0

        row.updated_at = current

        db.commit()

    except Exception:
        db.rollback()

        logger.exception(
            "API-Football response quota "
            "recording failed"
        )

    finally:
        db.close()


def quota_status(now=None):
    current = now or _utc_now()

    base = {
        "usage_date":
            current.date().isoformat(),

        "used":
            0,

        "daily_budget":
            daily_budget(),

        "minute_budget":
            minute_budget(),

        "provider_reserve":
            provider_reserve(),

        "provider_daily_remaining":
            None,

        "provider_minute_remaining":
            None,

        "blocked":
            False,

        "block_reason":
            None,

        "process_role":
            process_role(),

        "process_allowed":
            deployed_role_allows_provider(),

        "key_configured":
            bool(api_football_key()),
    }

    try:
        ensure_table()

        db = SessionLocal()

        try:
            row = (
                db.query(APIFootballQuota)
                .filter(
                    APIFootballQuota.usage_date
                    == current.date().isoformat()
                )
                .one_or_none()
            )

            if row is None:
                return base

            return {
                **base,

                "used":
                    int(row.used or 0),

                "provider_daily_remaining":
                    row.provider_daily_remaining,

                "provider_minute_remaining":
                    row.provider_minute_remaining,

                "blocked":
                    bool(row.blocked),

                "block_reason":
                    row.block_reason,

                "last_request_at":
                    (
                        row.last_request_at.isoformat()
                        if row.last_request_at
                        else None
                    ),
            }

        finally:
            db.close()

    except Exception as exc:
        return {
            **base,

            "blocked":
                True,

            "block_reason":
                "quota_store_error",

            "error":
                type(exc).__name__,
        }


def api_football_get(
    endpoint,
    params=None,
    *,
    api_key=None,
    timeout=30,
):
    """The only runtime network gateway to API-Football.

    The retired source is disabled by default in production and staging;
    offline/dev compatibility remains available for historical tooling.
    """
    environment = os.getenv("ENVIRONMENT", "development").strip().lower()
    default = "false" if environment in {"production", "prod", "staging"} else "true"
    enabled = os.getenv("API_FOOTBALL_ENABLED", default).strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        logger.debug("API-Football provider disabled")
        return None
    key = (
        api_key
        or api_football_key()
    ).strip()

    if not key:
        logger.warning(
            "API-Football skipped: "
            "no key configured"
        )

        return None

    allowed, reason = reserve_request()

    if not allowed:
        logger.warning(
            "API-Football blocked locally "
            "endpoint=%s reason=%s",
            endpoint,
            reason,
        )

        return None

    try:
        response = requests.get(
            (
                f"{BASE_URL}/"
                f"{endpoint.lstrip('/')}"
            ),
            headers={
                "x-apisports-key":
                    key,
            },
            params=params or {},
            timeout=timeout,
        )

    except requests.RequestException:
        # Keep the reservation counted.
        logger.exception(
            "API-Football transport error "
            "endpoint=%s",
            endpoint,
        )

        raise

    try:
        payload = response.json()
    except Exception:
        payload = None

    record_response(
        response,
        payload,
    )

    logger.info(
        "API-Football request "
        "endpoint=%s status=%s "
        "daily_remaining=%s "
        "minute_remaining=%s",
        endpoint,
        response.status_code,
        response.headers.get(
            "x-ratelimit-requests-remaining"
        ),
        response.headers.get(
            "X-RateLimit-Remaining"
        ),
    )

    return response
