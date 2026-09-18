"""Month-based ESPN final-score collection; read-only provider requests.

The ESPN soccer scoreboard rejects day-range expressions such as
20260914-20260918. Month requests (202609) return both completed and upcoming
fixtures, so only completed competitions with regulation scores are retained.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Callable

logger = logging.getLogger(__name__)


def month_keys(start_date: str, end_date: str) -> list[str]:
    """Inclusive months for the requested dates plus a one-day timezone margin."""
    start = datetime.strptime(start_date, "%Y-%m-%d").date() - timedelta(days=1)
    end = datetime.strptime(end_date, "%Y-%m-%d").date() + timedelta(days=1)
    if start > end:
        raise ValueError("reversed score date range")
    cursor = start.replace(day=1)
    months: list[str] = []
    while cursor <= end:
        months.append(cursor.strftime("%Y%m"))
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    return months


def collect_monthly_scores(
    start_date: str,
    end_date: str,
    *,
    slugs: list[str],
    fetch_month: Callable[[str, str], list[dict]],
    regulation_score: Callable[[dict], dict | None],
    normalize: Callable[[str], str],
) -> dict[str, dict]:
    """Get verified final scores with exact home/away/date keys.

    Ambiguous same-team/date collisions are deliberately omitted. No league or
    match is assigned a synthetic final and no database writes occur here.
    """
    months = month_keys(start_date, end_date)
    lo = (datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=1)).date()
    hi = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).date()
    requests = [(slug, month) for slug in sorted(set(slugs)) if slug for month in months]
    if not requests:
        return {}

    def fetch(key: tuple[str, str]):
        slug, month = key
        try:
            return key, fetch_month(slug, month) or []
        except Exception as exc:
            logger.warning("Monthly scores failed league=%s month=%s error=%s",
                           slug, month, type(exc).__name__)
            return key, []

    finished: dict[str, dict] = {}
    ambiguous: set[str] = set()
    # A loose pair key is supported only for legacy callers with no date, and
    # only when this pair has exactly one fixture in the whole result window.
    pair_matches: dict[str, tuple[str, dict] | None] = {}
    with ThreadPoolExecutor(max_workers=min(16, len(requests))) as pool:
        for (slug, _month), events in pool.map(fetch, requests):
            for event in events:
                try:
                    comp = (event.get("competitions") or [{}])[0]
                    status = ((comp.get("status") or event.get("status") or {})
                              .get("type") or {})
                    if not status.get("completed"):
                        continue
                    kickoff = datetime.fromisoformat(
                        str(event.get("date") or comp.get("date") or "").replace("Z", "+00:00")
                    )
                    if kickoff.tzinfo is None:
                        continue
                    fixture_day = kickoff.astimezone(timezone.utc).date()
                    if not lo <= fixture_day <= hi:
                        continue
                    competitors = comp.get("competitors") or []
                    home = [p for p in competitors if p.get("homeAway") == "home"]
                    away = [p for p in competitors if p.get("homeAway") == "away"]
                    if len(home) != 1 or len(away) != 1:
                        continue
                    hn = str((home[0].get("team") or {}).get("displayName") or "")
                    an = str((away[0].get("team") or {}).get("displayName") or "")
                    if not normalize(hn) or not normalize(an):
                        continue
                    score = regulation_score(comp)
                    if score is None:
                        continue
                    hs, aw = int(score["home_score"]), int(score["away_score"])
                    if hs < 0 or aw < 0:
                        continue
                except (AttributeError, IndexError, KeyError, TypeError, ValueError):
                    continue
                payload = {
                    "home": hn, "away": an, "home_score": hs, "away_score": aw,
                    "completed": True, "source": "espn_monthly",
                    "league_slug": slug, "provider_event_id": str(event.get("id") or ""),
                    "event_kickoff": kickoff.astimezone(timezone.utc).isoformat(),
                    **{key: score.get(key) for key in (
                        "score_90", "score_extra_time", "penalty_score",
                        "qualified_team", "match_status",
                    )},
                }
                pair = f"{normalize(hn)}|{normalize(an)}"
                exact = f"{pair}|{fixture_day.isoformat()}"
                if exact in ambiguous:
                    continue
                prior = finished.get(exact)
                if prior and (prior["provider_event_id"], prior["league_slug"],
                              prior["event_kickoff"], prior["home_score"], prior["away_score"]) != (
                              payload["provider_event_id"], slug, payload["event_kickoff"], hs, aw):
                    finished.pop(exact, None)
                    ambiguous.add(exact)
                    logger.warning("Ambiguous score for %s; awaiting fixture-specific recovery", exact)
                    continue
                finished[exact] = payload

    for key, payload in finished.items():
        pair = key.rsplit("|", 1)[0]
        if pair not in pair_matches:
            pair_matches[pair] = (key, payload)
        elif pair_matches[pair] and pair_matches[pair][0] != key:
            pair_matches[pair] = None
    for pair, match in pair_matches.items():
        if match is not None:
            finished[pair] = match[1]
    return finished
