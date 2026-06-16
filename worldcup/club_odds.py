"""
Multi-league club odds fetcher + safe-pick generator.

Pulls real bookmaker odds from The Odds API for active club leagues.
Caches per-league for 6 hours to stay within free-tier budget (500/mo).

This module is read-only relative to other code — it does not modify
any global state. Safe to import; safe to call repeatedly.
"""

import os
import json
import logging
import requests
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent.parent / "cache" / "odds"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL = timedelta(hours=12)

# Active club leagues (rotates with season)
ACTIVE_LEAGUES = [
    "soccer_spain_segunda_division",
    "soccer_chile_campeonato",
    "soccer_finland_veikkausliiga",
    "soccer_league_of_ireland",
    "soccer_brazil_campeonato",
    "soccer_norway_eliteserien",
    "soccer_sweden_allsvenskan",
    "soccer_conmebol_copa_libertadores",
    "soccer_conmebol_copa_sudamericana",
]

LEAGUE_NAMES = {
    "soccer_spain_segunda_division": "La Liga 2",
    "soccer_chile_campeonato": "Primera Division - Chile",
    "soccer_finland_veikkausliiga": "Veikkausliiga - Finland",
    "soccer_league_of_ireland": "League of Ireland",
    "soccer_brazil_campeonato": "Brasileirao Serie A",
    "soccer_norway_eliteserien": "Eliteserien - Norway",
    "soccer_sweden_allsvenskan": "Allsvenskan - Sweden",
    "soccer_conmebol_copa_libertadores": "Copa Libertadores",
    "soccer_conmebol_copa_sudamericana": "Copa Sudamericana",
}


# ── Cache helpers ──────────────────────────────────────────


def _cache_path(sport_key: str) -> Path:
    return CACHE_DIR / f"{sport_key}.json"


def _cache_fresh(cache_file: Path) -> bool:
    if not cache_file.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
    return age < CACHE_TTL


def _load_cache(cache_file: Path) -> List[dict]:
    try:
        with open(cache_file) as f:
            return json.load(f)
    except Exception:
        return []


# ── Fetcher ─────────────────────────────────────────────────


def fetch_league_odds(sport_key: str, force_refresh: bool = False) -> List[dict]:
    """
    Fetch odds for one league. Uses 6h cache by default. Returns raw
    Odds-API match list (empty list on failure).
    """
    cache_file = _cache_path(sport_key)

    if not force_refresh and _cache_fresh(cache_file):
        return _load_cache(cache_file)

    api_key = os.getenv("ODDS_API_KEY", "")
    if not api_key:
        logger.warning("ODDS_API_KEY missing — using stale cache or empty")
        return _load_cache(cache_file)

    try:
        resp = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds",
            params={
                "apiKey": api_key,
                "regions": "uk,eu",
                "markets": "h2h,totals",
                "oddsFormat": "decimal",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning(f"{sport_key}: HTTP {resp.status_code} — using stale cache")
            return _load_cache(cache_file)

        data = resp.json()
        with open(cache_file, "w") as f:
            json.dump(data, f)
        logger.info(f"Fetched {len(data)} matches for {sport_key}")
        return data

    except Exception as e:
        logger.error(f"Fetch failed {sport_key}: {e} — using stale cache")
        return _load_cache(cache_file)


# ── Parser ──────────────────────────────────────────────────


def parse_match(raw: dict, league_key: str) -> Optional[dict]:
    """Convert raw Odds-API match into a normalized prediction-ready dict."""
    bookmakers = raw.get("bookmakers") or []
    if not bookmakers:
        return None

    home = raw.get("home_team")
    away = raw.get("away_team")
    if not home or not away:
        return None

    h2h_home, h2h_away, h2h_draw = [], [], []
    over_2_5, under_2_5 = [], []

    for bm in bookmakers:
        for market in bm.get("markets", []):
            if market.get("key") == "h2h":
                for o in market.get("outcomes", []):
                    name = o.get("name")
                    price = o.get("price")
                    if not price:
                        continue
                    if name == home:
                        h2h_home.append(price)
                    elif name == away:
                        h2h_away.append(price)
                    elif name == "Draw":
                        h2h_draw.append(price)
            elif market.get("key") == "totals":
                for o in market.get("outcomes", []):
                    if o.get("point") == 2.5 and o.get("price"):
                        if o.get("name") == "Over":
                            over_2_5.append(o["price"])
                        elif o.get("name") == "Under":
                            under_2_5.append(o["price"])

    if not h2h_home or not h2h_away:
        return None

    # Best odds
    best_home = max(h2h_home)
    best_away = max(h2h_away)
    best_draw = max(h2h_draw) if h2h_draw else None
    best_over = max(over_2_5) if over_2_5 else None
    best_under = max(under_2_5) if under_2_5 else None

    # Implied probabilities (margin-stripped via normalization)
    avg_home = sum(h2h_home) / len(h2h_home)
    avg_away = sum(h2h_away) / len(h2h_away)
    avg_draw = sum(h2h_draw) / len(h2h_draw) if h2h_draw else None

    inv_h = 1.0 / avg_home
    inv_a = 1.0 / avg_away
    inv_d = (1.0 / avg_draw) if avg_draw else 0.0
    total = inv_h + inv_a + inv_d
    if total > 0:
        p_home = inv_h / total
        p_away = inv_a / total
        p_draw = inv_d / total
    else:
        p_home = p_away = p_draw = 0.33

    if over_2_5 and under_2_5:
        avg_o = sum(over_2_5) / len(over_2_5)
        avg_u = sum(under_2_5) / len(under_2_5)
        inv_o = 1.0 / avg_o
        inv_u = 1.0 / avg_u
        p_over = inv_o / (inv_o + inv_u)
        p_under = 1.0 - p_over
    else:
        p_over = None
        p_under = None

    return {
        "match_id": raw.get("id"),
        "league": LEAGUE_NAMES.get(league_key, league_key),
        "league_key": league_key,
        "home_team": home,
        "away_team": away,
        "commence_time": raw.get("commence_time"),
        "best_odds": {
            "home_win": round(best_home, 2),
            "away_win": round(best_away, 2),
            "draw": round(best_draw, 2) if best_draw else None,
            "over_2_5": round(best_over, 2) if best_over else None,
            "under_2_5": round(best_under, 2) if best_under else None,
        },
        "probabilities": {
            "home_win": round(p_home, 4),
            "draw": round(p_draw, 4),
            "away_win": round(p_away, 4),
            "over_2_5": round(p_over, 4) if p_over is not None else None,
            "under_2_5": round(p_under, 4) if p_under is not None else None,
        },
    }


# ── Safe-pick selector ─────────────────────────────────────


def safest_pick(match: dict) -> Optional[dict]:
    """
    Pick the single SAFEST option from a parsed match.

    Each candidate carries a pick_key used to ask the ML overlay
    (worldcup.ml_overlay) whether ELO ratings AGREE with the bookmaker.

    - Picks where ML AGREES get a +5% confidence boost (capped at 95%)
      and are flagged ml_verified=True.
    - Picks where ML STRONGLY DISAGREES are dropped from consideration.
    - Picks ML can't evaluate (unknown team OR goals market) keep their
      bookmaker confidence and ml_verified=False.
    """
    from worldcup.ml_overlay import check_agreement

    p = match.get("probabilities", {})
    bo = match.get("best_odds", {})
    home = match["home_team"]
    away = match["away_team"]

    # Each candidate: (prob, odds, label, market, pick_key)
    candidates = []

    if bo.get("home_win") and p.get("home_win", 0) >= 0.62:
        candidates.append((p["home_win"], bo["home_win"], f"{home} Win", "match_result", "home_win"))
    if bo.get("away_win") and p.get("away_win", 0) >= 0.62:
        candidates.append((p["away_win"], bo["away_win"], f"{away} Win", "match_result", "away_win"))

    hd = min(0.95, p.get("home_win", 0) + p.get("draw", 0))
    ad = min(0.95, p.get("away_win", 0) + p.get("draw", 0))
    if hd >= 0.75:
        est = round(1.0 / max(hd, 0.55), 2)
        candidates.append((hd, est, f"{home} or Draw", "double_chance", "home_or_draw"))
    if ad >= 0.75:
        est = round(1.0 / max(ad, 0.55), 2)
        candidates.append((ad, est, f"{away} or Draw", "double_chance", "away_or_draw"))

    over_2_5 = p.get("over_2_5") or 0
    if over_2_5 >= 0.50:
        over_1_5 = min(0.92, over_2_5 + 0.15)
        est = round(1.0 / max(over_1_5, 0.62), 2)
        candidates.append((over_1_5, est, "Over 1.5 Goals", "goals", "over_1_5"))

    if bo.get("over_2_5") and over_2_5 >= 0.55:
        candidates.append((over_2_5, bo["over_2_5"], "Over 2.5 Goals", "goals", "over_2_5"))

    under_2_5 = p.get("under_2_5") or 0
    if bo.get("under_2_5") and under_2_5 >= 0.62:
        candidates.append((under_2_5, bo["under_2_5"], "Under 2.5 Goals", "goals", "under_2_5"))

    if not candidates:
        return None

    # ── Run ML overlay on each candidate ──
    enriched = []
    for prob, odds, label, market, pick_key in candidates:
        try:
            check = check_agreement(p, pick_key, home, away)
        except Exception:
            check = {"ml_available": False, "agreement": "n/a"}

        if check["agreement"] == "strong_disagree":
            # Skip — bookmaker and ELO can't both be right
            continue

        boosted_prob = prob
        ml_verified = False
        if check["agreement"] == "agree":
            ml_verified = True
            # Small boost (avg of bookmaker + ml, capped slightly higher)
            ml_prob = check.get("ml_prob_for_pick") or prob
            boosted_prob = min(0.95, (prob + ml_prob) / 2 + 0.03)

        enriched.append({
            "prob": prob,
            "boosted_prob": boosted_prob,
            "odds": odds,
            "label": label,
            "market": market,
            "pick_key": pick_key,
            "ml_verified": ml_verified,
            "ml_check": check,
        })

    if not enriched:
        return None

    # Prefer ml_verified picks; then sort by boosted confidence
    enriched.sort(key=lambda x: (x["ml_verified"], x["boosted_prob"]), reverse=True)
    best = enriched[0]

    return {
        "prediction": best["label"],
        "odds": round(best["odds"], 2),
        "confidence": round(best["boosted_prob"], 3),
        "raw_confidence": round(best["prob"], 3),
        "market": best["market"],
        "ml_verified": best["ml_verified"],
        "ml_agreement": best["ml_check"].get("agreement", "n/a"),
        "ml_probability": best["ml_check"].get("ml_prob_for_pick"),
    }


# ── Main public function ───────────────────────────────────


def get_active_matches(days_ahead: int = 5, force_refresh: bool = False) -> List[dict]:
    """
    Fetch every parsed match across active leagues within the next
    `days_ahead` days. Each match has a `safe_pick` attached.

    Sorted by commence_time ascending.
    """
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=days_ahead)
    matches: List[dict] = []

    for league_key in ACTIVE_LEAGUES:
        try:
            raw_list = fetch_league_odds(league_key, force_refresh=force_refresh)
        except Exception as e:
            logger.error(f"league {league_key} fetch error: {e}")
            continue

        for raw in raw_list:
            try:
                ct = raw.get("commence_time")
                if not ct:
                    continue
                # Parse commence time
                commence = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                # Skip matches more than 2h in the past
                if commence < now - timedelta(hours=2):
                    continue
                # Skip too-far matches
                if commence > cutoff:
                    continue

                parsed = parse_match(raw, league_key)
                if not parsed:
                    continue
                pick = safest_pick(parsed)
                if not pick:
                    continue
                parsed["safe_pick"] = pick
                matches.append(parsed)
            except Exception as e:
                logger.error(f"parse error {raw.get('id', '?')}: {e}")
                continue

    matches.sort(key=lambda m: m["commence_time"])
    return matches
