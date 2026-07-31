"""
ELO ratings computed from ESPN results, keyed by ESPN team names.

Why this replaces models/api_football/elo_ratings.json: that file is a static
767-team snapshot pulled from API-Football, so its names follow a different
convention than the fixtures we actually publish. Measured against today's
slate only 46% of teams resolved — Peru, Chile, Colombia, Ecuador, Uruguay and
the EFL Cup matched almost nothing, meaning every pick in those leagues was
pure league average with no team strength behind it at all.

Building ratings from the same feed that supplies the fixtures removes the
name-matching problem by construction: a team is stored under exactly the
string ESPN will hand us tomorrow. It also stays current, since it is
recomputed from recent results rather than frozen at export time.

Ratings are league-scoped. Cross-league fixtures (Libertadores, Champions
League) compare teams that never play each other domestically, so a rating
earned in one league is not directly comparable to another's; callers get a
same-league flag and can fall back to base rates when it is False.
"""

import json
import logging
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).parent / "data" / "espn_elo.json"
CACHE_TTL = 3 * 24 * 3600      # rebuild every 3 days
HISTORY_DAYS = 240             # ~a full season of results
DEFAULT_RATING = 1500.0
K_FACTOR = 20.0
HOME_ADVANTAGE = 60.0
MIN_MATCHES = 3                # below this a team's rating is not trusted


def _american_to_decimal(american) -> float | None:
    """DraftKings quotes American odds; everything downstream expects decimal."""
    try:
        a = float(str(american).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if a == 0:
        return None
    return round((a / 100.0) + 1.0, 3) if a > 0 else round((100.0 / abs(a)) + 1.0, 3)


def _fetch_results(slug: str, start: str, end: str) -> list[dict]:
    """Finished matches with names and scores, oldest first."""
    try:
        resp = requests.get(
            f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard",
            params={"dates": f"{start}-{end}", "limit": 900}, timeout=30,
        )
        if resp.status_code != 200:
            return []
        events = resp.json().get("events", [])
    except Exception:
        return []

    out = []
    for ev in events:
        comp = (ev.get("competitions") or [{}])[0]
        if comp.get("status", {}).get("type", {}).get("name") != "STATUS_FULL_TIME":
            continue
        teams = comp.get("competitors", [])
        home = next((t for t in teams if t.get("homeAway") == "home"), None)
        away = next((t for t in teams if t.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        hn = (home.get("team") or {}).get("displayName", "")
        an = (away.get("team") or {}).get("displayName", "")
        if not hn or not an:
            continue
        try:
            hs, as_ = int(home.get("score", 0)), int(away.get("score", 0))
        except (TypeError, ValueError):
            continue
        out.append({"date": ev.get("date", ""), "home": hn, "away": an,
                    "hs": hs, "as": as_})
    out.sort(key=lambda m: m["date"])
    return out


def _run_elo(matches: list[dict]) -> tuple[dict, dict]:
    """Standard ELO with a goal-difference multiplier. Returns (ratings, counts)."""
    ratings: dict[str, float] = defaultdict(lambda: DEFAULT_RATING)
    counts: dict[str, int] = defaultdict(int)

    for m in matches:
        h, a = m["home"], m["away"]
        rh, ra = ratings[h], ratings[a]
        exp_h = 1.0 / (1.0 + 10 ** (-((rh + HOME_ADVANTAGE) - ra) / 400.0))

        hs, as_ = m["hs"], m["as"]
        score_h = 1.0 if hs > as_ else (0.5 if hs == as_ else 0.0)

        # A 3-0 says more than a 1-0; standard multiplier used by club ELO systems.
        gd = abs(hs - as_)
        mult = 1.0 if gd <= 1 else (1.5 if gd == 2 else (1.75 + (gd - 3) / 8.0))

        delta = K_FACTOR * mult * (score_h - exp_h)
        ratings[h] = rh + delta
        ratings[a] = ra - delta
        counts[h] += 1
        counts[a] += 1

    return dict(ratings), dict(counts)


def build_ratings(slugs: dict[str, str]) -> dict:
    """Compute per-league ELO from ESPN history. {slug: {team: {rating, matches}}}"""
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=HISTORY_DAYS)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")

    def work(slug):
        return slug, _fetch_results(slug, start, end)

    out = {}
    with ThreadPoolExecutor(max_workers=12) as pool:
        for slug, matches in pool.map(work, slugs):
            if len(matches) < 10:
                continue
            ratings, counts = _run_elo(matches)
            out[slug] = {
                team: {"rating": round(r, 1), "matches": counts.get(team, 0)}
                for team, r in ratings.items()
            }
    return out


def get_ratings(slugs: dict[str, str] | None = None, force: bool = False) -> dict:
    """Cached ESPN-derived ELO, rebuilt every CACHE_TTL."""
    if not force and CACHE_PATH.exists():
        try:
            if time.time() - CACHE_PATH.stat().st_mtime < CACHE_TTL:
                return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    if slugs is None:
        from leagues.club_fixtures import ESPN_CLUB_LEAGUES
        slugs = ESPN_CLUB_LEAGUES

    try:
        ratings = build_ratings(slugs)
        if ratings:
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            CACHE_PATH.write_text(json.dumps(ratings, ensure_ascii=False), encoding="utf-8")
            total = sum(len(v) for v in ratings.values())
            logger.info(f"ESPN ELO built: {total} teams across {len(ratings)} leagues")
            return ratings
    except Exception as e:
        logger.error(f"ELO build failed: {e}")

    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def rating_for(slug: str, team: str, all_ratings: dict) -> float | None:
    """Team's rating within its league, or None if unrated / too few matches."""
    entry = (all_ratings.get(slug) or {}).get(team)
    if not entry or entry.get("matches", 0) < MIN_MATCHES:
        return None
    return entry.get("rating")
