"""Permitted zero-key football result candidate feed (SportScore).

The public API is free with a visible attribution requirement. We use it for
SHADOW evidence only until regulation-time semantics, source independence and
public attribution have been verified. Never grade a paid ticket from these
observations alone, especially after extra time or penalties.

Docs: https://sportscore.com/developers/api/
Terms: https://sportscore.com/developers/terms/
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

LOG = logging.getLogger(__name__)
URL = "https://sportscore.com/api/v1/fixtures/"
_CACHE: dict[str, tuple[float, list[dict]]] = {}
_LOCK = threading.Lock()
_WAIT_UNTIL = 0.0
_TTL = 15 * 60
_CUP = re.compile(r"\\b(cup|pokal|copa|trophy|knockout|playoff|play-off|champions league|europa league)\\b", re.I)


def _datetime(value: object) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def _score(value: object) -> int | None:
    if isinstance(value, bool) or value is None or not re.fullmatch(r"[0-9]{1,2}", str(value)):
        return None
    result = int(value)
    return result if result <= 30 else None


def _url_id(value: object) -> tuple[str, bool]:
    """Use a provider-generated match URL only; detect apparent reversal."""
    if not isinstance(value, str) or not value.startswith("/football/match/"):
        return "", False
    parsed = urlparse(value)
    parts = parsed.path.strip("/").split("/")
    if len(parts) != 4 or parts[:2] != ["football", "match"] or not parts[3]:
        return "", False
    if not re.fullmatch(r"[a-z0-9-]+", parts[2]) or not re.fullmatch(r"[a-z0-9]+", parts[3]):
        return "", False
    return parts[3], "vs" in parts[2]


def _norm(value: object) -> str:
    from leagues.results_checker import _normalize_name
    return _normalize_name(str(value or ""))


def parse_fixture(entry: dict, day: str) -> dict | None:
    """Return a *candidate*, not a settlement result."""
    if not isinstance(entry, dict) or entry.get("status") != "finished":
        return None
    status = str(entry.get("status_text") or "").strip().lower()
    # SportScore's 'finished' doesn't document whether a knockout score is 90m
    # or after extra time. Reject all apparent non-regulation formats.
    if status not in {"finished", "full time", "ft"}:
        return None
    competition = str(entry.get("competition") or "").strip()
    if not competition or _CUP.search(competition):
        return None
    home = str(entry.get("home") or "").strip()
    away = str(entry.get("away") or "").strip()
    when = _datetime(entry.get("time"))
    hs, vs = _score(entry.get("home_score")), _score(entry.get("away_score"))
    event_id, has_ordered_slug = _url_id(entry.get("url"))
    if not (home and away and _norm(home) != _norm(away) and when
            and when.date().isoformat() == day and hs is not None
            and vs is not None and event_id and has_ordered_slug):
        return None
    # Some external feed rows have the opposite home/away order in their own
    # URL. Do not auto-settle these ambiguous home/away score assignments.
    slug = entry["url"].split("/")[3]
    hhead = re.sub(r"[^a-z0-9]+", "-", home.lower()).strip("-")
    ahead = re.sub(r"[^a-z0-9]+", "-", away.lower()).strip("-")
    if hhead and ahead and slug.startswith(ahead + "-vs-"):
        return None
    return {
        "home": home, "away": away, "date": day,
        "home_score": hs, "away_score": vs,
        "kickoff_utc": when.isoformat(), "competition": competition,
        "completed": True, "provider": "sportscore-shadow",
        "provider_event_id": event_id,
        "match_status": "FT_CANDIDATE_NOT_VERIFIED_90MIN",
        "score_90": None,
        "evidence_url": "https://sportscore.com" + entry["url"],
        "source_attribution": "SportScore / Powered by SportScore",
    }


def fetch_day(day: str) -> list[dict]:
    """One limited, cached public GET per date; fail closed on quotas/schema."""
    global _WAIT_UNTIL
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except (TypeError, ValueError):
        return []
    with _LOCK:
        now = time.monotonic()
        cached = _CACHE.get(day)
        if cached and cached[0] > now:
            return list(cached[1])
        if _WAIT_UNTIL > now:
            return []
        # Reserve the slot before releasing the lock; prevent simultaneous GETs.
        _CACHE[day] = (now + 60, [])
    try:
        resp = requests.get(
            URL, params={"sport": "football", "date": day,
                         "status": "finished", "limit": 200},
            headers={"Accept": "application/json",
                     "User-Agent": "BetSightly-settlement-coverage/1.0"},
            timeout=12,
        )
        if resp.status_code == 429:
            with _LOCK:
                _WAIT_UNTIL = max(_WAIT_UNTIL, time.monotonic() + 30 * 60)
            return []
        if resp.status_code != 200:
            LOG.warning("SportScore candidate day=%s HTTP_%s", day, resp.status_code)
            return []
        data = resp.json()
        if not isinstance(data, dict) or data.get("date") != day:
            return []
        rows = data.get("matches")
        if not isinstance(rows, list) or len(rows) > 200:
            return []
        output = [p for e in rows if (p := parse_fixture(e, day)) is not None]
        with _LOCK:
            _CACHE[day] = (time.monotonic() + _TTL, output)
        if data.get("count", 0) >= 200:
            LOG.info("SportScore day=%s returned capped 200-match page; coverage incomplete", day)
        return output
    except (requests.RequestException, ValueError, TypeError) as exc:
        LOG.warning("SportScore candidate feed unavailable day=%s error=%s", day, type(exc).__name__)
        return []


def candidate_matches(picks: list[dict]) -> list[dict]:
    """Strictly match only candidates to already-saved bookmaker fixtures.

    No candidate from this function is FT/90-minute settlement evidence.
    """
    if os.getenv("SPORTSCORE_SHADOW_ENABLED", "false").lower() not in ("true", "1", "yes"):
        return []
    pending = [p for p in picks if p.get("status") not in ("won", "lost", "void")]
    days = sorted({str(p.get("kickoff") or p.get("commence_time") or
                       p.get("date") or "")[:10] for p in pending}, reverse=True)
    # Fair-use bounded recovery: two recent dates and one historical rotation.
    recent = days[:2]
    old = days[2:]
    if old:
        recent.append(old[(int(time.time()) // 900) % len(old)])
    rows = [row for day in recent for row in fetch_day(day)]
    claims = {}
    for p in pending:
        kickoff = _datetime(p.get("kickoff") or p.get("commence_time") or p.get("date"))
        if not kickoff:
            continue
        home, away = _norm(p.get("home_team")), _norm(p.get("away_team"))
        league = _norm(p.get("league"))
        matches = [
            row for row in rows
            if _norm(row["home"]) == home and _norm(row["away"]) == away
            and (not league or _norm(row["competition"]) == league)
            and (time_p := _datetime(row["kickoff_utc"])) is not None
            and abs((time_p - kickoff).total_seconds()) <= 20 * 60
        ]
        if len(matches) == 1:
            key = str(p.get("sportybet_event_id") or p.get("match_id") or "")
            if key:
                claims.setdefault(key, []).append(matches[0])
    accepted = [
        candidates[0] for candidates in claims.values()
        if len({(x["provider_event_id"], x["home"], x["away"]) for x in candidates}) == 1
    ]
    LOG.info("SportScore shadow inspected=%s candidates=%s visited_days=%s",
             len(pending), len(accepted), len(recent))
    return accepted
