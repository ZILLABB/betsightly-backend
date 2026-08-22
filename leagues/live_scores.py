"""
Live scores for fixtures on today's card.

ESPN's scoreboard already carries the score, the state and the clock for every
match it lists, and the card is built from that same feed — so this needs no
new data source and no new key, just a second read of what we already use.

Keyed by the card's own `match_id`, which is an md5 of home + away +
commence_time. Rebuilding the id the same way means a score lands on the right
pick without any name matching, which is where this sort of thing usually goes
wrong.

Deliberately separate from the card. The card is locked at 08:00 and must not
change; a score is live and changes every few minutes. Merging them would
force a choice between a stale score and a card that rewrites itself, so they
are fetched apart and joined in the client.
"""

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
TIMEOUT = 12

# ESPN state -> what a reader needs to know.
STATE_LABEL = {"pre": "not started", "in": "live", "post": "finished"}


def _normalise_commence(raw: str) -> str:
    """Match espn_source's timestamp normalisation exactly.

    ESPN returns kick-offs without seconds ("2026-07-31T23:30Z") and
    espn_source pads them to "...:30:00Z" before hashing. Reconstructing the id
    from the raw value produces a different md5 for every fixture, which is
    what made the first version of this match nothing at all.
    """
    if raw.endswith("Z") and len(raw) == 17:
        return raw[:-1] + ":00Z"
    return raw


def _match_id(home: str, away: str, commence: str) -> str:
    return hashlib.md5(
        f"{home}{away}{_normalise_commence(commence)}".encode()
    ).hexdigest()


def _fetch_league(slug: str, date_str: str) -> list[dict]:
    try:
        resp = requests.get(SCOREBOARD.format(slug=slug),
                            params={"dates": date_str}, timeout=TIMEOUT)
        if resp.status_code != 200:
            return []
        return resp.json().get("events", []) or []
    except Exception:
        return []


def _parse(event: dict) -> dict | None:
    comp = (event.get("competitions") or [{}])[0]
    teams = comp.get("competitors", []) or []
    home = next((t for t in teams if t.get("homeAway") == "home"), None)
    away = next((t for t in teams if t.get("homeAway") == "away"), None)
    if not home or not away:
        return None

    status = comp.get("status", {}) or {}
    stype = status.get("type", {}) or {}
    state = stype.get("state") or "pre"

    commence = event.get("date") or comp.get("date") or ""
    home_name = (home.get("team") or {}).get("displayName") or ""
    away_name = (away.get("team") or {}).get("displayName") or ""

    def score(side):
        try:
            return int(side.get("score"))
        except (TypeError, ValueError):
            return None

    return {
        "match_id": _match_id(home_name, away_name, commence),
        "home_team": home_name,
        "away_team": away_name,
        "home_score": score(home),
        "away_score": score(away),
        "state": state,
        "state_label": STATE_LABEL.get(state, state),
        "detail": stype.get("shortDetail") or stype.get("description"),
        "clock": status.get("displayClock"),
        "period": status.get("period"),
        "finished": state == "post",
        "live": state == "in",
    }


def scores_for(slugs: list[str], date_str: str | None = None) -> dict:
    """Scores keyed by match_id for the given league slugs."""
    date_str = date_str or datetime.now(timezone.utc).strftime("%Y%m%d")
    out: dict[str, dict] = {}
    if not slugs:
        return out

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_fetch_league, s, date_str): s for s in set(slugs)}
        for fut in as_completed(futures):
            try:
                events = fut.result()
            except Exception:
                continue
            for ev in events:
                parsed = _parse(ev)
                if parsed:
                    out[parsed["match_id"]] = parsed
    return out


def scores_for_card() -> dict:
    """Scores for every fixture on today's card.

    Dates come from the card's own fixtures, not from the clock. Fetching
    "today and tomorrow" looked right and was wrong: at 02:13 UTC the card
    still carries the previous evening's late kick-offs, that date was never
    requested, and every one of those matches reported no score — which the
    frontend renders as a permanent "in play". Asking for the dates the
    fixtures actually fall on is correct at any hour.

    Only the leagues on the card are fetched, so this stays a handful of
    requests rather than a sweep of all 91.
    """
    try:
        from leagues.daily_feed import build_daily_accumulators

        card = build_daily_accumulators()
        if not card:
            return {"scores": {}, "leagues": [], "dates": []}

        slugs: set[str] = set()
        ids: set[str] = set()
        dates: set[str] = set()
        for cat in (card.get("accumulators") or {}).values():
            if not isinstance(cat, dict):
                continue
            games = list(cat.get("games") or [])
            for day in cat.get("chain") or []:
                games.extend(day.get("picks") or [])
            for g in games:
                if g.get("league_slug"):
                    slugs.add(g["league_slug"])
                if g.get("match_id"):
                    ids.add(g["match_id"])
                kickoff = g.get("kickoff") or g.get("commence_time") or ""
                if len(kickoff) >= 10:
                    dates.add(kickoff[:10])

        # A late kick-off can land in ESPN's next local day, so each fixture
        # date is asked for alongside the day after it.
        wanted: set[str] = set()
        for d in dates:
            try:
                day = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except Exception:
                continue
            wanted.add(day.strftime("%Y%m%d"))
            wanted.add((day + timedelta(days=1)).strftime("%Y%m%d"))

        found: dict[str, dict] = {}
        for date_str in sorted(wanted):
            found.update(scores_for(sorted(slugs), date_str))

        return {
            "scores": {k: v for k, v in found.items() if k in ids},
            "leagues": sorted(slugs),
            "dates": sorted(dates),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.warning(f"live scores unavailable: {e}")
        return {"scores": {}, "leagues": [], "dates": [], "error": str(e)}
