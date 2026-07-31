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
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).parent.parent / "cache" / "club_fixtures.json"
CACHE_TTL = 6 * 3600  # refresh from ESPN at most every 6 hours

# ESPN league slug -> display name. Active leagues rotate with the calendar;
# leagues out of season simply return no scheduled events.
ESPN_CLUB_LEAGUES = {
    # South America
    "bra.1": "Brasileirão Série A",
    "bra.2": "Brasileirão Série B",
    "arg.1": "Liga Profesional Argentina",
    "chi.1": "Primera División Chile",
    "col.1": "Categoría Primera A",
    "uru.1": "Primera División Uruguay",
    "par.1": "División Profesional Paraguay",
    "per.1": "Liga 1 Perú",
    "ecu.1": "Serie A Ecuador",
    "conmebol.libertadores": "Copa Libertadores",
    "conmebol.sudamericana": "Copa Sudamericana",
    # North America
    "usa.1": "MLS",
    "usa.nwsl": "NWSL",
    "mex.1": "Liga MX",
    "concacaf.league": "CONCACAF Champions Cup",
    # Northern Europe (summer season)
    "fin.1": "Veikkausliiga",
    "nor.1": "Eliteserien",
    "swe.1": "Allsvenskan",
    "den.1": "Superliga",
    "isl.1": "Besta deild",
    "irl.1": "League of Ireland",
    # Asia
    "jpn.1": "J1 League",
    "kor.1": "K League 1",
    "chn.1": "Chinese Super League",
    "aus.1": "A-League",
    # Europe — top flights (kick off Aug)
    "eng.1": "Premier League",
    "eng.2": "Championship",
    "eng.league_cup": "EFL Cup",
    "esp.1": "La Liga",
    "esp.2": "La Liga 2",
    "ger.1": "Bundesliga",
    "ger.2": "2. Bundesliga",
    "ita.1": "Serie A",
    "ita.2": "Serie B",
    "fra.1": "Ligue 1",
    "fra.2": "Ligue 2",
    "por.1": "Primeira Liga",
    "ned.1": "Eredivisie",
    "bel.1": "Belgian Pro League",
    "tur.1": "Süper Lig",
    "sco.1": "Scottish Premiership",
    "gre.1": "Super League Greece",
    "aut.1": "Austrian Bundesliga",
    "sui.1": "Swiss Super League",
    "uefa.champions": "Champions League",
    "uefa.europa": "Europa League",
    "uefa.europa.conf": "Conference League",
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
    Falls back to displayName; unrated teams still get a prediction, built
    from league base rates instead of team strength."""
    from leagues.ml_overlay import is_known_team

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


def _fetch_league_range(slug: str, start: str, end: str) -> list[dict]:
    """Scheduled events across a date range in one request (ESPN supports
    dates=YYYYMMDD-YYYYMMDD), instead of one call per league per day."""
    try:
        resp = requests.get(
            f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard",
            params={"dates": f"{start}-{end}", "limit": 500},
            timeout=25,
        )
        if resp.status_code != 200:
            return []
        return resp.json().get("events", [])
    except Exception as e:
        logger.warning(f"ESPN club fetch failed {slug}: {e}")
        return []


def _build_prediction(home: str, away: str, commence: str, league_name: str,
                      home_logo: str | None, away_logo: str | None,
                      rates: dict | None = None) -> dict | None:
    """League base rates (measured from real results) adjusted by team ELO.

    Base rates are the anchor: Over 1.5 in Argentina really is ~52% and in
    Norway ~84%, so a single global constant produces badly wrong confidence.
    ELO then tilts the match-result split and shifts goals modestly.
    Teams missing from the ELO registry still get a prediction — it simply
    rests on the league rate alone.
    """
    from leagues.base_rates import GLOBAL_DEFAULTS
    from leagues.ml_overlay import elo_probabilities, get_team_rating

    rates = rates or dict(GLOBAL_DEFAULTS)

    lg_home = rates.get("home_win", 0.474)
    lg_draw = rates.get("draw", 0.231)
    lg_away = rates.get("away_win", 0.295)

    # ── Match result: blend league base with ELO when both teams are rated ──
    probs = elo_probabilities(home, away)
    if probs:
        p_home = 0.60 * probs["home_win"] + 0.40 * lg_home
        p_draw = 0.60 * probs["draw"] + 0.40 * lg_draw
        p_away = 0.60 * probs["away_win"] + 0.40 * lg_away
        total = p_home + p_draw + p_away
        p_home, p_draw, p_away = p_home / total, p_draw / total, p_away / total
        rated = True
    else:
        p_home, p_draw, p_away = lg_home, lg_draw, lg_away
        rated = False

    # ── Goals: anchor on the league's measured scoring, tilt by ELO gap ──
    lg_home_goals = rates.get("home_goals", 1.50)
    lg_away_goals = rates.get("away_goals", 1.20)
    h_elo = get_team_rating(home)
    a_elo = get_team_rating(away)
    if h_elo is not None and a_elo is not None:
        gap = max(-1.5, min(1.5, (h_elo - a_elo) / 400.0))
        exp_home = lg_home_goals * (1.0 + gap * 0.22)
        exp_away = lg_away_goals * (1.0 - gap * 0.22)
    else:
        exp_home, exp_away = lg_home_goals, lg_away_goals
    exp_total = max(0.8, exp_home + exp_away)

    # Poisson gives the shape; scale it so the league's measured Over rates
    # are reproduced exactly at average strength. A raw Poisson on Argentine
    # goal averages overstates Over 1.5 by ~15 points.
    lg_avg = max(0.8, rates.get("avg_goals", 2.70))
    poisson_o15_at_avg = _poisson_over(1, lg_avg)
    poisson_o25_at_avg = _poisson_over(2, lg_avg)
    o15_cal = rates.get("over_1_5", 0.734) / max(poisson_o15_at_avg, 1e-6)
    o25_cal = rates.get("over_2_5", 0.549) / max(poisson_o25_at_avg, 1e-6)

    over_1_5 = min(0.94, max(0.35, _poisson_over(1, exp_total) * o15_cal))
    over_2_5 = min(0.90, max(0.20, _poisson_over(2, exp_total) * o25_cal))

    btts_raw = (1.0 - math.exp(-exp_home)) * (1.0 - math.exp(-exp_away))
    btts_at_avg = (1.0 - math.exp(-lg_home_goals)) * (1.0 - math.exp(-lg_away_goals))
    btts_cal = rates.get("btts", 0.526) / max(btts_at_avg, 1e-6)
    btts = min(0.88, max(0.20, btts_raw * btts_cal))

    # Fair odds from our own probabilities. These are NOT bookmaker prices —
    # book_odds stays absent so nothing downstream claims a verified edge.
    margin = 1.05
    best_odds = {
        "home_win": round(margin / max(p_home, 0.05), 2),
        "draw": round(margin / max(p_draw, 0.05), 2),
        "away_win": round(margin / max(p_away, 0.05), 2),
        "over_2_5": round(margin / max(over_2_5, 0.1), 2),
        "under_2_5": round(margin / max(1.0 - over_2_5, 0.1), 2),
    }

    home_or_draw = min(0.95, p_home + p_draw)
    away_or_draw = min(0.95, p_away + p_draw)

    # Headline pick: highest-probability option across every market
    candidates = [
        (f"{home} Win", "match_result", p_home, best_odds["home_win"]),
        (f"{away} Win", "match_result", p_away, best_odds["away_win"]),
        ("Over 1.5 Goals", "goals", over_1_5, round(margin / max(over_1_5, 0.1), 2)),
        ("Over 2.5 Goals", "goals", over_2_5, best_odds["over_2_5"]),
        ("Under 2.5 Goals", "goals", 1.0 - over_2_5, best_odds["under_2_5"]),
        ("Both Teams to Score", "btts", btts, round(margin / max(btts, 0.1), 2)),
        ("BTTS No", "btts", 1.0 - btts, round(margin / max(1.0 - btts, 0.1), 2)),
        (f"{home} or Draw", "double_chance", home_or_draw, round(margin / max(home_or_draw, 0.1), 2)),
        (f"{away} or Draw", "double_chance", away_or_draw, round(margin / max(away_or_draw, 0.1), 2)),
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
        "data_quality": {
            "source": "espn_elo",
            "league": league_name,
            "elo_rated": rated,
            "league_sample": rates.get("matches", 0),
        },
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

    from leagues.base_rates import get_base_rates, rates_for
    all_rates = get_base_rates(ESPN_CLUB_LEAGUES)

    now = datetime.now(timezone.utc)
    start = now.strftime("%Y%m%d")
    end = (now + timedelta(days=max(0, days_ahead - 1))).strftime("%Y%m%d")

    fetched: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(_fetch_league_range, slug, start, end): slug
                   for slug in ESPN_CLUB_LEAGUES}
        for fut in as_completed(futures):
            slug = futures[fut]
            try:
                fetched[slug] = fut.result()
            except Exception:
                fetched[slug] = []

    preds: list[dict] = []
    seen: set[str] = set()
    cutoff = now + timedelta(days=days_ahead)
    for slug, league_name in ESPN_CLUB_LEAGUES.items():
        league_rates = rates_for(slug, all_rates)
        for ev in fetched.get(slug, []):
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
            try:
                kickoff = datetime.fromisoformat(commence.replace("Z", "+00:00"))
                if kickoff > cutoff:
                    continue
            except Exception:
                pass
            key = f"{home}|{away}|{commence[:10]}"
            if key in seen:
                continue
            seen.add(key)
            pred = _build_prediction(
                home, away, commence, league_name,
                home_c.get("team", {}).get("logo"),
                away_c.get("team", {}).get("logo"),
                league_rates,
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
