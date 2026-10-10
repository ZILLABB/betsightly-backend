"""Conservative score-only adapters for two free football services.

Never publish fixtures/odds from these providers or amend official predictions.
The sources only supply *finished regulation-time scores* for unresolved bets.
Each request is bounded, the football-data.org token is read from environment,
and provider errors/cooldowns are non-fatal. TheSportsDB's public v1 key is for
development/shadow use unless production rights have been cleared.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any

import requests

logger = logging.getLogger(__name__)
FD_URL = "https://api.football-data.org/v4/matches"
SPORTSDB_URL = "https://www.thesportsdb.com/api/v1/json/123/eventsday.php"
_LOCK = threading.Lock()
_CACHE: dict[tuple, tuple[float, list[dict]]] = {}
_COOLDOWN: dict[str, float] = {}
_MIN_INTERVAL: dict[str, float] = {}
_CACHE_SECONDS = 12 * 60


def _usable(name: str) -> bool:
    now = time.monotonic()
    with _LOCK:
        if _COOLDOWN.get(name, 0) > now:
            return False
        if _MIN_INTERVAL.get(name, 0) > now:
            return False
        _MIN_INTERVAL[name] = now + (12 if name == "football-data.org" else 4)
        return True


def _cooldown(name: str, seconds: int) -> None:
    with _LOCK:
        _COOLDOWN[name] = max(
            _COOLDOWN.get(name, 0), time.monotonic() + min(3600, max(5, seconds))
        )


def _header_seconds(headers: Any, key: str, default: int) -> int:
    try:
        return max(1, int(float(headers.get(key, default))))
    except (ValueError, TypeError, OverflowError):
        return default


def _get(name: str, url: str, *, params: dict, headers: dict | None = None,
         key: tuple) -> dict | None:
    with _LOCK:
        item = _CACHE.get(key)
        if item and item[0] > time.monotonic():
            return {"_cached_matches": item[1]}
    if not _usable(name):
        return None
    try:
        response = requests.get(
            url, params=params, headers=headers or {}, timeout=12,
        )
        if name == "football-data.org":
            remaining = response.headers.get("X-Requests-Available-Minute")
            if remaining is not None:
                try:
                    if int(remaining) <= 1:
                        _cooldown(name, _header_seconds(
                            response.headers, "X-RequestCounter-Reset", 60,
                        ))
                except (ValueError, TypeError):
                    pass
        if response.status_code == 429:
            seconds = _header_seconds(
                response.headers, "Retry-After",
                _header_seconds(response.headers, "X-RequestCounter-Reset", 60),
            )
            _cooldown(name, seconds)
            logger.warning("%s rate limited; cooldown_seconds=%s", name, seconds)
            return None
        if response.status_code in (401, 403):
            _cooldown(name, 1800)
            logger.warning("%s permission denied HTTP_%s", name, response.status_code)
            return None
        if response.status_code != 200:
            logger.warning("%s returned HTTP_%s", name, response.status_code)
            return None
        payload = response.json()
        return payload if isinstance(payload, dict) else None
    except (requests.RequestException, ValueError, TypeError) as exc:
        logger.warning("%s results unavailable: %s", name, type(exc).__name__)
        return None


def _valid_window(start: str, end: str, *, max_days: int) -> bool:
    try:
        lo = datetime.strptime(start, "%Y-%m-%d").date()
        hi = datetime.strptime(end, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False
    return lo <= hi and (hi - lo).days <= max_days


def _score_pair(score: dict) -> tuple[int, int] | None:
    if not isinstance(score, dict):
        return None
    try:
        home, away = score.get("home"), score.get("away")
        if isinstance(home, bool) or isinstance(away, bool):
            return None
        if home is None or away is None:
            return None
        h, a = int(home), int(away)
        return (h, a) if h >= 0 and a >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _fd_match(match: dict) -> dict | None:
    if match.get("status") != "FINISHED":
        return None
    home = (match.get("homeTeam") or {}).get("name")
    away = (match.get("awayTeam") or {}).get("name")
    date = str(match.get("utcDate") or "")[:10]
    score = match.get("score") or {}
    if not home or not away or not _valid_window(date, date, max_days=0):
        return None
    duration = score.get("duration")
    regulation = score.get("regularTime")
    if duration == "REGULAR":
        pair = _score_pair(regulation) or _score_pair(score.get("fullTime"))
    elif duration in {"EXTRA_TIME", "PENALTY_SHOOTOUT"}:
        # Full-time includes extra time / shootouts. Never grade 90-minute
        # markets on those; v4 regularTime is the only admissible source.
        pair = _score_pair(regulation)
    else:
        return None
    if not pair:
        return None
    return {"home": home, "away": away, "date": date, "home_score": pair[0],
            "away_score": pair[1], "completed": True,
            "provider": "football-data.org",
            "provider_event_id": match.get("id"),
            "score_90": {"home": pair[0], "away": pair[1]},
            "match_status": "FT"}


def football_data_finals(start: str, end: str) -> list[dict]:
    """Use one request for all free-plan competitions in a short date window."""
    token = os.getenv("FOOTBALL_DATA_ORG_TOKEN", "").strip()
    if not token or not _valid_window(start, end, max_days=7):
        return []
    key = ("football-data.org", start, end)
    payload = _get("football-data.org", FD_URL,
                   params={"dateFrom": start, "dateTo": end, "status": "FINISHED"},
                   headers={"X-Auth-Token": token}, key=key)
    if payload is None:
        return []
    if "_cached_matches" in payload:
        return list(payload["_cached_matches"])
    matches = payload.get("matches")
    if not isinstance(matches, list):
        return []
    rows = [row for item in matches if isinstance(item, dict)
            if (row := _fd_match(item)) is not None]
    with _LOCK:
        _CACHE[key] = (time.monotonic() + _CACHE_SECONDS, rows)
    return rows


def _sportsdb_match(event: dict) -> dict | None:
    if str(event.get("strSport") or "").lower() != "soccer":
        return None
    status = str(event.get("strStatus") or "").lower().strip()
    # Nullable status cannot be interpreted as final; nor can postponed,
    # penalties, abandoned or extra-time scores.
    if status not in {"match finished", "finished", "ft", "full time"}:
        return None
    home, away = event.get("strHomeTeam"), event.get("strAwayTeam")
    date = str(event.get("dateEvent") or "")[:10]
    if not home or not away or not _valid_window(date, date, max_days=0):
        return None
    pair = _score_pair({"home": event.get("intHomeScore"),
                        "away": event.get("intAwayScore")})
    if pair is None:
        return None
    return {"home": home, "away": away, "date": date, "home_score": pair[0],
            "away_score": pair[1], "completed": True, "provider": "thesportsdb",
            "provider_event_id": event.get("idEvent"),
            "score_90": {"home": pair[0], "away": pair[1]},
            "match_status": "FT"}


def sportsdb_finals(dates: list[str]) -> list[dict]:
    """Development-only secondary source; free endpoint returns <=3 per day."""
    enabled = os.getenv("THESPORTSDB_FALLBACK_ENABLED", "false").lower()
    if enabled not in {"true", "1", "yes", "on"}:
        return []
    results: list[dict] = []
    for date in sorted(set(dates))[:3]:
        if not _valid_window(date, date, max_days=0):
            continue
        key = ("thesportsdb", date)
        payload = _get("thesportsdb", SPORTSDB_URL,
                       params={"d": date, "s": "Soccer"}, key=key)
        if payload is None:
            continue
        if "_cached_matches" in payload:
            results.extend(payload["_cached_matches"])
            continue
        events = payload.get("events")
        if not isinstance(events, list):
            continue
        rows = [row for event in events if isinstance(event, dict)
                if (row := _sportsdb_match(event)) is not None]
        results.extend(rows)
        with _LOCK:
            _CACHE[key] = (time.monotonic() + _CACHE_SECONDS, rows)
    return results
