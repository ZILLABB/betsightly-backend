"""
SportyBet price adapter.

Supplies a second opinion on price, and — more usefully — the *margin* behind
each price. The engine stays bookmaker-neutral: nothing here reaches into the
predictor, the calibrator or selection. This module normalises one book's
board into the project's own market vocabulary and hands back a plain dict.

Why margin matters enough to have its own module. Every published slip is
capped by the bookmaker's cut, and the cut is not uniform. Measured across 296
Over 1.5 markets on one board, the median overround was 5.95% and the tightest
decile 4.03% — nearly two points of difference between fixtures, in the same
book, on the same day, for the same market. Preferring the cheaper side of that
spread is the only edge available without paying for a second price feed, and
unlike an edge from the model it cannot decay: it is arithmetic on a number the
book publishes itself.

The distinction the rest of the codebase relies on:

    odds_shop  — many books, best price, needs paid credits
    sportybet  — one book, real price *and* its margin, free

Both hand back the same shape, so `picks.py` does not care which spoke.

Only the ordinary public board endpoint is used. Nothing here authenticates,
spoofs, or works around a control; if SportyBet closes the endpoint this
degrades to "no prices" and the card falls back to estimated ones exactly as it
does today.
"""

import json
import logging
import os
import unicodedata
import urllib.request

logger = logging.getLogger(__name__)

BASE_URL = os.getenv("SPORTYBET_BASE_URL", "https://www.sportybet.com")
OPER_ID = os.getenv("SPORTYBET_OPER_ID", "2")  # Nigeria

# Markets worth pulling. Each costs nothing extra — they arrive on the same
# response — but every one widens how many picks can carry a real price.
_MARKET_IDS = "1,18,10,29"

_PAGE_SIZE = 100
_MAX_PAGES = 12
_CACHE_KEY = "sportybet_board"
_CACHE_TTL_HOURS = 3.0


# ── Market vocabulary ──────────────────────────────────────
# Verified against the live board: outcome ids are stable per market, and the
# Over/Under market is distinguished by its `specifier` rather than its id.

_FIXED = {
    "1": {"1": "home_win", "2": "draw", "3": "away_win"},
    "10": {"9": "home_or_draw", "10": "home_or_away", "11": "away_or_draw"},
    "29": {"74": "btts_yes", "76": "btts_no"},
}

_OVER_UNDER = {
    "total=1.5": ("over_1_5", "under_1_5"),
    "total=2.5": ("over_2_5", "under_2_5"),
    "total=3.5": ("over_3_5", "under_3_5"),
}

# Double chance quotes three outcomes that each cover two of three results, so
# the book's implied probabilities sum to 2.0 rather than 1.0 when the margin
# is zero. Dividing by the number of results each selection covers puts every
# market's overround on the same scale.
_COVERAGE = {"10": 2.0}


# Letters NFKD will not take apart, because they are distinct letters rather
# than a base plus an accent. Missing these is why "Brøndby" and "Brondby"
# failed to meet.
_LETTERS = str.maketrans({
    "ø": "o", "æ": "ae", "å": "a", "ð": "d", "þ": "th", "đ": "d",
    "ł": "l", "ß": "ss", "ı": "i", "œ": "oe",
})

# Words that identify a club as a club rather than identifying *which* club.
# Dropped wherever they appear, not only at the ends, since feeds disagree on
# placement as much as on presence.
_NOISE = {
    "fc", "cf", "sc", "ac", "afc", "cd", "ca", "club", "if", "sk", "bk", "ik",
    "sv", "vfl", "vfb", "tsv", "fsv", "spvgg", "bsc", "csd", "cdd", "ec", "sd",
    "as", "ss", "us", "ud", "cs", "rc", "sl", "aa", "ff", "gf", "ogc", "rcd",
    "sfk", "spor", "kulubu", "de", "do", "da", "the", "ii",
}

_RE_PAREN = None
_RE_YEAR = None


def _norm(name: str) -> str:
    """Comparable form of a club name, tolerant of how feeds spell things.

    Feeds disagree in four consistent ways, and each is handled here rather
    than left to fuzzy matching, which would risk pairing the wrong fixture
    and attaching the wrong price — a worse outcome than no price at all.

      accents      Brøndby IF            -> brondby
      qualifiers   Central Cordoba (Sa..)-> central cordoba
      state codes  Athletico-PR          -> athletico
      founding yr  SC Verl 1924          -> verl
    """
    global _RE_PAREN, _RE_YEAR
    if _RE_PAREN is None:
        import re
        _RE_PAREN = re.compile(r"\([^)]*\)?")
        _RE_YEAR = re.compile(r"\b(1[89]\d{2}|20[0-2]\d)\b")

    if not name:
        return ""
    n = name.lower().translate(_LETTERS)
    n = unicodedata.normalize("NFKD", n)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = _RE_PAREN.sub(" ", n)
    n = _RE_YEAR.sub(" ", n)
    # Brazilian and Argentine feeds tack the state on with a hyphen; ESPN and
    # SportyBet disagree about whether to include it at all.
    n = n.replace("-", " ")
    tokens = [t for t in n.split() if t and t not in _NOISE and len(t) > 1]
    # Never reduce a name to nothing: a club genuinely called "CD" keeps it.
    if not tokens:
        tokens = n.split()
    return " ".join(tokens)


def _tokens(norm_name: str) -> set:
    return {t for t in norm_name.split() if len(t) > 2}


# A club's youth or reserve side is a different team with different players and
# a different price. Matching across the two is not a near miss, it is wrong —
# and it also breaks fixtures that would otherwise resolve, because a senior
# side and its U19 both answer to the same shortened name and the ambiguity
# guard then rejects both.
_AGE_MARKERS = ("u23", "u21", "u20", "u19", "u18", "u17")
_SQUAD_WORDS = ("jong", "reserves", "reserve", "youth", "academy")


def _squad(raw_name: str) -> str:
    """Which side of a club this is: senior, a youth age group, or reserves."""
    n = (raw_name or "").lower()
    compact = n.replace("-", "").replace(" ", "")
    for m in _AGE_MARKERS:
        if m in compact:
            return m
    for w in _SQUAD_WORDS:
        if w in n:
            return "reserve"
    if n.endswith(" ii") or n.endswith(" b"):
        return "reserve"
    return ""


def _fold(token: str) -> str:
    """Collapse the ways feeds transliterate the same letter.

    ESPN writes Brøndby and SportyBet writes Broendby; both mean the same o.
    Folding the digraphs makes them comparable without loosening anything
    else, since no distinct pair of clubs differs only by an "oe"/"o".
    """
    return (token.replace("oe", "o").replace("ae", "a")
                 .replace("ue", "u").replace("aa", "a"))


def _token_match(x: str, y: str) -> bool:
    if x == y:
        return True
    fx, fy = _fold(x), _fold(y)
    if fx == fy:
        return True
    # Hamburg/Hamburger, Djurgarden/Djurgardens. Bounded tightly: a real
    # prefix, both reasonably long, and only a short tail of difference, so
    # this cannot pair two genuinely different clubs.
    short, long_ = (fx, fy) if len(fx) <= len(fy) else (fy, fx)
    return (len(short) >= 5 and len(long_) - len(short) <= 3
            and long_.startswith(short))


def _same_team(a: str, b: str) -> bool:
    """Whether two normalised names denote the same club.

    Strict by design. Containment alone pairs "Everton" with "Everton CD" —
    two different clubs on two continents — so a containment hit must also
    agree on every significant token of the shorter name.
    """
    if a == b:
        return True
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return all(any(_token_match(s, l) for l in long_) for s in short)


def _db_get(key: str):
    try:
        from sqlalchemy import text
        from database import engine
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS bookmaker_cache ("
                "k VARCHAR(48) PRIMARY KEY, v TEXT)"))
            row = conn.execute(text("SELECT v FROM bookmaker_cache WHERE k = :k"),
                               {"k": key}).fetchone()
        return json.loads(row[0]) if row and row[0] else None
    except Exception:
        return None


def _db_set(key: str, value) -> None:
    try:
        from sqlalchemy import text
        from database import engine
        payload = json.dumps(value)
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS bookmaker_cache ("
                "k VARCHAR(48) PRIMARY KEY, v TEXT)"))
            updated = conn.execute(
                text("UPDATE bookmaker_cache SET v = :v WHERE k = :k"),
                {"k": key, "v": payload}).rowcount
            if not updated:
                conn.execute(
                    text("INSERT INTO bookmaker_cache (k, v) VALUES (:k, :v)"),
                    {"k": key, "v": payload})
    except Exception as e:
        logger.debug(f"sportybet cache persist failed: {e}")


def _get_json(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _parse_event(ev: dict) -> dict | None:
    """One fixture's prices and per-market margins in our own vocabulary."""
    home = ev.get("homeTeamName") or ""
    away = ev.get("awayTeamName") or ""
    if not home or not away:
        return None

    prices: dict[str, float] = {}
    margins: dict[str, float] = {}

    for m in ev.get("markets") or []:
        mid = str(m.get("id") or "")
        spec = m.get("specifier") or ""
        outcomes = m.get("outcomes") or []

        if mid in _FIXED:
            mapping = _FIXED[mid]
        elif mid == "18" and spec in _OVER_UNDER:
            over_key, under_key = _OVER_UNDER[spec]
            mapping = {}
            for o in outcomes:
                desc = (o.get("desc") or "").lower()
                if desc.startswith("over"):
                    mapping[str(o.get("id"))] = over_key
                elif desc.startswith("under"):
                    mapping[str(o.get("id"))] = under_key
        else:
            continue

        priced: dict[str, float] = {}
        for o in outcomes:
            key = mapping.get(str(o.get("id")))
            if not key:
                continue
            try:
                price = float(o.get("odds"))
            except (TypeError, ValueError):
                continue
            if price > 1.0:
                priced[key] = price

        # A margin only means something across a market's full set of
        # outcomes. A partial quote — one side suspended — would read as a
        # suspiciously cheap market and pull selection straight towards it.
        if len(priced) < len(mapping) or not priced:
            prices.update(priced)
            continue

        overround = sum(1.0 / p for p in priced.values()) / _COVERAGE.get(mid, 1.0)
        margin = round(overround - 1.0, 5)
        for key, price in priced.items():
            prices[key] = round(price, 3)
            margins[key] = margin

    if not prices:
        return None

    return {
        "event_id": ev.get("eventId"),
        "home_team": home,
        "away_team": away,
        "home_squad": _squad(home),
        "away_squad": _squad(away),
        "kickoff_ms": ev.get("estimateStartTime"),
        "prices": prices,
        "margins": margins,
    }


def fetch_board(max_pages: int = _MAX_PAGES, force: bool = False) -> dict:
    """The upcoming board keyed by "home|away". Cached; {} when unavailable."""
    if not force:
        cached = _db_get(_CACHE_KEY)
        if cached:
            import time
            age_h = (time.time() - cached.get("fetched_at", 0)) / 3600.0
            if age_h < _CACHE_TTL_HOURS and cached.get("fixtures"):
                return cached["fixtures"]

    fixtures: dict[str, dict] = {}
    try:
        for page in range(1, max_pages + 1):
            url = (f"{BASE_URL}/api/ng/factsCenter/pcUpcomingEvents"
                   f"?sportId=sr%3Asport%3A1&marketId={_MARKET_IDS}"
                   f"&pageSize={_PAGE_SIZE}&pageNum={page}")
            payload = _get_json(url)
            data = (payload or {}).get("data") or {}
            tournaments = data.get("tournaments") or []
            if not tournaments:
                break
            before = len(fixtures)
            for t in tournaments:
                for ev in t.get("events") or []:
                    parsed = _parse_event(ev)
                    if not parsed:
                        continue
                    parsed["competition"] = t.get("name")
                    key = f"{_norm(parsed['home_team'])}|{_norm(parsed['away_team'])}"
                    fixtures[key] = parsed
            if len(fixtures) == before:
                break
            if len(fixtures) >= int(data.get("totalNum") or 0) > 0:
                break
    except Exception as e:
        logger.warning(f"sportybet board fetch failed: {e}")
        if not fixtures:
            stale = _db_get(_CACHE_KEY)
            return (stale or {}).get("fixtures") or {}

    if fixtures:
        import time
        _db_set(_CACHE_KEY, {"fetched_at": time.time(), "fixtures": fixtures})
    logger.info(f"sportybet board: {len(fixtures)} fixtures priced")
    return fixtures


def _kickoff_ok(entry: dict, commence: str, tolerance_h: float = 6.0) -> bool:
    """Whether a candidate fixture kicks off close enough to be the same match.

    The guard that name matching cannot provide. Arsenal of London and Arsenal
    de Sarandi normalise to the same single token, and no amount of string
    care separates them — but they do not kick off within six hours of each
    other. Where either feed is missing a time this abstains rather than
    blocking, so a missing timestamp costs coverage but never correctness.
    """
    if not commence or not entry.get("kickoff_ms"):
        return True
    try:
        from datetime import datetime, timezone
        want = datetime.fromisoformat(commence.replace("Z", "+00:00"))
        got = datetime.fromtimestamp(entry["kickoff_ms"] / 1000.0, tz=timezone.utc)
        return abs((want - got).total_seconds()) <= tolerance_h * 3600
    except Exception:
        return True


def lookup(board: dict, home: str, away: str,
           commence: str = "") -> dict | None:
    """One fixture's prices, tolerating naming differences between feeds."""
    if not board:
        return None
    h, a = _norm(home), _norm(away)
    hs, as_ = _squad(home), _squad(away)
    hit = board.get(f"{h}|{a}")
    if hit and _kickoff_ok(hit, commence):
        return hit
    # Both sides must agree, the squads must agree, and only one fixture may
    # qualify. An ambiguous match is discarded rather than guessed: pricing a
    # slip off the wrong fixture is a worse failure than showing an estimated
    # price.
    found = None
    for key, val in board.items():
        kh, ka = key.split("|", 1) if "|" in key else ("", "")
        if not kh or not ka:
            continue
        if val.get("home_squad", "") != hs or val.get("away_squad", "") != as_:
            continue
        if not _kickoff_ok(val, commence):
            continue
        if _same_team(kh, h) and _same_team(ka, a):
            if found is not None:
                return None
            found = val
    return found


def apply_to_fixtures(fixtures: list[dict], board: dict | None = None) -> int:
    """Attach real prices and per-market margins. Returns fixtures matched.

    Deliberately does *not* touch `implied`. That key is what `predictor.py`
    reads to decide `has_market`, and feeding a second book's probabilities
    into it would change every prediction on the board — a far larger change
    than pricing, and one that would invalidate a calibration fit currently
    sitting at 401 legs and 73.1% against 70.8% promised. Prices and margins
    are display-and-selection concerns; probabilities are model inputs. Only
    the former move here.

    Merging a second book's prices over the first is safe for the same reason:
    `edge` is measured against `implied`, which stays as the original feed left
    it, so edge still compares our probability to a consensus while the price
    shown is the one a reader can actually take.
    """
    if board is None:
        board = fetch_board()
    if not board:
        return 0

    matched = 0
    for fx in fixtures:
        try:
            hit = lookup(board, fx["home"]["name"], fx["away"]["name"],
                         fx.get("commence_time", ""))
        except (KeyError, TypeError):
            continue
        if not hit:
            continue
        odds = dict(fx.get("odds") or {})
        odds.update(hit["prices"])
        odds["margins"] = hit["margins"]
        odds["provider"] = "SportyBet"
        odds["sportybet_event_id"] = hit["event_id"]
        fx["odds"] = odds
        matched += 1
    return matched


def board_status() -> dict:
    """What the cache holds, for the admin dashboard and health checks."""
    import time
    cached = _db_get(_CACHE_KEY) or {}
    fixtures = cached.get("fixtures") or {}
    margins = [m for f in fixtures.values() for m in (f.get("margins") or {}).values()]
    out = {
        "fixtures": len(fixtures),
        "cache_age_hours": (round((time.time() - cached["fetched_at"]) / 3600.0, 2)
                            if cached.get("fetched_at") else None),
        "base_url": BASE_URL,
        "priced_markets": len(margins),
    }
    if margins:
        margins.sort()
        out["margin_median"] = round(margins[len(margins) // 2], 5)
        out["margin_best_decile"] = round(margins[max(0, len(margins) // 10)], 5)
    return out
