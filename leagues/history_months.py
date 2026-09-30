"""One normalized, versioned league-month result shared by history consumers."""

import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from leagues.cache_paths import cache_path
from leagues.competition_registry import competition_for, regulation_score
from leagues.espn_history_fetch import HistoryMonthUnavailable, finished_events
from leagues.history_cache_io import (local_refresh_claim, read_complete,
                                      replace_complete)
from leagues import shared_history_store


SCHEMA = 1
MONTH_DIR = cache_path(Path(__file__).parent / "data" / "history_months")
CURRENT_TTL = 12 * 3600
PAST_TTL = 7 * 24 * 3600


def _normalize(slug: str, events: list[dict]) -> list[dict]:
    meta = competition_for(slug)
    rows = []
    seen = set()
    for ev in events:
        comp = (ev.get("competitions") or [{}])[0]
        if not comp.get("status", {}).get("type", {}).get("completed"):
            continue
        teams = comp.get("competitors") or []
        home = next((t for t in teams if t.get("homeAway") == "home"), None)
        away = next((t for t in teams if t.get("homeAway") == "away"), None)
        score = regulation_score(comp) if home and away else None
        identity = str(ev.get("id") or "")
        if not score or not identity or identity in seen:
            continue
        seen.add(identity)
        rows.append({
            "id": identity, "date": str(ev.get("date") or "")[:10],
            "home": (home.get("team") or {}).get("displayName", ""),
            "away": (away.get("team") or {}).get("displayName", ""),
            "hs": score["home_score"], "as": score["away_score"],
            "team_type": meta.team_type if meta else "CLUB",
        })
    return rows


def _month(slug: str, key: str, *, as_of: datetime | None = None) -> list[dict]:
    first = datetime.strptime(key, "%Y%m").date()
    next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    last = next_month - timedelta(days=1)
    if as_of is not None:
        # As-of replay cannot use a later live-cache observation.
        return _normalize(slug, finished_events(
            slug, first.strftime("%Y%m%d"), last.strftime("%Y%m%d"),
            limit=900, as_of=as_of))

    safe_slug = re.sub(r"[^A-Za-z0-9._-]", "_", slug)
    path = MONTH_DIR / f"{safe_slug}-{key}.json"
    cache_key = f"month:{slug}:{key}"
    complete = read_complete(path, SCHEMA, required="matches")
    if shared_history_store.production_shared():
        try:
            complete = (shared_history_store.read(
                cache_key, SCHEMA, required="matches") or complete)
        except Exception:
            pass
    ttl = CURRENT_TTL if key == datetime.now(timezone.utc).strftime("%Y%m") else PAST_TTL
    if complete and time.time() - float(complete.get("fetched_at") or 0) < ttl:
        if complete.get("unavailable"):
            raise HistoryMonthUnavailable(f"{slug} {key} unsupported", permanent=True)
        return complete["matches"]

    def refresh(owner=None):
        try:
            rows = _normalize(slug, finished_events(
                slug, first.strftime("%Y%m%d"), last.strftime("%Y%m%d"), limit=900))
            payload = {"_cache_schema": SCHEMA, "slug": slug, "month": key,
                       "fetched_at": time.time(), "complete": True,
                       "provider_status": 200, "matches": rows}
        except HistoryMonthUnavailable as exc:
            if not exc.permanent:
                if complete and not complete.get("unavailable"):
                    return complete["matches"]
                raise
            payload = {"_cache_schema": SCHEMA, "slug": slug, "month": key,
                       "fetched_at": time.time(), "complete": True,
                       "provider_status": exc.status_code,
                       "unavailable": True, "matches": []}
        if owner and not shared_history_store.promote(
                cache_key, SCHEMA, payload, owner, required="matches"):
            if complete and not complete.get("unavailable"):
                return complete["matches"]
            raise HistoryMonthUnavailable(f"{slug} {key} lost refresh claim")
        replace_complete(path, payload, SCHEMA, required="matches")
        if payload.get("unavailable"):
            raise HistoryMonthUnavailable(f"{slug} {key} unsupported", permanent=True)
        return payload["matches"]

    if shared_history_store.production_shared():
        with shared_history_store.claim(cache_key, SCHEMA) as owner:
            if owner:
                return refresh(owner)
    else:
        with local_refresh_claim(path) as acquired:
            if acquired:
                return refresh()
    if complete and not complete.get("unavailable"):
        return complete["matches"]
    raise HistoryMonthUnavailable(f"{slug} {key} refresh in progress")


def finished_matches(slug: str, start: str, end: str, *,
                     as_of: datetime | None = None) -> list[dict]:
    first = datetime.strptime(start, "%Y%m%d").date()
    last = datetime.strptime(end, "%Y%m%d").date()
    if last < first:
        return []
    month = first.replace(day=1)
    seen = set()
    out = []
    while month <= last:
        for row in _month(slug, month.strftime("%Y%m"), as_of=as_of):
            if first.isoformat() <= row["date"] <= last.isoformat() and row["id"] not in seen:
                seen.add(row["id"])
                out.append(row)
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out
