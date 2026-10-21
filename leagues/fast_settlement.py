"""Low-cost, verified full-time ESPN scoreboard collector for rapid settlement.

This source is deliberately *not* the provisional/live UI feed. We inspect
explicitly completed competitions, use regulation-time scores only, and
retain exact home/away/UTC-date identity checks in the common evaluator.
Unavailable or ambiguous fixtures remain pending for the broader 15-minute
multi-provider recovery cycle.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import logging
import threading
import time

import requests

LOG = logging.getLogger(__name__)
_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
_CACHE_LOCK = threading.Lock()
_CACHE: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_CACHE_TTL = 45
_RECENT_HOURS = 12


def _utc_datetime(raw: object) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(raw or "").replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def _fetch_confirmed_events(slug: str, day: str) -> list[dict]:
    """Cache one small competition/day lookup; never cache a false final."""
    key = (slug, day)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
    try:
        resp = requests.get(
            _SCOREBOARD.format(slug=slug),
            params={"dates": day.replace("-", ""), "limit": 200},
            timeout=9,
        )
        if resp.status_code != 200:
            LOG.warning("Rapid ESPN score fetch failed league=%s day=%s HTTP_%s",
                        slug, day, resp.status_code)
            return []
        events = resp.json().get("events")
        if not isinstance(events, list):
            return []
    except (requests.RequestException, ValueError, TypeError) as exc:
        LOG.warning("Rapid ESPN score fetch failed league=%s day=%s error=%s",
                    slug, day, type(exc).__name__)
        return []
    with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic() + _CACHE_TTL, events)
        if len(_CACHE) > 300:
            # This is only a recent-fixture cache, not a historical score DB.
            expired = [k for k, (deadline, _) in _CACHE.items()
                       if deadline < time.monotonic()]
            for expired_key in expired:
                _CACHE.pop(expired_key, None)
    return events


def collect_recent_verified_finals(
    picks: list[dict], *, now: datetime | None = None,
) -> tuple[dict, str]:
    """Request just the leagues/dates of recent finished-or-finishing picks.

    A 60-second job must not perform the monthly all-league archive scan.
    Non-ESPN competitions are handled by the regular fallback cycle.
    """
    from leagues.competition_registry import regulation_score
    from leagues.live_scores import infer_published_competition_slugs
    from leagues.results_checker import _index_free_finals

    current = now or datetime.now(timezone.utc)
    wanted: set[tuple[str, str]] = set()
    for pick in picks:
        if pick.get("status") in {"won", "lost", "void"}:
            continue
        kickoff = _utc_datetime(
            pick.get("commence_time") or pick.get("kickoff") or pick.get("date")
        )
        if (kickoff is None or current < kickoff + timedelta(minutes=80)
                or kickoff < current - timedelta(hours=_RECENT_HOURS)):
            continue
        slugs, _ = infer_published_competition_slugs([pick])
        if len(slugs) != 1:
            continue
        slug = next(iter(slugs))
        # Use the provider kickoff's UTC date, not an inferred local day.
        wanted.add((slug, kickoff.date().isoformat()))

    if not wanted:
        return {}, "espn-rapid"

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(
            lambda item: (item, _fetch_confirmed_events(*item)),
            sorted(wanted),
        ))

    for (slug, _), events in responses:
        for event in events:
            comps = event.get("competitions") or []
            if not comps or not isinstance(comps[0], dict):
                continue
            comp = comps[0]
            if not ((comp.get("status") or {}).get("type") or {}).get("completed"):
                continue
            members = comp.get("competitors") or []
            home = next((m for m in members if m.get("homeAway") == "home"), None)
            away = next((m for m in members if m.get("homeAway") == "away"), None)
            if not home or not away:
                continue
            score = regulation_score(comp)
            kickoff = _utc_datetime(event.get("date"))
            if score is None or kickoff is None:
                continue
            home_name = (home.get("team") or {}).get("displayName")
            away_name = (away.get("team") or {}).get("displayName")
            if not home_name or not away_name:
                continue
            rows.append({
                "home": home_name, "away": away_name,
                "date": kickoff.date().isoformat(),
                "home_score": score["home_score"],
                "away_score": score["away_score"],
                "completed": True, "provider": "espn",
                "provider_event_id": event.get("id"),
                "score_90": score.get("score_90"),
                "match_status": score.get("match_status"),
                "league_slug": slug,
            })

    LOG.info("Rapid verified finals leagues_dates=%s completed_rows=%s",
             len(wanted), len(rows))
    return _index_free_finals(rows), "espn-rapid"
