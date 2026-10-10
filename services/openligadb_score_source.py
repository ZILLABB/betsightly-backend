"""Read-only OpenLigaDB final-score adapter for German domestic leagues.

OpenLigaDB is free, keyless, community-maintained (ODbL 1.0).
Use only *finished* fixtures with an explicit 90-minute full-time result.
Never synthesize odds, create prediction candidates, or grade cup/tie scores.
Provider: https://api.openligadb.de/ (60 req/min/IP; cached here for 30 min).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import date, datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)
BASE_URL = "https://api.openligadb.de"
LEAGUE_SHORTCUTS = {
    "ger.1": "bl1",
    "ger.2": "bl2",
    # Kept for forward compatibility if ger.3 is added to the competition registry.
    "ger.3": "bl3",
}
_CACHE_TTL = 30 * 60
_FAILURE_TTL = 2 * 60
_CACHE: dict[tuple[str, int], tuple[float, list[dict]]] = {}
_LOCK = threading.Lock()

# These are deliberately explicit league-name aliases, not fuzzy matching.
# Names absent from this table are left unchanged and might remain unverified.
ESPN_TEAM_ALIASES = {
    "FC Bayern München": "Bayern Munich",
    "FC Bayern Muenchen": "Bayern Munich",
    "Bayer 04 Leverkusen": "Bayer Leverkusen",
    "1. FSV Mainz 05": "Mainz",
    "1. FC Köln": "FC Cologne",
    "1. FC Koeln": "FC Cologne",
    "1. FC Union Berlin": "Union Berlin",
    "TSG 1899 Hoffenheim": "TSG Hoffenheim",
    "SV Werder Bremen": "Werder Bremen",
}


def _valid_score(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
        return parsed if parsed >= 0 and str(value).strip() == str(parsed) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _utc_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone.utc).date().isoformat()
    except ValueError:
        return None


def _normalize_fixture(match: dict, shortcut: str, season: int) -> dict | None:
    """Only a completed league match with one unambiguous 90-minute final."""
    if match.get("matchIsFinished") is not True:
        return None
    if match.get("leagueShortcut") not in (None, shortcut):
        return None
    try:
        league_season = match.get("leagueSeason")
        if league_season is not None and int(league_season) != season:
            return None
    except (ValueError, TypeError):
        return None
    date_text = _utc_date(match.get("matchDateTimeUTC"))
    home = (match.get("team1") or {}).get("teamName")
    away = (match.get("team2") or {}).get("teamName")
    if not date_text or not home or not away or home == away:
        return None

    rows = match.get("matchResults")
    if not isinstance(rows, list):
        return None
    results: list[tuple[int, int]] = []
    for result in rows:
        if not isinstance(result, dict):
            return None
        try:
            kind = int(result.get("resultTypeID"))
        except (ValueError, TypeError):
            return None
        # Do not use extra-time/penalty totals for 90-minute markets.
        if kind in {3, 4}:
            return None
        if kind != 2:
            continue
        hs = _valid_score(result.get("pointsTeam1"))
        aw = _valid_score(result.get("pointsTeam2"))
        if hs is None or aw is None:
            return None
        results.append((hs, aw))
    if len(results) != 1:
        return None
    hs, aw = results[0]
    return {
        "home": ESPN_TEAM_ALIASES.get(home, home),
        "away": ESPN_TEAM_ALIASES.get(away, away),
        "home_score": hs,
        "away_score": aw,
        "date": date_text,
        "completed": True,
        "provider": "openligadb",
        "provider_event_id": match.get("matchID"),
        "score_90": {"home": hs, "away": aw},
        "match_status": "FT",
        "source_attribution": "OpenLigaDB (ODbL 1.0)",
    }


def _season_for(day: date) -> int:
    return day.year if day.month >= 7 else day.year - 1


def _season_finals(shortcut: str, season: int) -> list[dict]:
    key = (shortcut, season)
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and cached[0] > time.monotonic():
            return list(cached[1])

    try:
        resp = requests.get(
            f"{BASE_URL}/getmatchdata/{shortcut}/{season}",
            timeout=12, headers={"Accept": "application/json"},
        )
        if resp.status_code == 429:
            try:
                retry = min(1800, max(60, int(resp.headers.get("Retry-After", "60"))))
            except (ValueError, TypeError):
                retry = 60
            with _LOCK:
                _CACHE[key] = (time.monotonic() + retry, [])
            logger.warning("OpenLigaDB rate limited league=%s season=%s", shortcut, season)
            return []
        if resp.status_code != 200:
            logger.warning("OpenLigaDB HTTP_%s league=%s season=%s",
                           resp.status_code, shortcut, season)
            with _LOCK:
                _CACHE[key] = (time.monotonic() + _FAILURE_TTL, [])
            return []
        payload = resp.json()
        if not isinstance(payload, list):
            logger.warning("OpenLigaDB invalid response type league=%s", shortcut)
            return []
        finals = [row for match in payload if isinstance(match, dict)
                  if (row := _normalize_fixture(match, shortcut, season)) is not None]
        with _LOCK:
            _CACHE[key] = (time.monotonic() + _CACHE_TTL, finals)
        logger.info("OpenLigaDB fixture snapshot league=%s season=%s total=%s finals=%s",
                    shortcut, season, len(payload), len(finals))
        return finals
    except (requests.RequestException, ValueError, TypeError) as exc:
        logger.warning("OpenLigaDB unavailable league=%s season=%s reason=%s",
                       shortcut, season, type(exc).__name__)
        with _LOCK:
            _CACHE[key] = (time.monotonic() + _FAILURE_TTL, [])
        return []


def openligadb_finals(picks: list[dict]) -> list[dict]:
    """Fetch only seasons/leagues of *unresolved* German domestic predictions.

    Requires an explicit ESPN league_slug: unknown leagues, German cup ties
    and international competitions must never be accidentally settled here.
    """
    enabled = os.getenv("OPENLIGADB_ENABLED", "true").strip().lower()
    if enabled not in {"true", "1", "yes", "on"}:
        return []
    targets: set[tuple[str, int, str]] = set()
    for pick in picks:
        slug = str(pick.get("league_slug") or "")
        shortcut = LEAGUE_SHORTCUTS.get(slug)
        if shortcut is None:
            continue
        kickoff = str(pick.get("commence_time") or pick.get("kickoff") or
                      pick.get("date") or "")
        iso_date = _utc_date(kickoff) if "T" in kickoff else kickoff[:10]
        try:
            target_date = date.fromisoformat(iso_date or "")
        except ValueError:
            continue
        targets.add((shortcut, _season_for(target_date), target_date.isoformat()))

    if not targets:
        return []
    # Limit work to up to three distinct league-seasons per settlement pass.
    # Cached, normal Bundesliga + second-division calls are 2 per 30 minutes.
    by_season: dict[tuple[str, int], set[str]] = {}
    for shortcut, season, target_date in sorted(targets, reverse=True):
        by_season.setdefault((shortcut, season), set()).add(target_date)
    results: list[dict] = []
    for (shortcut, season), dates in list(by_season.items())[:3]:
        for row in _season_finals(shortcut, season):
            if row["date"] in dates:
                results.append(row)
    return results
