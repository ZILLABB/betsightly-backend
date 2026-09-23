"""
Team form and head-to-head, rebuilt from ESPN results.

The trained models want 25 features. Six of them (the market probabilities and
the league tier) we already have on every fixture. The other nineteen are form
and head-to-head — goals scored and conceded over the last five, home-only and
away-only splits, previous meetings — and ESPN hands us none of that directly.
The scoreboard carries a five-character form string ("WWLLD") and nothing about
goals, so the history has to be assembled from finished matches.

Same source and the same monthly-fetch path as base_rates, run in parallel and
cached on disk. The window
is longer here because a team needs its own last ten matches, not a league
average, and a side playing weekly needs about three months to accumulate them.

Everything degrades to a neutral value rather than failing. A team we have
never seen returns league-average form, which is what the models were trained
to receive for an unknown side anyway — the alternative is refusing to predict
on exactly the obscure fixtures that make up most of the card.
"""

import json
import logging
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

from leagues.cache_paths import cache_path
from leagues.competition_registry import competition_for, regulation_score

logger = logging.getLogger(__name__)

CACHE_PATH = cache_path(Path(__file__).parent / "data" / "team_history.json")
CACHE_TTL = 12 * 3600
LOOKBACK_DAYS = 120
HISTORY_CACHE_SCHEMA = 2  # ESPN monthly queries; schema 1 used rejected date ranges

# Neutral fallbacks, used for a team with no recorded history. These are the
# global averages measured in base_rates, so an unknown side looks like an
# average side rather than a broken one.
NEUTRAL = {
    "win_rate_5": 0.40, "win_rate_10": 0.40, "draw_rate_5": 0.25,
    "goals_scored_5": 1.35, "goals_conceded_5": 1.35,
    "venue_win_rate_5": 0.40, "venue_goals_5": 1.35,
}


def _fetch_finished(slug: str, start: str, end: str, *,
                    as_of: datetime | None = None) -> list[dict]:
    """Finished matches for a league over supported monthly queries."""
    from leagues.espn_history_fetch import finished_events
    events = finished_events(slug, start, end, limit=900, as_of=as_of)

    out = []
    for ev in events:
        comp = (ev.get("competitions") or [{}])[0]
        if not comp.get("status", {}).get("type", {}).get("completed"):
            continue
        teams = comp.get("competitors", []) or []
        home = next((t for t in teams if t.get("homeAway") == "home"), None)
        away = next((t for t in teams if t.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        score = regulation_score(comp)
        if not score:
            continue
        hs, as_ = score["home_score"], score["away_score"]
        meta = competition_for(slug)
        out.append({
            "date": ev.get("date", "")[:10],
            "home": (home.get("team") or {}).get("displayName", ""),
            "away": (away.get("team") or {}).get("displayName", ""),
            "hs": hs, "as": as_,
            "team_type": meta.team_type if meta else "CLUB",
        })
    return out


def build(slugs: dict[str, str] | None = None, *,
          as_of: datetime | None = None) -> dict:
    """Fetch and index results. Returns {"matches": [...], "built_at": ...}."""
    if slugs is None:
        from leagues.espn_source import ESPN_CLUB_LEAGUES
        slugs = ESPN_CLUB_LEAGUES

    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    now = now.astimezone(timezone.utc)
    start = (now - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")

    from leagues.espn_history_fetch import HistoryMonthUnavailable
    matches: list[dict] = []
    failed_leagues = []
    unavailable_leagues = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(_fetch_finished, s, start, end,
                               as_of=as_of): s for s in slugs}
        for fut in as_completed(futures):
            try:
                matches.extend(fut.result())
            except HistoryMonthUnavailable as exc:
                (unavailable_leagues if exc.permanent else failed_leagues).append(
                    futures[fut])
                continue
            except Exception:
                failed_leagues.append(futures[fut])
                continue

    matches.sort(key=lambda m: m["date"])
    logger.info(f"team history: {len(matches)} finished matches over {LOOKBACK_DAYS} days")
    return {"matches": matches, "built_at": now.isoformat(),
            "failed_leagues": sorted(failed_leagues),
            "unavailable_leagues": sorted(unavailable_leagues),
            "_cache_schema": HISTORY_CACHE_SCHEMA}


def load(force: bool = False, *, as_of: datetime | None = None,
         allow_refresh: bool = True) -> dict:
    """Cached history, rebuilt when stale."""
    from leagues.history_cache_io import (local_refresh_claim, read_complete,
                                          replace_complete)
    complete = read_complete(CACHE_PATH, HISTORY_CACHE_SCHEMA,
                             required="matches") if as_of is None else None
    if as_of is None and not force and complete:
        try:
            if time.time() - CACHE_PATH.stat().st_mtime < CACHE_TTL:
                return complete
        except Exception:
            pass
    if as_of is None and not allow_refresh:
        return complete or {"matches": []}

    def refresh():
        data = build(as_of=as_of)
        if data.get("failed_leagues") and as_of is None:
            logger.warning("Team-history refresh incomplete: %s leagues failed",
                           len(data["failed_leagues"]))
            return complete or data
        if data.get("matches") and as_of is None:
            replace_complete(CACHE_PATH, data, HISTORY_CACHE_SCHEMA,
                             required="matches")
        return data

    try:
        if as_of is not None:
            return refresh()
        with local_refresh_claim(CACHE_PATH) as acquired:
            if not acquired:
                return complete or {"matches": []}
            return refresh()
    except Exception as e:
        logger.warning(f"team history build failed: {e}")
        return complete or {"matches": []}


class HistoryIndex:
    """Per-team and head-to-head lookups over the fetched results."""

    def __init__(self, data: dict | None = None):
        data = data or load()
        self.by_team: dict[str, list[dict]] = defaultdict(list)
        self.h2h: dict[tuple, list[dict]] = defaultdict(list)

        for m in data.get("matches", []):
            h, a = m["home"], m["away"]
            team_type = m.get("team_type") or "CLUB"
            # Each match is recorded from both sides, so "last five" means the
            # team's own last five whether they were home or away.
            self.by_team[(team_type, h)].append({"venue": "home", "gf": m["hs"], "ga": m["as"],
                                    "date": m["date"]})
            self.by_team[(team_type, a)].append({"venue": "away", "gf": m["as"], "ga": m["hs"],
                                    "date": m["date"]})
            self.h2h[(team_type, *sorted((h, a)))].append(m)

        for rows in self.by_team.values():
            rows.sort(key=lambda r: r["date"], reverse=True)

    # ── team form ──────────────────────────────────────────

    def team_form(self, team: str, venue: str, team_type: str = "CLUB") -> dict:
        """Form features for one team. Neutral values when unseen."""
        rows = self.by_team.get((team_type, team)) or []
        if not rows:
            return dict(NEUTRAL)

        def rates(sub: list[dict]) -> tuple[float, float, float, float]:
            if not sub:
                return (NEUTRAL["win_rate_5"], NEUTRAL["draw_rate_5"],
                        NEUTRAL["goals_scored_5"], NEUTRAL["goals_conceded_5"])
            wins = sum(1 for r in sub if r["gf"] > r["ga"])
            draws = sum(1 for r in sub if r["gf"] == r["ga"])
            return (wins / len(sub), draws / len(sub),
                    sum(r["gf"] for r in sub) / len(sub),
                    sum(r["ga"] for r in sub) / len(sub))

        w5, d5, gf5, ga5 = rates(rows[:5])
        w10, _, _, _ = rates(rows[:10])
        venue_rows = [r for r in rows if r["venue"] == venue][:5]
        vw, _, vgf, _ = rates(venue_rows)

        return {
            "win_rate_5": w5, "win_rate_10": w10, "draw_rate_5": d5,
            "goals_scored_5": gf5, "goals_conceded_5": ga5,
            "venue_win_rate_5": vw, "venue_goals_5": vgf,
        }

    # ── head to head ───────────────────────────────────────

    def head_to_head(self, home: str, away: str, window: int = 10,
                     team_type: str = "CLUB") -> dict:
        """Previous meetings, oriented so `home` is the reference team."""
        meetings = (self.h2h.get((team_type, *sorted((home, away)))) or [])[-window:]
        if not meetings:
            # No meetings is a real, common state and the models saw it in
            # training as zero meetings with neutral rates.
            return {"home_win_rate": 0.40, "avg_goals": 2.70,
                    "btts_rate": 0.52, "meetings": 0}

        wins = goals = btts = 0
        for m in meetings:
            total = m["hs"] + m["as"]
            goals += total
            if m["hs"] >= 1 and m["as"] >= 1:
                btts += 1
            ref_gf = m["hs"] if m["home"] == home else m["as"]
            ref_ga = m["as"] if m["home"] == home else m["hs"]
            if ref_gf > ref_ga:
                wins += 1
        n = len(meetings)
        return {"home_win_rate": wins / n, "avg_goals": goals / n,
                "btts_rate": btts / n, "meetings": n}

    def coverage(self) -> dict:
        return {"teams": len(self.by_team), "h2h_pairs": len(self.h2h),
                "matches": sum(len(v) for v in self.by_team.values()) // 2}
