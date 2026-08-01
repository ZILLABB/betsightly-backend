"""
Multi-bookmaker price shopping.

This is the piece that decides whether the picks can make money at all.

Reading one bookmaker, the arithmetic is hopeless: DraftKings runs about a 9%
overround on these leagues, and our probabilities are derived from that same
book's prices, so the model reproduces the market and expected value settles
at roughly minus the margin. No amount of model work fixes that.

Across many books it changes completely. Measured on Arsenal vs Coventry with
39 books quoting: taking the best available price on each outcome gives an
overround of 0.9996 — the house edge is gone. The same match priced at one
book carries 9%. Individual quotes differ enormously (Coventry ranged 13.0 to
20.0, the draw 6.1 to 8.6), and that dispersion is the edge.

So this module does two things:

- **Consensus probability.** De-vig each book separately, then take the median
  across books. A median of forty opinions is a far better estimate of the
  true probability than any single book's line.
- **Best available price.** The highest quote on each outcome.

Value is then consensus_prob x best_price - 1, which is positive exactly when
one book is out of step with everyone else. That is a real, bankable edge,
unlike beating a single book's de-vigged number.

The Odds API free tier allows 500 credits a month, so requests are budgeted:
only leagues that actually appear in today's card are fetched, results are
cached, and a hard ceiling stops the month's allowance being spent in a day.
"""

import json
import logging
import os
import statistics
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).parent / "data" / "shopped_odds.json"
BUDGET_PATH = Path(__file__).parent / "data" / "odds_budget.json"
CACHE_TTL = 6 * 3600           # prices move; 6h keeps them usable and cheap

# Free tier is 500/month. Staying under a daily ceiling means a busy day
# cannot eat the whole allowance and leave the rest of the month blind.
DAILY_CREDIT_CEILING = 14
MONTHLY_CREDIT_CEILING = 460

# ESPN slug -> The Odds API sport key. Only leagues present on both sides can
# be shopped; anything unmapped simply keeps its single-book price.
SLUG_TO_ODDS_KEY = {
    "eng.1": "soccer_epl",
    "eng.2": "soccer_efl_champ",
    "eng.3": "soccer_england_league1",
    "eng.4": "soccer_england_league2",
    "eng.league_cup": "soccer_england_efl_cup",
    "esp.1": "soccer_spain_la_liga",
    "ger.1": "soccer_germany_bundesliga",
    "ger.2": "soccer_germany_bundesliga2",
    "ita.1": "soccer_italy_serie_a",
    "ita.2": "soccer_italy_serie_b",
    "fra.1": "soccer_france_ligue_one",
    "ned.1": "soccer_netherlands_eredivisie",
    "por.1": "soccer_portugal_primeira_liga",
    "bel.1": "soccer_belgium_first_div",
    "sui.1": "soccer_switzerland_superleague",
    "aut.1": "soccer_austria_bundesliga",
    "gre.1": "soccer_greece_super_league",
    "tur.1": "soccer_turkey_super_league",
    "sco.1": "soccer_spl",
    "den.1": "soccer_denmark_superliga",
    "nor.1": "soccer_norway_eliteserien",
    "swe.1": "soccer_sweden_allsvenskan",
    "pol.1": "soccer_poland_ekstraklasa",
    "rus.1": "soccer_russia_premier_league",
    "bra.1": "soccer_brazil_campeonato",
    "bra.2": "soccer_brazil_serie_b",
    "arg.1": "soccer_argentina_primera_division",
    "chi.1": "soccer_chile_campeonato",
    "mex.1": "soccer_mexico_ligamx",
    "usa.1": "soccer_usa_mls",
    "jpn.1": "soccer_japan_j_league",
    "kor.1": "soccer_korea_kleague1",
    "chn.1": "soccer_china_superleague",
    "fin.1": "soccer_finland_veikkausliiga",
    "irl.1": "soccer_league_of_ireland",
    "conmebol.libertadores": "soccer_conmebol_copa_libertadores",
    "conmebol.sudamericana": "soccer_conmebol_copa_sudamericana",
}


def _norm(name: str) -> str:
    if not name:
        return ""
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c)).lower()
    for token in ("fc ", "cf ", "sc ", "ac ", "afc ", "cd ", "ca ", "club "):
        if n.startswith(token):
            n = n[len(token):]
    for token in (" fc", " cf", " sc", " afc", " ii"):
        if n.endswith(token):
            n = n[: -len(token)]
    return " ".join(n.split())


# ── Credit budget ──────────────────────────────────────────

def _budget() -> dict:
    try:
        b = json.loads(BUDGET_PATH.read_text())
    except Exception:
        b = {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month = today[:7]
    if b.get("day") != today:
        b["day"], b["day_used"] = today, 0
    if b.get("month") != month:
        b["month"], b["month_used"] = month, 0
    return b


def _spend(credits: int) -> None:
    b = _budget()
    b["day_used"] = b.get("day_used", 0) + credits
    b["month_used"] = b.get("month_used", 0) + credits
    try:
        BUDGET_PATH.parent.mkdir(parents=True, exist_ok=True)
        BUDGET_PATH.write_text(json.dumps(b))
    except Exception:
        pass


def _can_spend(credits: int) -> bool:
    b = _budget()
    return (b.get("day_used", 0) + credits <= DAILY_CREDIT_CEILING
            and b.get("month_used", 0) + credits <= MONTHLY_CREDIT_CEILING)


def budget_status() -> dict:
    b = _budget()
    return {
        "day": b.get("day"), "day_used": b.get("day_used", 0),
        "day_ceiling": DAILY_CREDIT_CEILING,
        "month": b.get("month"), "month_used": b.get("month_used", 0),
        "month_ceiling": MONTHLY_CREDIT_CEILING,
    }


# ── Fetch + aggregate ──────────────────────────────────────

def _devig(prices: list[float]) -> list[float]:
    """Convert one book's quotes for a full market into fair probabilities."""
    inv = [1.0 / p for p in prices if p and p > 1.0]
    if len(inv) != len(prices) or not inv:
        return []
    total = sum(inv)
    return [i / total for i in inv]


def _fetch_league(sport_key: str, api_key: str) -> list[dict]:
    """One league's odds across EU + UK books. Costs regions x markets credits."""
    try:
        resp = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds",
            params={"apiKey": api_key, "regions": "eu,uk",
                    "markets": "h2h", "oddsFormat": "decimal"},
            timeout=30,
        )
        if resp.status_code != 200:
            logger.warning(f"odds shop {sport_key}: HTTP {resp.status_code}")
            return []
        used = int(resp.headers.get("x-requests-last", 2) or 2)
        _spend(used)
        return resp.json() or []
    except Exception as e:
        logger.warning(f"odds shop {sport_key} failed: {e}")
        return []


def _aggregate(event: dict) -> dict:
    """Best price and consensus probability per outcome for one fixture."""
    home, away = event.get("home_team", ""), event.get("away_team", "")
    best: dict[str, tuple[float, str]] = {}
    devigged: dict[str, list[float]] = {}

    for book in event.get("bookmakers", []):
        title = book.get("title", "")
        for market in book.get("markets", []):
            if market.get("key") != "h2h":
                continue
            outcomes = market.get("outcomes", [])
            names = [o.get("name", "") for o in outcomes]
            prices = [o.get("price", 0) for o in outcomes]
            fair = _devig(prices)
            for i, name in enumerate(names):
                price = prices[i]
                if not price or price <= 1.0:
                    continue
                if name not in best or price > best[name][0]:
                    best[name] = (price, title)
                if fair:
                    devigged.setdefault(name, []).append(fair[i])

    def key_for(name: str) -> str:
        if name == home:
            return "home_win"
        if name == away:
            return "away_win"
        return "draw"

    out = {"home_team": home, "away_team": away,
           "commence_time": event.get("commence_time", ""),
           "book_count": len(event.get("bookmakers", [])), "outcomes": {}}

    for name, (price, book) in best.items():
        samples = devigged.get(name, [])
        out["outcomes"][key_for(name)] = {
            "best_price": round(price, 3),
            "best_book": book,
            # Median across books: far more robust than any single line, and
            # immune to one outlier dragging the estimate around.
            "consensus_prob": round(statistics.median(samples), 4) if samples else None,
            "books": len(samples),
        }
    return out


def shop_odds(league_slugs: list[str], force: bool = False) -> dict:
    """Shopped prices keyed by "home|away". Respects cache and credit budget."""
    api_key = os.getenv("ODDS_API_KEY", "")
    if not api_key:
        return {}

    cache: dict = {}
    if not force and CACHE_PATH.exists():
        try:
            blob = json.loads(CACHE_PATH.read_text())
            if time.time() - blob.get("ts", 0) < CACHE_TTL:
                return blob.get("data", {})
            cache = blob.get("data", {})
        except Exception:
            pass

    keys = []
    for slug in league_slugs:
        k = SLUG_TO_ODDS_KEY.get(slug)
        if k and k not in keys:
            keys.append(k)

    data = dict(cache)
    for sport_key in keys:
        if not _can_spend(2):
            logger.info(f"odds shop: credit ceiling reached, skipping {sport_key}")
            break
        for event in _fetch_league(sport_key, api_key):
            agg = _aggregate(event)
            if agg["outcomes"]:
                data[f"{_norm(agg['home_team'])}|{_norm(agg['away_team'])}"] = agg

    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps({"ts": time.time(), "data": data}))
    except Exception:
        pass

    logger.info(f"odds shop: {len(data)} fixtures priced, budget={budget_status()}")
    return data


def lookup(shopped: dict, home: str, away: str) -> dict | None:
    """Shopped prices for a fixture, tolerating naming differences."""
    if not shopped:
        return None
    h, a = _norm(home), _norm(away)
    hit = shopped.get(f"{h}|{a}")
    if hit:
        return hit
    # Fall back to a containment match — feeds disagree on club suffixes
    for key, val in shopped.items():
        kh, ka = key.split("|", 1) if "|" in key else ("", "")
        if not kh or not ka:
            continue
        if (kh in h or h in kh) and (ka in a or a in ka):
            return val
    return None
