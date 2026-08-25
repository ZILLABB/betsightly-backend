"""
Team form and head-to-head, rebuilt from ESPN results.

The trained models want 25 features. Six of them (the market probabilities and
the league tier) we already have on every fixture. The other nineteen are form
and head-to-head — goals scored and conceded over the last five, home-only and
away-only splits, previous meetings — and ESPN hands us none of that directly.
The scoreboard carries a five-character form string ("WWLLD") and nothing about
goals, so the history has to be assembled from finished matches.

Same source and the same ranged-fetch trick as base_rates: one request per
league covering the whole window, run in parallel, cached on disk. The window
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

import requests

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).parent / "data" / "team_history.json"
CACHE_TTL = 12 * 3600
LOOKBACK_DAYS = 120
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"

# Neutral fallbacks, used for a team with no recorded history. These are the
# global averages measured in base_rates, so an unknown side looks like an
# average side rather than a broken one.
NEUTRAL = {
    "win_rate_5": 0.40, "win_rate_10": 0.40, "draw_rate_5": 0.25,
    "goals_scored_5": 1.35, "goals_conceded_5": 1.35,
    "venue_win_rate_5": 0.40, "venue_goals_5": 1.35,
}


def _fetch_finished(slug: str, start: str, end: str) -> list[dict]:
    """Finished matches for a league over a date range, in one request."""
    try:
        resp = requests.get(SCOREBOARD.format(slug=slug),
                            params={"dates": f"{start}-{end}", "limit": 900},
                            timeout=25)
        if resp.status_code != 200:
            return []
        events = resp.json().get("events", []) or []
    except Exception:
        return []

    out = []
    for ev in events:
        comp = (ev.get("competitions") or [{}])[0]
        if comp.get("status", {}).get("type", {}).get("name") != "STATUS_FULL_TIME":
            continue
        teams = comp.get("competitors", []) or []
        home = next((t for t in teams if t.get("homeAway") == "home"), None)
        away = next((t for t in teams if t.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        try:
            hs, as_ = int(home.get("score", 0)), int(away.get("score", 0))
        except (TypeError, ValueError):
            continue
        out.append({
            "date": ev.get("date", "")[:10],
            "home": (home.get("team") or {}).get("displayName", ""),
            "away": (away.get("team") or {}).get("displayName", ""),
            "hs": hs, "as": as_,
        })
    return out


def build(slugs: dict[str, str] | None = None) -> dict:
    """Fetch and index results. Returns {"matches": [...], "built_at": ...}."""
    if slugs is None:
        from leagues.espn_source import ESPN_CLUB_LEAGUES
        slugs = ESPN_CLUB_LEAGUES

    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")

    matches: list[dict] = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(_fetch_finished, s, start, end): s for s in slugs}
        for fut in as_completed(futures):
            try:
                matches.extend(fut.result())
            except Exception:
                continue

    matches.sort(key=lambda m: m["date"])
    logger.info(f"team history: {len(matches)} finished matches over {LOOKBACK_DAYS} days")
    return {"matches": matches, "built_at": now.isoformat()}


def load(force: bool = False) -> dict:
    """Cached history, rebuilt when stale."""
    if not force and CACHE_PATH.exists():
        try:
            if time.time() - CACHE_PATH.stat().st_mtime < CACHE_TTL:
                return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    try:
        data = build()
        if data.get("matches"):
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data
    except Exception as e:
        logger.warning(f"team history build failed: {e}")
        if CACHE_PATH.exists():
            try:
                return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"matches": []}


class HistoryIndex:
    """Per-team and head-to-head lookups over the fetched results."""

    def __init__(self, data: dict | None = None):
        data = data or load()
        self.by_team: dict[str, list[dict]] = defaultdict(list)
        self.h2h: dict[tuple, list[dict]] = defaultdict(list)

        for m in data.get("matches", []):
            h, a = m["home"], m["away"]
            # Each match is recorded from both sides, so "last five" means the
            # team's own last five whether they were home or away.
            self.by_team[h].append({"venue": "home", "gf": m["hs"], "ga": m["as"],
                                    "date": m["date"]})
            self.by_team[a].append({"venue": "away", "gf": m["as"], "ga": m["hs"],
                                    "date": m["date"]})
            self.h2h[tuple(sorted((h, a)))].append(m)

        for rows in self.by_team.values():
            rows.sort(key=lambda r: r["date"], reverse=True)

    # ── team form ──────────────────────────────────────────

    def team_form(self, team: str, venue: str) -> dict:
        """Form features for one team. Neutral values when unseen."""
        rows = self.by_team.get(team) or []
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

    def head_to_head(self, home: str, away: str, window: int = 10) -> dict:
        """Previous meetings, oriented so `home` is the reference team."""
        meetings = (self.h2h.get(tuple(sorted((home, away)))) or [])[-window:]
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
