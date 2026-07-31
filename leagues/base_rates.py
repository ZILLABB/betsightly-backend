"""
Per-league base rates measured from real recent results.

Why this exists: the previous goals model used one universal expected-total
(~2.6 goals) for every fixture, so Over 1.5 always scored ~73% regardless of
who was playing. Measured against reality that number is wildly league
dependent — Argentina's Primera runs 51.9% Over 1.5 while Norway's
Eliteserien runs 84.0%. Publishing "73%" on Argentine games was the direct
cause of the July losing streak.

This module fetches finished matches from ESPN (free) for each league,
computes the actual hit rates, and caches them. Predictions are anchored to
these measured rates and then adjusted by team strength, instead of being
invented from a constant.

Leagues with too few recent matches fall back to GLOBAL_DEFAULTS, which are
themselves measured across every tracked league.
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

CACHE_PATH = Path(__file__).parent / "data" / "league_base_rates.json"
CACHE_TTL = 7 * 24 * 3600          # recompute weekly
LOOKBACK_DAYS = 45                 # sample window
MIN_SAMPLE = 10                    # below this, use global defaults

# Measured across all tracked leagues (see module docstring).
GLOBAL_DEFAULTS = {
    "matches": 0,
    "avg_goals": 2.70,
    "over_1_5": 0.734,
    "over_2_5": 0.549,
    "home_win": 0.474,
    "draw": 0.231,
    "away_win": 0.295,
    "btts": 0.526,
    "home_goals": 1.50,
    "away_goals": 1.20,
}


def _empty():
    return {
        "n": 0, "goals": 0, "home_goals": 0, "away_goals": 0,
        "o15": 0, "o25": 0, "home": 0, "draw": 0, "away": 0, "btts": 0,
    }


def _fetch_finished_range(slug: str, start: str, end: str) -> list[tuple[int, int]]:
    """Finished (home, away) scores for a whole date range in one request.

    ESPN accepts dates=YYYYMMDD-YYYYMMDD, so a 45-day window costs one call
    per league instead of 45 — the difference between a ~35-minute refresh
    and a few seconds.
    """
    try:
        resp = requests.get(
            f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard",
            params={"dates": f"{start}-{end}", "limit": 500}, timeout=25,
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
        try:
            out.append((int(home.get("score", 0)), int(away.get("score", 0))))
        except (TypeError, ValueError):
            continue
    return out


def compute_base_rates(slugs: dict[str, str]) -> dict:
    """Measure base rates for each league slug. Leagues run in parallel."""
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")
    end = (now - timedelta(days=1)).strftime("%Y%m%d")

    raw = {}
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(_fetch_finished_range, slug, start, end): slug for slug in slugs}
        for fut in as_completed(futures):
            slug = futures[fut]
            try:
                results = fut.result()
            except Exception:
                continue
            s = _empty()
            for hs, as_ in results:
                total = hs + as_
                s["n"] += 1
                s["goals"] += total
                s["home_goals"] += hs
                s["away_goals"] += as_
                if total >= 2:
                    s["o15"] += 1
                if total >= 3:
                    s["o25"] += 1
                if hs > as_:
                    s["home"] += 1
                elif hs == as_:
                    s["draw"] += 1
                else:
                    s["away"] += 1
                if hs >= 1 and as_ >= 1:
                    s["btts"] += 1
            raw[slug] = s

    rates = {}
    for slug, s in raw.items():
        n = s["n"]
        if n < MIN_SAMPLE:
            continue
        rates[slug] = {
            "matches": n,
            "avg_goals": round(s["goals"] / n, 3),
            "over_1_5": round(s["o15"] / n, 4),
            "over_2_5": round(s["o25"] / n, 4),
            "home_win": round(s["home"] / n, 4),
            "draw": round(s["draw"] / n, 4),
            "away_win": round(s["away"] / n, 4),
            "btts": round(s["btts"] / n, 4),
            "home_goals": round(s["home_goals"] / n, 3),
            "away_goals": round(s["away_goals"] / n, 3),
        }
    return rates


def get_base_rates(slugs: dict[str, str] | None = None, force: bool = False) -> dict:
    """Cached per-league base rates. Recomputed weekly."""
    if not force and CACHE_PATH.exists():
        try:
            age = time.time() - CACHE_PATH.stat().st_mtime
            if age < CACHE_TTL:
                return json.loads(CACHE_PATH.read_text())
        except Exception:
            pass

    if slugs is None:
        from leagues.espn_source import ESPN_CLUB_LEAGUES
        slugs = ESPN_CLUB_LEAGUES

    try:
        rates = compute_base_rates(slugs)
        if rates:
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            CACHE_PATH.write_text(json.dumps(rates, indent=2))
            logger.info(f"Base rates computed for {len(rates)} leagues")
            return rates
    except Exception as e:
        logger.error(f"Base-rate computation failed: {e}")

    # Fall back to whatever is cached, even if stale
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except Exception:
            pass
    return {}


# Strength of the pull toward global averages, in "virtual matches". A league
# with SHRINKAGE_K real matches is weighted 50/50 against the global rate.
SHRINKAGE_K = 25


def rates_for(slug: str, cached: dict | None = None) -> dict:
    """Base rates for one league, shrunk toward global averages.

    A league measured over 11 matches can easily read 76% Over 1.5 when its
    true rate is nearer 60% — sampling noise, not signal. Publishing that raw
    number is how a market gets overclaimed. Weighting the league's own rate
    against the global one by sample size keeps thin leagues honest while
    letting well-sampled leagues (Argentina at 27+ matches) keep their real,
    very different profile.
    """
    if cached is None:
        cached = get_base_rates()
    r = cached.get(slug)
    if not r or r.get("matches", 0) < MIN_SAMPLE:
        return dict(GLOBAL_DEFAULTS)

    n = r.get("matches", 0)
    w = n / (n + SHRINKAGE_K)
    out = {"matches": n}
    for key, global_val in GLOBAL_DEFAULTS.items():
        if key == "matches":
            continue
        league_val = r.get(key, global_val)
        out[key] = round(w * league_val + (1 - w) * global_val, 4)
    return out
