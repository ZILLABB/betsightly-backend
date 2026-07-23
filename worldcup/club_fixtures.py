"""
ELO-based club fixture source — no Odds API needed.

The Odds API free tier (500/mo) is exhausted, so club fixtures now come
from ESPN scoreboards (free, no key) and odds are derived from the club
ELO registry (models/api_football/elo_ratings.json, 767 teams) via
worldcup.ml_overlay — the same approach that powered the WC knockout rounds.

Teams missing from the ELO registry are skipped rather than guessed, so
every published pick has a real strength rating behind it.

Output schema matches _club_match_to_prediction / WC predictions so
build_daily_accumulators consumes it unchanged.
"""

import hashlib
import json
import logging
import math
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).parent.parent / "cache" / "club_fixtures.json"
CACHE_TTL = 6 * 3600  # refresh from ESPN at most every 6 hours

# ESPN league slug -> display name. Active leagues rotate with the calendar;
# leagues out of season simply return no scheduled events.
ESPN_CLUB_LEAGUES = {
    "bra.1": "Brasileirão Série A",
    "arg.1": "Liga Profesional Argentina",
    "chi.1": "Primera División Chile",
    "usa.1": "MLS",
    "mex.1": "Liga MX",
    "fin.1": "Veikkausliiga",
    "nor.1": "Eliteserien",
    "swe.1": "Allsvenskan",
    "irl.1": "League of Ireland",
    "jpn.1": "J1 League",
    "kor.1": "K League 1",
    "conmebol.libertadores": "Copa Libertadores",
    "conmebol.sudamericana": "Copa Sudamericana",
    "eng.1": "Premier League",
    "esp.1": "La Liga",
    "esp.2": "La Liga 2",
    "ger.1": "Bundesliga",
    "ita.1": "Serie A",
    "fra.1": "Ligue 1",
}


def _poisson_over(threshold: int, lam: float) -> float:
    cum = sum((lam ** k) * math.exp(-lam) / math.factorial(k) for k in range(threshold + 1))
    return 1.0 - cum


# ESPN display name -> ELO registry name, for teams whose registry entry
# uses a different convention than any ESPN name variant.
CLUB_ALIASES = {
    "Botafogo": "Botafogo RJ",
    "Gimnasia La Plata": "Gimnasia L.P.",
    "Gimnasia (Mendoza)": "Gimnasia Mendoza",
    "Sarmiento (Junín)": "Sarmiento Junin",
    "Unión (Santa Fe)": "Union de Santa Fe",
    "Central Córdoba (Santiago del Estero)": "Central Cordoba",
    "Instituto (Córdoba)": "Instituto",
    "Örgryte IS": "Orgryte",
    "Colón": "Colon Santa Fe",
}


def _resolve_name(team: dict) -> str:
    """Pick the ESPN team-name variant that resolves in the ELO registry.
    Falls back to displayName when none match (the pick then gets skipped)."""
    from worldcup.ml_overlay import is_known_team

    display = team.get("displayName", "")
    if display in CLUB_ALIASES:
        return CLUB_ALIASES[display]
    candidates = [
        display,
        team.get("shortDisplayName", ""),
        team.get("name", ""),
        team.get("location", ""),
    ]
    for c in candidates:
        if c and is_known_team(c):
            return c
    return display


def _fetch_league_day(slug: str, date_str: str) -> list[dict]:
    try:
        resp = requests.get(
            f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard",
            params={"dates": date_str},
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        return resp.json().get("events", [])
    except Exception as e:
        logger.warning(f"ESPN club fetch failed {slug}/{date_str}: {e}")
        return []


def _build_prediction(home: str, away: str, commence: str, league_name: str,
                      home_logo: str | None, away_logo: str | None) -> dict | None:
    """ELO probabilities + Poisson goals -> WC-prediction-schema dict."""
    from worldcup.ml_overlay import elo_probabilities, get_team_rating

    probs = elo_probabilities(home, away)
    if not probs:
        return None  # team not in ELO registry — skip, don't guess

    p_home, p_draw, p_away = probs["home_win"], probs["draw"], probs["away_win"]

    # Expected goals: league-average total ~2.6, tilted by ELO gap
    h_elo = get_team_rating(home) or 1500
    a_elo = get_team_rating(away) or 1500
    gap = (h_elo - a_elo) / 400.0
    exp_home = max(0.4, min(3.2, 1.40 * (1.0 + gap * 0.25)))
    exp_away = max(0.3, min(2.6, 1.20 * (1.0 - gap * 0.25)))
    exp_total = exp_home + exp_away

    over_2_5 = _poisson_over(2, exp_total)
    over_1_5 = min(0.95, max(0.40, _poisson_over(1, exp_total)))
    btts = (1.0 - math.exp(-exp_home)) * (1.0 - math.exp(-exp_away))

    margin = 1.05
    best_odds = {
        "home_win": round(margin / max(p_home, 0.05), 2),
        "draw": round(margin / max(p_draw, 0.05), 2),
        "away_win": round(margin / max(p_away, 0.05), 2),
        "over_2_5": round(margin / max(over_2_5, 0.1), 2),
        "under_2_5": round(margin / max(1.0 - over_2_5, 0.1), 2),
    }

    # Headline pick: strongest of home/away win vs over 1.5
    candidates = [
        (f"{home} Win", "match_result", p_home, best_odds["home_win"]),
        (f"{away} Win", "match_result", p_away, best_odds["away_win"]),
        ("Over 1.5 Goals", "goals", over_1_5, round(1.0 / max(over_1_5, 0.62), 2)),
    ]
    label, market, conf, odds = max(candidates, key=lambda c: c[2])

    match_id = hashlib.md5(f"{home}{away}{commence}".encode()).hexdigest()
    return {
        "match_id": match_id,
        "home_team": home,
        "away_team": away,
        "home_team_logo": home_logo,
        "away_team_logo": away_logo,
        "commence_time": commence,
        "prediction": label,
        "prediction_key": market,
        "prediction_market": market,
        "confidence": round(conf, 3),
        "risk_level": "low" if conf >= 0.70 else "medium",
        "probabilities": {
            "home_win": round(p_home, 3),
            "draw": round(p_draw, 3),
            "away_win": round(p_away, 3),
        },
        "best_odds": best_odds,
        "top_tips": [{"tip": label, "market": market, "confidence": round(conf, 3), "odds": odds}],
        "goals": {
            "over_2_5_prob": round(over_2_5, 3),
            "under_2_5_prob": round(1.0 - over_2_5, 3),
            "over_1_5_prob": round(over_1_5, 3),
            "btts_prob": round(btts, 3),
            "expected_total": round(exp_total, 2),
            "expected_home": round(exp_home, 2),
            "expected_away": round(exp_away, 2),
        },
        "value_bets": [],
        "data_quality": {"source": "espn_elo", "league": league_name},
    }


def get_club_predictions(days_ahead: int = 2) -> list[dict]:
    """Upcoming club predictions from ESPN + ELO. Cached for CACHE_TTL."""
    try:
        if CACHE_PATH.exists() and (time.time() - CACHE_PATH.stat().st_mtime) < CACHE_TTL:
            cached = json.loads(CACHE_PATH.read_text())
            if cached:
                return cached
    except Exception:
        pass

    preds: list[dict] = []
    seen: set[str] = set()
    now = datetime.utcnow()
    for slug, league_name in ESPN_CLUB_LEAGUES.items():
        for offset in range(days_ahead):
            date_str = (now + timedelta(days=offset)).strftime("%Y%m%d")
            for ev in _fetch_league_day(slug, date_str):
                status = ev.get("status", {}).get("type", {}).get("name", "")
                if status != "STATUS_SCHEDULED":
                    continue
                comp = (ev.get("competitions") or [{}])[0]
                teams = comp.get("competitors", [])
                home_c = next((t for t in teams if t.get("homeAway") == "home"), {})
                away_c = next((t for t in teams if t.get("homeAway") == "away"), {})
                home = _resolve_name(home_c.get("team", {}))
                away = _resolve_name(away_c.get("team", {}))
                commence = ev.get("date", "")
                if not home or not away or not commence:
                    continue
                if commence.endswith("Z") and len(commence) == 17:
                    commence = commence[:-1] + ":00Z"
                key = f"{home}|{away}|{commence[:10]}"
                if key in seen:
                    continue
                seen.add(key)
                pred = _build_prediction(
                    home, away, commence, league_name,
                    home_c.get("team", {}).get("logo"),
                    away_c.get("team", {}).get("logo"),
                )
                if pred:
                    preds.append(pred)

    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(preds))
    except Exception:
        pass

    logger.info(f"ESPN+ELO club predictions: {len(preds)} matches")
    return preds
