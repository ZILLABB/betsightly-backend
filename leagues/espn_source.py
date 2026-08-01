"""
ESPN fixture + odds source.

ESPN's public scoreboard carries real DraftKings prices (moneyline for
home/draw/away plus an over/under line with both sides) on essentially every
scheduled fixture, alongside kickoff time, venue, recent form and season
records. That removes the dependency on the paid Odds API, whose free quota
has been exhausted since June.

It also fixes the coverage collapse. The previous pipeline required both
teams to exist in the 767-team ELO registry and dropped the fixture
otherwise — which discarded 85% of fixtures, because that registry never
covered Argentine Nacional B, the Bolivian or Peruvian leagues, and most of
the rest of the world. Here, odds are the primary signal and ELO is an
optional second opinion, so no fixture is dropped for want of a rating.

Odds arrive as American prices and are converted to decimal, then de-vigged
(normalised so the three outcome probabilities sum to 1) before use.
"""

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).parent.parent / "cache" / "espn_fixtures.json"
CACHE_TTL = 3 * 3600  # 3 hours — odds drift, but not minute to minute

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"

# Every league we track. Out-of-season leagues simply return no fixtures, so
# listing them costs one cheap request and means European leagues light up
# automatically when their seasons start.
ESPN_CLUB_LEAGUES = {
    # Europe — top flights
    "eng.1": "Premier League", "eng.2": "EFL Championship", "eng.3": "EFL League One",
    "eng.4": "EFL League Two", "eng.fa": "FA Cup", "eng.league_cup": "Carabao Cup",
    "esp.1": "LaLiga", "esp.2": "LaLiga 2", "esp.copa_del_rey": "Copa del Rey",
    "ger.1": "Bundesliga", "ger.2": "2. Bundesliga", "ger.dfb_pokal": "DFB Pokal",
    "ita.1": "Serie A", "ita.2": "Serie B", "ita.coppa_italia": "Coppa Italia",
    "fra.1": "Ligue 1", "fra.2": "Ligue 2",
    "por.1": "Primeira Liga", "ned.1": "Eredivisie", "bel.1": "Belgian Pro League",
    "tur.1": "Süper Lig", "sui.1": "Swiss Super League", "aut.1": "Austrian Bundesliga",
    "gre.1": "Greek Super League", "sco.1": "Scottish Premiership",
    "sco.2": "Scottish Championship", "den.1": "Danish Superliga",
    "nor.1": "Eliteserien", "swe.1": "Allsvenskan", "fin.1": "Veikkausliiga",
    "irl.1": "League of Ireland", "pol.1": "Ekstraklasa", "cze.1": "Czech First League",
    "rou.1": "Liga I", "rus.1": "Russian Premier League", "ukr.1": "Ukrainian Premier League",
    "cro.1": "HNL", "srb.1": "Serbian SuperLiga", "hun.1": "NB I", "isr.1": "Ligat ha'Al",
    # UEFA clubs
    "uefa.champions": "UEFA Champions League", "uefa.europa": "UEFA Europa League",
    "uefa.europa.conf": "UEFA Conference League",
    # North & Central America
    "usa.1": "MLS", "usa.nwsl": "NWSL", "usa.usl.1": "USL Championship",
    "mex.1": "Liga MX", "mex.2": "Liga de Expansión MX", "can.1": "Canadian Premier League",
    "crc.1": "Liga Promerica", "gua.1": "Liga Nacional Guatemala",
    "hon.1": "Liga Nacional Honduras", "slv.1": "Primera División El Salvador",
    "pan.1": "LPF Panamá", "jam.1": "Jamaica Premier League",
    "concacaf.champions": "CONCACAF Champions Cup",
    # South America
    "bra.1": "Brasileirão Série A", "bra.2": "Brasileirão Série B",
    "arg.1": "Liga Profesional Argentina", "arg.2": "Primera Nacional",
    "chi.1": "Primera División Chile", "col.1": "Categoría Primera A",
    "per.1": "Liga 1 Perú", "uru.1": "Primera División Uruguay",
    "ecu.1": "LigaPro Ecuador", "par.1": "División Profesional Paraguay",
    "bol.1": "División Profesional Bolivia", "ven.1": "Primera División Venezuela",
    "conmebol.libertadores": "Copa Libertadores", "conmebol.sudamericana": "Copa Sudamericana",
    # Asia & Oceania
    "jpn.1": "J1 League", "jpn.2": "J2 League", "kor.1": "K League 1",
    "chn.1": "Chinese Super League", "aus.1": "A-League", "idn.1": "Liga 1 Indonesia",
    "tha.1": "Thai League 1", "ind.1": "Indian Super League", "mys.1": "Malaysia Super League",
    "qat.1": "Qatar Stars League", "sau.1": "Saudi Pro League", "uae.1": "UAE Pro League",
    "irn.1": "Persian Gulf Pro League",
    # Africa
    "rsa.1": "South African Premiership", "egy.1": "Egyptian Premier League",
    "mar.1": "Botola Pro", "tun.1": "Tunisian Ligue 1", "alg.1": "Algerian Ligue 1",
    "nga.1": "Nigeria Premier League", "gha.1": "Ghana Premier League",
    # Misc
    "club.friendly": "Club Friendly",
}


# ── Odds helpers ───────────────────────────────────────────

def _american_to_decimal(american) -> float | None:
    """Convert an American moneyline price to decimal odds."""
    try:
        a = float(str(american).replace("+", "").strip())
    except (TypeError, ValueError):
        return None
    if a == 0:
        return None
    return round(1.0 + (100.0 / abs(a) if a < 0 else a / 100.0), 3)


def _devig(probs: dict[str, float]) -> dict[str, float]:
    """Normalise implied probabilities so they sum to 1 (strip bookmaker margin)."""
    total = sum(v for v in probs.values() if v)
    if total <= 0:
        return {}
    return {k: v / total for k, v in probs.items() if v}


def _parse_odds(competition: dict) -> dict:
    """Extract decimal odds + de-vigged probabilities from an ESPN competition.

    Returns {} when the fixture carries no usable prices.
    """
    blocks = [b for b in (competition.get("odds") or []) if isinstance(b, dict)]
    if not blocks:
        return {}
    o = blocks[0]

    # 1X2 moneylines. ESPN nests these as moneyline.{home,away}.{close,open}.odds
    # (closing price preferred), with the draw carried separately on drawOdds.
    # Older payloads instead expose {home,away}TeamOdds.moneyLine, so try both.
    def _phase_odds(node) -> object | None:
        if not isinstance(node, dict):
            return None
        for phase in ("close", "open", "current"):
            p = node.get(phase)
            if isinstance(p, dict) and p.get("odds") is not None:
                return p["odds"]
        return node.get("odds")

    ml = o.get("moneyline") or {}
    home_ml = _phase_odds(ml.get("home"))
    away_ml = _phase_odds(ml.get("away"))
    draw_ml = _phase_odds(ml.get("draw"))

    if home_ml is None:
        home_ml = (o.get("homeTeamOdds") or {}).get("moneyLine")
    if away_ml is None:
        away_ml = (o.get("awayTeamOdds") or {}).get("moneyLine")
    if draw_ml is None:
        draw_ml = (o.get("drawOdds") or {}).get("moneyLine")

    home_dec = _american_to_decimal(home_ml)
    away_dec = _american_to_decimal(away_ml)
    draw_dec = _american_to_decimal(draw_ml)

    # Over/under. Prefer the closing price, fall back to opening.
    total = o.get("total") or {}
    line = o.get("overUnder")

    def _ou(side: str):
        node = total.get(side) or {}
        for phase in ("close", "open"):
            p = node.get(phase) or {}
            dec = _american_to_decimal(p.get("odds"))
            if dec:
                return dec
        return None

    over_dec, under_dec = _ou("over"), _ou("under")

    out = {
        "provider": (o.get("provider") or {}).get("displayName"),
        "line": line,
        "home_win": home_dec, "draw": draw_dec, "away_win": away_dec,
    }

    if line is not None and float(line) == 2.5:
        out["over_2_5"] = over_dec
        out["under_2_5"] = under_dec

    # De-vigged 1X2 probabilities
    if home_dec and away_dec:
        raw = {"home_win": 1.0 / home_dec, "away_win": 1.0 / away_dec}
        if draw_dec:
            raw["draw"] = 1.0 / draw_dec
        out["implied"] = {k: round(v, 4) for k, v in _devig(raw).items()}

    # De-vigged over/under probabilities
    if over_dec and under_dec:
        ou = _devig({"over": 1.0 / over_dec, "under": 1.0 / under_dec})
        out["implied_over"] = round(ou.get("over", 0), 4)
        out["implied_under"] = round(ou.get("under", 0), 4)
        out["ou_line"] = float(line) if line is not None else None

    return out


# ── Fixture fetching ───────────────────────────────────────

def _fetch_league(slug: str, date_range: str) -> list[dict]:
    """Scheduled fixtures for one league across a date range (single request)."""
    try:
        resp = requests.get(
            SCOREBOARD.format(slug=slug),
            params={"dates": date_range, "limit": 500}, timeout=25,
        )
        if resp.status_code != 200:
            return []
        payload = resp.json()
    except Exception as e:
        logger.debug(f"ESPN fetch failed {slug}: {e}")
        return []

    league_name = ESPN_CLUB_LEAGUES.get(slug) or (payload.get("leagues") or [{}])[0].get("name", slug)
    out = []
    for ev in payload.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        if comp.get("status", {}).get("type", {}).get("name") != "STATUS_SCHEDULED":
            continue
        teams = comp.get("competitors", [])
        home = next((t for t in teams if t.get("homeAway") == "home"), None)
        away = next((t for t in teams if t.get("homeAway") == "away"), None)
        if not home or not away:
            continue

        commence = ev.get("date", "")
        if commence.endswith("Z") and len(commence) == 17:  # 2026-07-31T23:30Z
            commence = commence[:-1] + ":00Z"
        if not commence:
            continue

        def team_info(c: dict) -> dict:
            t = c.get("team", {}) or {}
            rec = ""
            for r in (c.get("records") or []):
                if r.get("type") == "total":
                    rec = r.get("summary", "")
                    break
            return {
                "name": t.get("displayName", ""),
                "short": t.get("shortDisplayName", ""),
                "abbrev": t.get("abbreviation", ""),
                "logo": t.get("logo"),
                "form": c.get("form"),      # e.g. "WWLLD"
                "record": rec,              # e.g. "7-4-6"
            }

        venue = comp.get("venue") or {}
        addr = venue.get("address") or {}
        broadcasts = []
        for b in (comp.get("broadcasts") or []):
            broadcasts.extend(b.get("names") or [])

        h, a = team_info(home), team_info(away)
        out.append({
            "event_id": ev.get("id"),
            "league_slug": slug,
            "league": league_name,
            "commence_time": commence,
            "home": h,
            "away": a,
            "venue": {
                "name": venue.get("fullName"),
                "city": addr.get("city"),
                "country": addr.get("country"),
            },
            "broadcast": broadcasts,
            "odds": _parse_odds(comp),
        })
    return out


def get_fixtures(days_ahead: int = 3, force: bool = False) -> list[dict]:
    """All scheduled fixtures with odds across every tracked league. Cached."""
    if not force and CACHE_PATH.exists():
        try:
            if time.time() - CACHE_PATH.stat().st_mtime < CACHE_TTL:
                cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
                if cached:
                    return cached
        except Exception:
            pass

    now = datetime.now(timezone.utc)
    date_range = f"{now.strftime('%Y%m%d')}-{(now + timedelta(days=days_ahead)).strftime('%Y%m%d')}"

    fixtures: list[dict] = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        for chunk in pool.map(lambda s: _fetch_league(s, date_range), ESPN_CLUB_LEAGUES):
            fixtures.extend(chunk)

    # Drop fixtures that already kicked off
    cutoff = now.isoformat().replace("+00:00", "Z")
    fixtures = [f for f in fixtures if f["commence_time"] >= cutoff]
    fixtures.sort(key=lambda f: f["commence_time"])

    for f in fixtures:
        f["match_id"] = hashlib.md5(
            f"{f['home']['name']}{f['away']['name']}{f['commence_time']}".encode()
        ).hexdigest()

    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(fixtures, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    with_odds = sum(1 for f in fixtures if f["odds"].get("implied"))
    logger.info(f"ESPN: {len(fixtures)} fixtures across {len(ESPN_CLUB_LEAGUES)} leagues ({with_odds} priced)")
    return fixtures
