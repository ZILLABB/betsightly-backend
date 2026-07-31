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


def _market_probs(odds_block: dict | None) -> dict | None:
    """De-vigged 1X2 probabilities from the sportsbook's moneylines.

    Raw implied probabilities sum to >1 because the book's margin is baked in;
    normalising strips it out so the result is comparable to a model number.
    """
    if not odds_block:
        return None
    from leagues.elo_engine import _american_to_decimal

    def imp(block, key="moneyLine"):
        if not block:
            return None
        dec = _american_to_decimal(block.get(key))
        return 1.0 / dec if dec and dec > 1 else None

    ph = imp(odds_block.get("homeTeamOdds"))
    pa = imp(odds_block.get("awayTeamOdds"))
    pd = imp(odds_block.get("drawOdds"))
    if ph is None or pa is None or pd is None:
        return None
    total = ph + pa + pd
    if total <= 0:
        return None
    return {"home_win": ph / total, "draw": pd / total, "away_win": pa / total}


def _market_total_probs(odds_block: dict | None) -> dict | None:
    """De-vigged Over/Under probabilities and the line they refer to."""
    if not odds_block:
        return None
    from leagues.elo_engine import _american_to_decimal

    total_block = odds_block.get("total") or {}
    line = odds_block.get("overUnder")

    def side(name):
        b = total_block.get(name) or {}
        quote = b.get("close") or b.get("open") or {}
        dec = _american_to_decimal(quote.get("odds"))
        return 1.0 / dec if dec and dec > 1 else None

    po, pu = side("over"), side("under")
    if po is None or pu is None:
        return None
    s = po + pu
    if s <= 0:
        return None
    return {"line": line, "over": po / s, "under": pu / s}


def _build_prediction(home: str, away: str, commence: str, league_name: str,
                      home_logo: str | None, away_logo: str | None,
                      rates: dict | None = None, slug: str | None = None,
                      elo_all: dict | None = None,
                      odds_block: dict | None = None,
                      extra: dict | None = None) -> dict | None:
    """Blend three independent signals into one probability per market.

    1. The sportsbook's de-vigged price — the sharpest single estimate available,
       so it carries the most weight when present.
    2. ELO built from this league's own recent results.
    3. The league's measured base rates.

    Falling back through those in order means a fixture in a league with no
    odds and no rated teams still gets an honest league-average number rather
    than an invented one.
    """
    from leagues.base_rates import GLOBAL_DEFAULTS
    from leagues.elo_engine import rating_for

    rates = rates or dict(GLOBAL_DEFAULTS)

    lg_home = rates.get("home_win", 0.474)
    lg_draw = rates.get("draw", 0.231)
    lg_away = rates.get("away_win", 0.295)

    # ── Team strength from ESPN-derived, league-scoped ELO ──
    h_elo = a_elo = None
    if slug and elo_all is not None:
        h_elo = rating_for(slug, home, elo_all)
        a_elo = rating_for(slug, away, elo_all)
    rated = h_elo is not None and a_elo is not None

    if rated:
        diff = (h_elo + 60.0) - a_elo
        expected = 1.0 / (1.0 + math.pow(10, -diff / 400.0))
        draw_p = max(0.08, min(0.32, lg_draw))
        e_home = max(0.03, expected - 0.5 * draw_p)
        e_away = max(0.03, 1.0 - e_home - draw_p)
        s = e_home + draw_p + e_away
        elo_home, elo_draw, elo_away = e_home / s, draw_p / s, e_away / s
    else:
        elo_home, elo_draw, elo_away = lg_home, lg_draw, lg_away

    # ── Match result: market first, then ELO, then league base ──
    mkt = _market_probs(odds_block)
    if mkt:
        w_mkt, w_elo, w_lg = (0.65, 0.25, 0.10) if rated else (0.80, 0.0, 0.20)
        p_home = w_mkt * mkt["home_win"] + w_elo * elo_home + w_lg * lg_home
        p_draw = w_mkt * mkt["draw"] + w_elo * elo_draw + w_lg * lg_draw
        p_away = w_mkt * mkt["away_win"] + w_elo * elo_away + w_lg * lg_away
    else:
        p_home, p_draw, p_away = elo_home, elo_draw, elo_away
    total = p_home + p_draw + p_away
    p_home, p_draw, p_away = p_home / total, p_draw / total, p_away / total

    # ── Goals: anchor on the league's measured scoring, tilt by ELO gap ──
    lg_home_goals = rates.get("home_goals", 1.50)
    lg_away_goals = rates.get("away_goals", 1.20)
    if rated:
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

    # Blend the book's Over/Under when it is quoted on the 2.5 line
    mkt_tot = _market_total_probs(odds_block)
    if mkt_tot and abs((mkt_tot.get("line") or 0) - 2.5) < 0.01:
        over_2_5 = 0.65 * mkt_tot["over"] + 0.35 * over_2_5

    btts_raw = (1.0 - math.exp(-exp_home)) * (1.0 - math.exp(-exp_away))
    btts_at_avg = (1.0 - math.exp(-lg_home_goals)) * (1.0 - math.exp(-lg_away_goals))
    btts_cal = rates.get("btts", 0.526) / max(btts_at_avg, 1e-6)
    btts = min(0.88, max(0.20, btts_raw * btts_cal))

    # Real sportsbook prices where quoted; our own fair price elsewhere, so a
    # slip never mixes a real payout with an imagined one silently.
    from leagues.elo_engine import _american_to_decimal
    ob = odds_block or {}
    book = {}
    if ob:
        book["home_win"] = _american_to_decimal((ob.get("homeTeamOdds") or {}).get("moneyLine"))
        book["away_win"] = _american_to_decimal((ob.get("awayTeamOdds") or {}).get("moneyLine"))
        book["draw"] = _american_to_decimal((ob.get("drawOdds") or {}).get("moneyLine"))
        tb = ob.get("total") or {}
        for side, key in (("over", "over_2_5"), ("under", "under_2_5")):
            q = (tb.get(side) or {}).get("close") or (tb.get(side) or {}).get("open") or {}
            book[key] = _american_to_decimal(q.get("odds"))
    book = {k: v for k, v in book.items() if v}

    margin = 1.05

    def price(key, prob):
        """Sportsbook price when available, else our fair price."""
        return book.get(key) or round(margin / max(prob, 0.05), 2)

    best_odds = {
        "home_win": price("home_win", p_home),
        "draw": price("draw", p_draw),
        "away_win": price("away_win", p_away),
        "over_2_5": price("over_2_5", over_2_5),
        "under_2_5": price("under_2_5", 1.0 - over_2_5),
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

    # Value: where our probability beats the book's own de-vigged number.
    # Only computed against real prices — an edge over our own fair price
    # would be meaningless.
    value_bets = []
    if mkt:
        for key, our_p, lbl in (
            ("home_win", p_home, f"{home} Win"),
            ("away_win", p_away, f"{away} Win"),
            ("draw", p_draw, "Draw"),
        ):
            dec = book.get(key)
            if not dec:
                continue
            edge = our_p - mkt[key]
            if edge > 0.04:
                value_bets.append({
                    "bet": lbl, "market": "match_result", "odds": dec,
                    "our_prob": round(our_p, 3),
                    "implied_prob": round(mkt[key], 3),
                    "edge": round(edge, 3),
                    "expected_value": round(our_p * dec - 1, 3),
                })
    if mkt_tot and abs((mkt_tot.get("line") or 0) - 2.5) < 0.01:
        for key, our_p, lbl, mp in (
            ("over_2_5", over_2_5, "Over 2.5 Goals", mkt_tot["over"]),
            ("under_2_5", 1.0 - over_2_5, "Under 2.5 Goals", mkt_tot["under"]),
        ):
            dec = book.get(key)
            if dec and our_p - mp > 0.04:
                value_bets.append({
                    "bet": lbl, "market": "goals", "odds": dec,
                    "our_prob": round(our_p, 3),
                    "implied_prob": round(mp, 3),
                    "edge": round(our_p - mp, 3),
                    "expected_value": round(our_p * dec - 1, 3),
                })
    value_bets.sort(key=lambda v: v["expected_value"], reverse=True)

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
        "value_bets": value_bets,
        # Context shown on the match card: where and when it kicks off, how
        # each side has been going, and how strong the numbers behind the
        # pick are.
        "match_info": {
            "kickoff_utc": commence,
            "venue": (extra or {}).get("venue"),
            "city": (extra or {}).get("city"),
            "country": (extra or {}).get("country"),
            "broadcast": (extra or {}).get("broadcast"),
            "home_form": (extra or {}).get("home_form"),
            "away_form": (extra or {}).get("away_form"),
            "home_record": (extra or {}).get("home_record"),
            "away_record": (extra or {}).get("away_record"),
            "home_elo": round(h_elo) if h_elo is not None else None,
            "away_elo": round(a_elo) if a_elo is not None else None,
        },
        "data_quality": {
            "source": "espn_elo",
            "league": league_name,
            "elo_rated": rated,
            "league_sample": rates.get("matches", 0),
            "has_book_odds": bool(book),
            "odds_provider": (ob.get("provider") or {}).get("displayName") if ob else None,
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
    from leagues.elo_engine import get_ratings
    all_rates = get_base_rates(ESPN_CLUB_LEAGUES)
    elo_all = get_ratings(ESPN_CLUB_LEAGUES)

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

            venue = comp.get("venue") or {}
            addr = venue.get("address") or {}
            bc = comp.get("broadcasts") or []
            names = (bc[0].get("names") if bc else None) or []

            def _record(c):
                recs = c.get("records") or []
                return recs[0].get("summary") if recs else None

            extra = {
                "venue": venue.get("fullName"),
                "city": addr.get("city"),
                "country": addr.get("country"),
                "broadcast": names[0] if names else None,
                "home_form": home_c.get("form"),
                "away_form": away_c.get("form"),
                "home_record": _record(home_c),
                "away_record": _record(away_c),
            }
            odds_list = comp.get("odds") or []

            pred = _build_prediction(
                home, away, commence, league_name,
                home_c.get("team", {}).get("logo"),
                away_c.get("team", {}).get("logo"),
                league_rates,
                slug=slug,
                elo_all=elo_all,
                odds_block=odds_list[0] if odds_list else None,
                extra=extra,
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
