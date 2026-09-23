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

from leagues.competition_registry import regulation_score
from leagues.cache_paths import cache_path

logger = logging.getLogger(__name__)

CACHE_PATH = cache_path(Path(__file__).parent / "data" / "league_base_rates.json")
CACHE_TTL = 7 * 24 * 3600          # recompute weekly
HISTORY_CACHE_SCHEMA = 2  # ESPN monthly queries; schema 1 used rejected date ranges
LOOKBACK_DAYS = 45                 # sample window
MIN_SAMPLE = 10                    # below this, use global defaults
MIN_PRIOR_SAMPLE = 20

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


def _merge(target: dict, source: dict) -> None:
    for key in target:
        target[key] += int(source.get(key) or 0)


def _as_rates(sample: dict) -> dict:
    n = int(sample.get("n") or 0)
    if not n:
        return {**GLOBAL_DEFAULTS, "matches": 0}
    return {
        "matches": n,
        "avg_goals": round(sample["goals"] / n, 3),
        "over_1_5": round(sample["o15"] / n, 4),
        "over_2_5": round(sample["o25"] / n, 4),
        "home_win": round(sample["home"] / n, 4),
        "draw": round(sample["draw"] / n, 4),
        "away_win": round(sample["away"] / n, 4),
        "btts": round(sample["btts"] / n, 4),
        "home_goals": round(sample["home_goals"] / n, 3),
        "away_goals": round(sample["away_goals"] / n, 3),
    }


def _fetch_finished_range(slug: str, start: str, end: str, *,
                          as_of: datetime | None = None) -> list[tuple[int, int]]:
    """Finished (home, away) scores from supported monthly ESPN queries."""
    from leagues.espn_history_fetch import finished_events
    events = finished_events(slug, start, end, as_of=as_of)

    out = []
    for ev in events:
        comp = (ev.get("competitions") or [{}])[0]
        if not comp.get("status", {}).get("type", {}).get("completed"):
            continue
        teams = comp.get("competitors", [])
        home = next((t for t in teams if t.get("homeAway") == "home"), None)
        away = next((t for t in teams if t.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        score = regulation_score(comp)
        if not score:
            continue
        out.append((score["home_score"], score["away_score"]))
    return out


def compute_base_rates(slugs: dict[str, str], *,
                       as_of: datetime | None = None) -> dict:
    """Measure base rates for each league slug. Leagues run in parallel."""
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    now = now.astimezone(timezone.utc)
    start = (now - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")
    end = (now - timedelta(days=1)).strftime("%Y%m%d")

    raw = {}
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(_fetch_finished_range, slug, start, end,
                               as_of=as_of): slug for slug in slugs}
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
        if s["n"]:
            rates[slug] = _as_rates(s)

    # Hierarchical priors prevent a six-match knockout sample from masquerading
    # as a stable competition rate. These are real pooled results, not invented
    # samples: region/type -> type -> club/national -> global.
    from leagues.competition_registry import competition_for
    prior_samples: dict[str, dict] = defaultdict(_empty)
    for slug, sample in raw.items():
        meta = competition_for(slug)
        if not meta or not sample["n"]:
            continue
        keys = (
            f"region_type:{meta.region}|{meta.competition_type}",
            f"competition_type:{meta.competition_type}",
            f"team_type:{meta.team_type}",
            "global",
        )
        for key in keys:
            _merge(prior_samples[key], sample)
    rates["_priors"] = {key: _as_rates(sample) for key, sample in prior_samples.items()}
    rates["_cache_schema"] = HISTORY_CACHE_SCHEMA
    return rates


def get_base_rates(slugs: dict[str, str] | None = None, force: bool = False,
                   *, as_of: datetime | None = None) -> dict:
    """Cached per-league base rates. Recomputed weekly."""
    if as_of is None and not force and CACHE_PATH.exists():
        try:
            age = time.time() - CACHE_PATH.stat().st_mtime
            if age < CACHE_TTL:
                cached = json.loads(CACHE_PATH.read_text())
                if (cached.get("_cache_schema") == HISTORY_CACHE_SCHEMA
                        and cached.get("_priors")):
                    return cached
                logger.info("Base-rate cache predates monthly ESPN history; rebuilding")
        except Exception:
            pass

    if slugs is None:
        from leagues.espn_source import ESPN_CLUB_LEAGUES
        slugs = ESPN_CLUB_LEAGUES

    try:
        rates = compute_base_rates(slugs, as_of=as_of)
        if rates:
            if as_of is None:
                CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                CACHE_PATH.write_text(json.dumps(rates, indent=2))
                logger.info(f"Base rates computed for {len(rates)} leagues")
            return rates
    except Exception as e:
        logger.error(f"Base-rate computation failed: {e}")

    # Fall back to whatever is cached, even if stale
    if as_of is None and CACHE_PATH.exists():
        try:
            cached = json.loads(CACHE_PATH.read_text())
            if cached.get("_cache_schema") == HISTORY_CACHE_SCHEMA:
                return cached
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
    from leagues.competition_registry import prior_keys
    r = cached.get(slug) or {}
    priors = cached.get("_priors") or {}
    prior = None
    source = "global_default"
    for key in prior_keys(slug):
        candidate = priors.get(key)
        if candidate and int(candidate.get("matches") or 0) >= MIN_PRIOR_SAMPLE:
            prior = candidate
            source = key
            break
    if prior is None:
        prior = GLOBAL_DEFAULTS

    n = int(r.get("matches") or 0)
    if n <= 0:
        return {**dict(prior), "matches": 0, "base_rate_source": source}

    w = n / (n + SHRINKAGE_K)
    out = {"matches": n, "base_rate_source": f"competition+{source}"}
    for key, global_val in prior.items():
        if key == "matches":
            continue
        league_val = r.get(key, global_val)
        out[key] = round(w * league_val + (1 - w) * global_val, 4)
    return out
