"""Conservative ESPN per-fixture recovery for unresolved, published predictions.

No database writes and no synthetic score or time-based voids. The caller
persists a result only after the exact teams, league and kickoff are verified.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

logger = logging.getLogger(__name__)


def _dt(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def recover_missing_espn_scores(
    picks: list[dict],
    scores: dict,
    *,
    known_slugs: set[str],
    fetch_events: Callable[[str, str], list[dict]],
    regulation_score: Callable[[dict], dict | None],
    normalize: Callable[[str], str],
    lookup_score: Callable[[dict, str, str, str], dict | None],
    now: datetime | None = None,
    max_queries: int = 12,
) -> dict:
    """Rescue only missing, past-due scores with an exact competition/fixture match.

    ESPN wide-range scoreboards may omit specific events even when another
    competition returns results. Retry the *known published league* on the
    fixture day, then adjacent days if ESPN assigned it a different local day.
    The actual event kickoff must be within 12h of the archived UTC kickoff.
    Identical-looking rematches and one-team fuzzy matches never qualify.
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    out = dict(scores)
    unresolved: list[tuple[dict, datetime, str]] = []

    for pick in picks:
        if pick.get("status") in ("won", "lost", "void"):
            continue
        kickoff = _dt(pick.get("commence_time") or pick.get("kickoff") or pick.get("date"))
        slug = str(pick.get("league_slug") or "").strip()
        home = str(pick.get("home_team") or "")
        away = str(pick.get("away_team") or "")
        if not (kickoff and slug in known_slugs and normalize(home) and normalize(away)):
            continue
        if kickoff + timedelta(hours=3) > current:
            continue
        if lookup_score(out, home, away, kickoff.date().isoformat()):
            continue
        unresolved.append((pick, kickoff, slug))

    if not unresolved:
        return out

    def lookup_event(pick: dict, kickoff: datetime, events: list[dict]):
        matches: list[dict] = []
        expected_home = normalize(str(pick.get("home_team") or ""))
        expected_away = normalize(str(pick.get("away_team") or ""))
        for event in events:
            competition = (event.get("competitions") or [{}])[0]
            status = ((competition.get("status") or event.get("status") or {})
                      .get("type") or {})
            if not status.get("completed"):
                continue
            event_kickoff = _dt(event.get("date") or competition.get("date"))
            if not event_kickoff or abs((event_kickoff - kickoff).total_seconds()) > 12 * 3600:
                continue
            teams = competition.get("competitors") or []
            homes = [t for t in teams if t.get("homeAway") == "home"]
            aways = [t for t in teams if t.get("homeAway") == "away"]
            if len(homes) != 1 or len(aways) != 1:
                continue
            home = str((homes[0].get("team") or {}).get("displayName") or "")
            away = str((aways[0].get("team") or {}).get("displayName") or "")
            if normalize(home) != expected_home or normalize(away) != expected_away:
                continue
            result = regulation_score(competition)
            if result is None or result.get("home_score") is None or result.get("away_score") is None:
                continue
            try:
                hs, aws = int(result["home_score"]), int(result["away_score"])
            except (TypeError, ValueError):
                continue
            if hs < 0 or aws < 0:
                continue
            matches.append({
                "home": home, "away": away, "home_score": hs, "away_score": aws,
                "completed": True, "source": "espn_single_day_verified",
                "provider_event_id": str(event.get("id") or ""),
                "event_kickoff": event_kickoff.isoformat(),
                **{key: result.get(key) for key in (
                    "score_90", "score_extra_time", "penalty_score",
                    "qualified_team", "match_status",
                )},
            })
        # If ESPN returns conflicting event records, do not choose at random.
        identities = {(m["provider_event_id"], m["event_kickoff"],
                       m["home_score"], m["away_score"]) for m in matches}
        return matches[0] if len(identities) == 1 else None

    # Rotate priority hourly so a persistently missing old result does not
    # consume every retry budget forever. Every invocation is bounded, and
    # all fetches within a phase run concurrently.
    unresolved.sort(key=lambda entry: entry[1])
    rotation = int(current.timestamp() // 3600) % len(unresolved)
    unresolved = unresolved[rotation:] + unresolved[:rotation]

    fetched: dict[tuple[str, str], list[dict]] = {}
    queries = 0
    remaining = list(unresolved)
    for offset in (0, -1, 1):
        if not remaining or queries >= max_queries:
            break
        requested: list[tuple[str, str]] = []
        for _pick, kickoff, slug in remaining:
            day = (kickoff + timedelta(days=offset)).strftime("%Y%m%d")
            key = (slug, day)
            if key not in fetched and key not in requested:
                if queries + len(requested) >= max_queries:
                    break
                requested.append(key)
        if requested:
            # fetch_events is an injected, time-limited provider call. No
            # database writes occur here; failures remain pending.
            def fetch(key: tuple[str, str]) -> tuple[tuple[str, str], list[dict]]:
                try:
                    return key, fetch_events(*key) or []
                except Exception as exc:
                    logger.warning("Score recovery fetch failed league=%s date=%s error=%s",
                                   key[0], key[1], type(exc).__name__)
                    return key, []
            with ThreadPoolExecutor(max_workers=min(12, len(requested))) as pool:
                for key, events in pool.map(fetch, requested):
                    fetched[key] = events
            queries += len(requested)

        next_remaining: list[tuple[dict, datetime, str]] = []
        for pick, kickoff, slug in remaining:
            date = kickoff.date().isoformat()
            if lookup_score(out, pick.get("home_team", ""), pick.get("away_team", ""), date):
                continue
            day = (kickoff + timedelta(days=offset)).strftime("%Y%m%d")
            match = lookup_event(pick, kickoff, fetched.get((slug, day), []))
            if match is None:
                next_remaining.append((pick, kickoff, slug))
                continue
            score_key = "|".join((normalize(str(pick.get("home_team") or "")),
                                  normalize(str(pick.get("away_team") or "")), date))
            if score_key in out and (out[score_key]["home_score"], out[score_key]["away_score"]) != (match["home_score"], match["away_score"]):
                logger.error("Conflicting final scores for %s; leaving result untouched", score_key)
                continue
            out[score_key] = match
            logger.info("Verified missing score league=%s event=%s fixture=%s", slug,
                        match["provider_event_id"], score_key)
        remaining = next_remaining
    if remaining and queries >= max_queries:
        logger.warning("Score recovery request cap reached; unresolved fixtures remain pending")
    return out
