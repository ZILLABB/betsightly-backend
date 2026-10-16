"""Optional live SportyBet Nigeria scoreboard via the Parse managed API.

The underlying SportyBet website does NOT offer a supported public developer
API. This independent third-party API uses SportyBet's live event IDs. All
scores here are *provisional display-only*; NEVER send them to settlement,
calibration, Telegram official results, or the immutable prediction archive.

Docs: https://parse.bot/marketplace/ee2f426b-cfa0-4321-b46f-392dbd3e7269/sportybet-ng-api
Enable explicitly with SPORTYBET_PARSE_LIVE_ENABLED=true and
SPORTYBET_PARSE_API_KEY; no credentials are sent to the browser.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
import re
import threading
import time

import requests

logger = logging.getLogger(__name__)
_URL = ("https://api.parse.bot/scraper/"
        "1df614cd-9f3c-463c-bd99-bb51593c7dd5/list_live_football_matches")
_LOCK = threading.RLock()
_CACHE: dict = {"status": "not_configured", "matches": [], "fetched_at": None}
_LAST_FETCH = 0.0
_BUDGET_MONTH = ""
_BUDGET_DAY = ""
_MONTH_CALLS = 0
_DAY_CALLS = 0
_EVENT_ID = re.compile(r"^sr:match:\d{1,20}$")
_PLAY = {"H1", "H2", "HT", "1H", "2H", "LIVE", "HALF_TIME"}


def _enabled() -> bool:
    return (os.getenv("SPORTYBET_PARSE_LIVE_ENABLED", "").lower() in
            {"true", "1", "yes"})


def _positive_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(os.getenv(name, str(default)))))
    except ValueError:
        return default


def _score(v) -> int | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int) and 0 <= v <= 99:
        return v
    if isinstance(v, str) and v.isdigit() and 0 <= int(v) <= 99:
        return int(v)
    return None


def _parse_match(row: dict) -> dict | None:
    if not isinstance(row, dict):
        return None
    event_id = row.get("event_id")
    if not isinstance(event_id, str) or not _EVENT_ID.fullmatch(event_id):
        return None
    if row.get("is_live") is not True:
        return None
    home = row.get("home_team")
    away = row.get("away_team")
    if not isinstance(home, str) or not isinstance(away, str):
        return None
    home, away = home.strip()[:120], away.strip()[:120]
    if not home or not away:
        return None
    state = str(row.get("match_status") or "").strip().upper()
    if state not in _PLAY:
        return None
    hs, aw = _score(row.get("home_score")), _score(row.get("away_score"))
    if hs is None or aw is None:
        return None
    try:
        ms = int(row.get("start_time_ms"))
        kickoff = datetime.fromtimestamp(ms / 1000, timezone.utc)
        if ms < 1_000_000_000_000 or ms > 5_000_000_000_000:
            return None
    except (ValueError, TypeError, OverflowError, OSError):
        return None
    minute = row.get("match_minute")
    try:
        minute = int(minute) if minute is not None else None
    except (ValueError, TypeError):
        minute = None
    if minute is not None and not (0 <= minute <= 150):
        minute = None
    return {
        "event_id": event_id, "home_team": home, "away_team": away,
        "home_score": hs, "away_score": aw,
        "date": kickoff.date().isoformat(),
        "kickoff": kickoff.isoformat(),
        "match_minute": minute,
        "match_status": state, "live": True, "finished": False,
        "provider": "sportybet-via-parse", "provisional": True,
    }


def _parse_payload(data: dict) -> list[dict]:
    # Parse's documented response is {"status":"success",
    # "data":{"matches":[...],"total":N,"live_count":N}}.
    if not isinstance(data, dict) or data.get("status") != "success":
        raise ValueError("unexpected_provider_status")
    body = data.get("data")
    if not isinstance(body, dict) or not isinstance(body.get("matches"), list):
        raise ValueError("unexpected_live_score_payload")
    # Duplicated event IDs are ambiguous. Do not pick one silently.
    entries: dict[str, list[dict]] = {}
    for raw in body["matches"][:500]:
        m = _parse_match(raw)
        if m:
            entries.setdefault(m["event_id"], []).append(m)
    return [matches[0] for matches in entries.values() if len(matches) == 1]


def snapshot() -> dict:
    """Bounded single-flight provider snapshot; empty when disabled or keyless.

    Safe for concurrent public page requests; per-process quotas are a secondary
    guard, not a billing guarantee across multiple workers/deployments. Parse
    account credit limits remain the primary enforcement mechanism.
    """
    global _LAST_FETCH, _BUDGET_DAY, _BUDGET_MONTH, _MONTH_CALLS, _DAY_CALLS
    if not _enabled():
        return {"status": "disabled", "matches": [], "fetched_at": None}
    api_key = os.getenv("SPORTYBET_PARSE_API_KEY", "").strip()
    if not api_key:
        return {"status": "missing_api_key", "matches": [], "fetched_at": None}
    with _LOCK:
        now = time.monotonic()
        ttl = _positive_int("SPORTYBET_PARSE_CACHE_SECONDS", 900, 120, 3600)
        if _LAST_FETCH and now - _LAST_FETCH < ttl:
            return dict(_CACHE)
        utc = datetime.now(timezone.utc)
        month, day = utc.strftime("%Y-%m"), utc.strftime("%Y-%m-%d")
        if month != _BUDGET_MONTH:
            _BUDGET_MONTH, _MONTH_CALLS = month, 0
        if day != _BUDGET_DAY:
            _BUDGET_DAY, _DAY_CALLS = day, 0
        monthly_cap = _positive_int("SPORTYBET_PARSE_MONTHLY_BUDGET", 150, 1, 100000)
        daily_cap = _positive_int("SPORTYBET_PARSE_DAILY_BUDGET", 5, 1, 10000)
        if _MONTH_CALLS >= monthly_cap or _DAY_CALLS >= daily_cap:
            return {"status": "budget_exhausted", "matches": [],
                    "fetched_at": _CACHE.get("fetched_at")}
        # Charge local request budget before calling, even if the provider times out:
        # a failing provider never creates a hot retry loop.
        _DAY_CALLS += 1
        _MONTH_CALLS += 1
        _LAST_FETCH = now
        try:
            response = requests.get(
                _URL, params={"include_upcoming": "false"},
                headers={"Accept": "application/json", "X-API-Key": api_key},
                timeout=9,
            )
            if response.status_code != 200:
                status = "provider_http_" + str(response.status_code)
                result = {"status": status, "matches": [],
                          "fetched_at": utc.isoformat()}
            else:
                parsed = _parse_payload(response.json())
                result = {"status": "live" if parsed else "no_live_games",
                          "matches": parsed, "fetched_at": utc.isoformat()}
        except (requests.RequestException, ValueError, TypeError) as exc:
            logger.warning("SportyBet live feed unavailable: %s", type(exc).__name__)
            result = {"status": "provider_unavailable", "matches": [],
                      "fetched_at": utc.isoformat()}
        _CACHE.clear()
        _CACHE.update(result)
        return dict(result)
