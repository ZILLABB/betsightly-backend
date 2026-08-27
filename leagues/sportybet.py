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
import hashlib
import logging
import math
import os
import time
import unicodedata
import urllib.request

logger = logging.getLogger(__name__)

BASE_URL = os.getenv("SPORTYBET_BASE_URL", "https://www.sportybet.com")
OPER_ID = os.getenv("SPORTYBET_OPER_ID", "2")  # Nigeria

# Markets worth pulling. Each costs nothing extra — they arrive on the same
# response — but every one widens how many picks can carry a real price.
_MARKET_IDS = "1,18,10,29,11,19,20"

_PAGE_SIZE = 100
_MAX_PAGES = 40
_CACHE_KEY = "sportybet_board"
_CACHE_TTL_HOURS = 3.0
try:
    KICKOFF_TOLERANCE_MINUTES = max(
        1, float(os.getenv("SPORTYBET_KICKOFF_TOLERANCE_MINUTES", "45")))
except ValueError:
    KICKOFF_TOLERANCE_MINUTES = 45.0


# One canonical mapping used by pricing, candidate availability and booking.
# Keeping these identifiers in two modules allowed the parser to say a market
# existed while booking constructed a different selection tuple.
MARKET_TO_SPORTYBET = {
    "home_win":     ("1", "", "1"),
    "draw":         ("1", "", "2"),
    "away_win":     ("1", "", "3"),
    "home_or_draw": ("10", "", "9"),
    "home_or_away": ("10", "", "10"),
    "away_or_draw": ("10", "", "11"),
    "over_1_5":     ("18", "total=1.5", "12"),
    "under_1_5":    ("18", "total=1.5", "13"),
    "over_2_5":     ("18", "total=2.5", "12"),
    "under_2_5":    ("18", "total=2.5", "13"),
    "over_3_5":     ("18", "total=3.5", "12"),
    "under_3_5":    ("18", "total=3.5", "13"),
    "over_4_5":     ("18", "total=4.5", "12"),
    "under_4_5":    ("18", "total=4.5", "13"),
    "btts_yes":     ("29", "", "74"),
    "btts_no":      ("29", "", "76"),
    "dnb_home":     ("11", "", "4"),
    "dnb_away":     ("11", "", "5"),
    "home_over_0_5": ("19", "total=0.5", "12"),
    "home_under_0_5": ("19", "total=0.5", "13"),
    "home_over_1_5": ("19", "total=1.5", "12"),
    "home_under_1_5": ("19", "total=1.5", "13"),
    "away_over_0_5": ("20", "total=0.5", "12"),
    "away_under_0_5": ("20", "total=0.5", "13"),
    "away_over_1_5": ("20", "total=1.5", "12"),
    "away_under_1_5": ("20", "total=1.5", "13"),
}


# ── Market vocabulary ──────────────────────────────────────
# Verified against the live board: outcome ids are stable per market, and the
# Over/Under market is distinguished by its `specifier` rather than its id.

_FIXED = {
    "1": {"1": "home_win", "2": "draw", "3": "away_win"},
    "10": {"9": "home_or_draw", "10": "home_or_away", "11": "away_or_draw"},
    "29": {"74": "btts_yes", "76": "btts_no"},
    "11": {"4": "dnb_home", "5": "dnb_away"},
}

# Market 18 is the match total; 19 and 20 are the same structure per team, so
# outcome ids repeat across all three and only the market id separates them.
_OVER_UNDER = {
    "18": {
        "total=1.5": ("over_1_5", "under_1_5"),
        "total=2.5": ("over_2_5", "under_2_5"),
        "total=3.5": ("over_3_5", "under_3_5"),
        "total=4.5": ("over_4_5", "under_4_5"),
    },
    "19": {
        "total=0.5": ("home_over_0_5", "home_under_0_5"),
        "total=1.5": ("home_over_1_5", "home_under_1_5"),
    },
    "20": {
        "total=0.5": ("away_over_0_5", "away_under_0_5"),
        "total=1.5": ("away_over_1_5", "away_under_1_5"),
    },
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

# Clubs the two feeds call different things. Not spelling variants — different
# names for the same team, which no amount of normalisation resolves, because
# there is no shared substring to work from. Athletico Paranaense is
# "Athletico-PR" to ESPN and "Paranaense" to SportyBet; Wolverhampton
# Wanderers is "Wolves". Both sides are normalised before lookup, so keys here
# are in normalised form.
#
# Kept deliberately short. Every entry is a hand-verified pair, because a
# wrong alias silently prices a slip off the wrong match — the failure this
# whole module is arranged to avoid.
_ALIASES = {
    "wolverhampton wanderers": "wolves",
    "athletico pr": "paranaense",
    "atletico pr": "paranaense",
    "crb": "cr brasil",
    "america mineiro": "america mg",
    "atletico mineiro": "atletico mg",
    "gremio": "gremio rs",
    "internacional": "internacional rs",
    "vasco da gama": "vasco",
    "brighton hove albion": "brighton",
    "tottenham hotspur": "tottenham",
    "manchester united": "man utd",
    "manchester city": "man city",
    "newcastle united": "newcastle",
    "west ham united": "west ham",
    "nottingham forest": "nottm forest",
    "borussia monchengladbach": "monchengladbach",
    "bayer leverkusen": "leverkusen",
    "paris saint germain": "psg",
    "inter milan": "inter",
    "sporting cp": "sporting",
}


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
    out = " ".join(tokens)
    # Applied last, so an alias is written in the same normalised form both
    # feeds arrive in and one entry covers every spelling of either side.
    return _ALIASES.get(out, out)


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
    """One fixture, including every exact market/outcome availability state."""
    home = ev.get("homeTeamName") or ""
    away = ev.get("awayTeamName") or ""
    if not home or not away:
        return None

    prices: dict[str, float] = {}
    margins: dict[str, float] = {}
    market_refs: dict[str, dict] = {}

    def _active(value) -> bool:
        # Some payloads omit isActive; an explicitly false/zero value is the
        # only safe evidence that the outcome is suspended.
        return value not in (False, 0, "0", "false", "False")

    for m in ev.get("markets") or []:
        mid = str(m.get("id") or "")
        spec = m.get("specifier") or ""
        outcomes = m.get("outcomes") or []
        canonical = {
            key: outcome_id
            for key, (market_id, wanted_spec, outcome_id)
            in MARKET_TO_SPORTYBET.items()
            if market_id == mid and wanted_spec == spec
        }
        if not canonical:
            continue

        raw_outcomes = {str(o.get("id") or ""): o for o in outcomes}
        priced: dict[str, float] = {}
        expected_keys: list[str] = []
        market_key = f"{mid}|{spec}"
        market_refs[market_key] = {"market_id": mid, "specifier": spec,
                                   "outcomes": {}}

        for key, outcome_id in canonical.items():
            expected_keys.append(key)
            o = raw_outcomes.get(outcome_id)
            if o is None:
                continue
            active = _active(o.get("isActive", True))
            raw_odds = o.get("odds")
            try:
                price = float(raw_odds)
            except (TypeError, ValueError):
                price = None
            valid_odds = price is not None and price > 1.0
            market_refs[market_key]["outcomes"][outcome_id] = {
                "outcome_id": outcome_id,
                "active": active,
                "odds": round(price, 3) if valid_odds else None,
                "description": o.get("desc"),
            }
            if active and valid_odds:
                priced[key] = price

        # A margin only means something when every canonical outcome for that
        # market is active and priced. A partial quote still keeps its valid
        # prices but cannot masquerade as a suspiciously cheap market.
        prices.update({key: round(price, 3) for key, price in priced.items()})
        if expected_keys and len(priced) == len(expected_keys):
            overround = (sum(1.0 / p for p in priced.values())
                         / _COVERAGE.get(mid, 1.0))
            margin = round(overround - 1.0, 5)
            for key in priced:
                margins[key] = margin

    return {
        "event_id": ev.get("eventId"),
        "home_team": home,
        "away_team": away,
        "home_squad": _squad(home),
        "away_squad": _squad(away),
        "kickoff_ms": ev.get("estimateStartTime"),
        "prices": prices,
        "margins": margins,
        "market_refs": market_refs,
    }


def board_metadata(board: dict | None) -> dict:
    return dict((board or {}).get("__meta__") or {})


def _board_entries(board: dict | None):
    """Yield entries from both the collision-safe and legacy test shapes."""
    for key, value in (board or {}).items():
        if key.startswith("__"):
            continue
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, dict):
                    yield key, entry
        elif isinstance(value, dict):
            yield key, value


def _snapshot(fixtures: dict, metadata: dict) -> dict:
    return {"__meta__": metadata, **fixtures}


def fetch_board(max_pages: int = _MAX_PAGES, force: bool = False) -> dict:
    """Complete upcoming board, collision-safe and cached as one snapshot."""
    cached = _db_get(_CACHE_KEY)
    if not force and cached:
        age_h = (time.time() - cached.get("fetched_at", 0)) / 3600.0
        metadata = cached.get("metadata") or {}
        # Old cache entries had no completeness metadata. Refetch them instead
        # of reusing a board which may have silently stopped at page twelve.
        if (age_h < _CACHE_TTL_HOURS and cached.get("fixtures")
                and metadata.get("is_complete") is True):
            return _snapshot(cached["fixtures"], metadata)

    fixtures: dict[str, list[dict]] = {}
    declared_total = 0
    fetched_total = 0
    page_count = 0
    error = None
    required_pages = 1

    try:
        for page in range(1, max_pages + 1):
            url = (f"{BASE_URL}/api/ng/factsCenter/pcUpcomingEvents"
                   f"?sportId=sr%3Asport%3A1&marketId={_MARKET_IDS}"
                   f"&pageSize={_PAGE_SIZE}&pageNum={page}")
            payload = _get_json(url)
            data = (payload or {}).get("data") or {}
            if page == 1:
                try:
                    declared_total = max(0, int(data.get("totalNum") or 0))
                except (TypeError, ValueError):
                    declared_total = 0
                required_pages = (math.ceil(declared_total / _PAGE_SIZE)
                                  if declared_total else max_pages)

            tournaments = data.get("tournaments") or []
            if not tournaments:
                # An empty page is complete only after the declared total has
                # already been consumed. Otherwise it is a partial response.
                if declared_total and fetched_total < declared_total:
                    error = f"empty page {page} before declared total"
                break

            page_count = page
            page_events = 0
            for tournament in tournaments:
                for ev in tournament.get("events") or []:
                    page_events += 1
                    parsed = _parse_event(ev)
                    if not parsed:
                        continue
                    parsed["competition"] = tournament.get("name")
                    key = (f"{_norm(parsed['home_team'])}|"
                           f"{_norm(parsed['away_team'])}")
                    bucket = fixtures.setdefault(key, [])
                    # Pages can repeat a boundary event. Preserve genuinely
                    # repeated fixtures on different dates, not duplicates.
                    if not any(str(x.get("event_id")) == str(parsed.get("event_id"))
                               for x in bucket):
                        bucket.append(parsed)
            fetched_total += page_events

            if declared_total and fetched_total >= declared_total:
                break
            if page >= required_pages and not declared_total:
                break

        if declared_total and required_pages > max_pages:
            error = (f"declared total needs {required_pages} pages; "
                     f"defensive maximum is {max_pages}")
    except Exception as exc:
        error = f"{type(exc).__name__}: {str(exc)[:180]}"
        logger.warning(f"sportybet board fetch failed: {exc}")

    is_complete = bool(declared_total and fetched_total >= declared_total
                       and page_count >= required_pages and not error)
    fetched_at = time.time()
    snapshot_id = hashlib.sha256(
        f"{fetched_at:.6f}|{declared_total}|{fetched_total}|{page_count}".encode()
    ).hexdigest()[:16]
    metadata = {
        "snapshot_id": snapshot_id,
        "declared_total": declared_total,
        "fetched_total": fetched_total,
        "page_count": page_count,
        "required_pages": required_pages,
        "is_complete": is_complete,
        "fetched_at": fetched_at,
        "error": error,
    }

    if fixtures:
        _db_set(_CACHE_KEY, {"fetched_at": fetched_at, "fixtures": fixtures,
                             "metadata": metadata})
        board = _snapshot(fixtures, metadata)
    else:
        stale = cached or {}
        stale_fixtures = stale.get("fixtures") or {}
        stale_meta = dict(stale.get("metadata") or {})
        stale_meta.update({"is_complete": False,
                           "error": error or "no fixtures returned",
                           "snapshot_id": stale_meta.get("snapshot_id")})
        board = _snapshot(stale_fixtures, stale_meta) if stale_fixtures else {
            "__meta__": metadata}

    parsed_count = sum(1 for _ in _board_entries(board))
    logger.info(
        f"sportybet board: {parsed_count}/{declared_total or '?'} fixtures, "
        f"{page_count} page(s), complete={is_complete}")
    return board


def _kickoff_delta_minutes(entry: dict, commence: str) -> float | None:
    if not commence or not entry.get("kickoff_ms"):
        return None
    try:
        from datetime import datetime, timezone
        want = datetime.fromisoformat(commence.replace("Z", "+00:00"))
        if want.tzinfo is None:
            want = want.replace(tzinfo=timezone.utc)
        got = datetime.fromtimestamp(entry["kickoff_ms"] / 1000.0,
                                     tz=timezone.utc)
        return abs((want - got).total_seconds()) / 60.0
    except (TypeError, ValueError, OSError):
        return None


def _kickoff_ok(entry: dict, commence: str,
                tolerance_h: float | None = None) -> bool:
    """Strict time guard retained as a bool for existing callers/tests."""
    delta = _kickoff_delta_minutes(entry, commence)
    if delta is None:
        return False
    tolerance = (KICKOFF_TOLERANCE_MINUTES if tolerance_h is None
                 else tolerance_h * 60.0)
    return delta <= tolerance


_COMPETITION_ALIASES = {
    "carabao cup": "efl cup",
    "english league cup": "efl cup",
    "division profesional bolivia": "division profesional",
    "división profesional bolivia": "division profesional",
    "efl championship": "championship",
}


def _norm_competition(value: str) -> str:
    n = (value or "").lower().translate(_LETTERS)
    n = unicodedata.normalize("NFKD", n)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = " ".join("".join(c if c.isalnum() else " " for c in n).split())
    return _COMPETITION_ALIASES.get(n, n)


def _league_score(provider_league: str, sporty_competition: str) -> float:
    a, b = _norm_competition(provider_league), _norm_competition(sporty_competition)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ta = {x for x in a.split() if len(x) > 2}
    tb = {x for x in b.split() if len(x) > 2}
    return len(ta & tb) / max(1, len(ta | tb))


def match_fixture(board: dict, home: str, away: str, commence: str = "",
                  league: str = "") -> dict:
    """Resolve one provider fixture with explicit failure diagnostics."""
    meta = board_metadata(board)
    base = {"entry": None, "snapshot_id": meta.get("snapshot_id"),
            "fixture_match_method": None, "fixture_match_confidence": 0.0,
            "failure_reason": None, "league_diagnostic": None}
    if not board or not any(True for _ in _board_entries(board)):
        return {**base, "status": "SPORTYBET_DATA_ERROR",
                "failure_reason": meta.get("error") or "SportyBet board unavailable"}

    h, a = _norm(home), _norm(away)
    hs, as_ = _squad(home), _squad(away)
    exact_key = f"{h}|{a}"
    exact_values = board.get(exact_key) or []
    if isinstance(exact_values, dict):
        exact_values = [exact_values]

    team_candidates: list[tuple[str, dict, str]] = []
    for entry in exact_values:
        if (entry.get("home_squad", "") == hs
                and entry.get("away_squad", "") == as_):
            team_candidates.append((exact_key, entry, "exact"))

    if not team_candidates:
        for key, entry in _board_entries(board):
            kh, ka = key.split("|", 1) if "|" in key else ("", "")
            if not kh or not ka:
                continue
            if (entry.get("home_squad", "") != hs
                    or entry.get("away_squad", "") != as_):
                continue
            if _same_team(kh, h) and _same_team(ka, a):
                team_candidates.append((key, entry, "normalized"))

    if not team_candidates:
        status = ("FIXTURE_NOT_FOUND" if (meta.get("is_complete") is True
                  or ("is_complete" not in meta and bool(board)))
                  else "SPORTYBET_DATA_ERROR")
        why = ("fixture is not present on the complete SportyBet board"
               if status == "FIXTURE_NOT_FOUND"
               else "fixture missing from an incomplete SportyBet board")
        return {**base, "status": status, "failure_reason": why}

    timed: list[tuple[str, dict, str, float]] = []
    unparsable = False
    for key, entry, method in team_candidates:
        delta = _kickoff_delta_minutes(entry, commence)
        if delta is None:
            unparsable = True
            continue
        if delta <= KICKOFF_TOLERANCE_MINUTES:
            timed.append((key, entry, method, delta))

    if not timed:
        return {**base,
                "status": "FIXTURE_MAPPING_FAILED" if unparsable else "KICKOFF_MISMATCH",
                "failure_reason": ("kickoff timestamp missing or invalid"
                                   if unparsable else
                                   f"no team match within {KICKOFF_TOLERANCE_MINUTES} minutes")}

    # Exact names and the nearest kickoff lead. League is supporting evidence
    # and only resolves a collision; it can never override a team/time conflict.
    ranked = sorted(
        timed,
        key=lambda item: (
            item[2] == "exact",
            _league_score(league, item[1].get("competition") or ""),
            -item[3],
        ),
        reverse=True,
    )
    best = ranked[0]
    if len(ranked) > 1:
        first_key = (best[2] == "exact",
                     round(_league_score(league, best[1].get("competition") or ""), 3),
                     round(best[3], 2))
        second = ranked[1]
        second_key = (second[2] == "exact",
                      round(_league_score(league, second[1].get("competition") or ""), 3),
                      round(second[3], 2))
        if first_key == second_key:
            return {**base, "status": "FIXTURE_MAPPING_FAILED",
                    "failure_reason": "multiple SportyBet fixtures match teams and kickoff"}

    league_score = _league_score(league, best[1].get("competition") or "")
    league_diag = "LEAGUE_MISMATCH" if league and league_score == 0 else None
    confidence = 1.0 if best[2] == "exact" else 0.9
    if best[3] > 5:
        confidence -= 0.05
    if league_diag:
        confidence -= 0.1
    return {**base, "status": "MATCHED", "entry": best[1],
            "fixture_match_method": best[2],
            "fixture_match_confidence": round(max(0.0, confidence), 2),
            "league_diagnostic": league_diag}


def availability_for(board: dict, home: str, away: str, commence: str,
                     league: str, market: str) -> dict:
    """Exact fixture + market + outcome + active odds availability."""
    matched = match_fixture(board, home, away, commence, league)
    base = {
        "status": matched["status"], "sportybet_available": False,
        "event_id": None, "market_id": None, "outcome_id": None,
        "specifier": None, "sportybet_odds": None,
        "fixture_match_method": matched.get("fixture_match_method"),
        "fixture_match_confidence": matched.get("fixture_match_confidence", 0.0),
        "failure_reason": matched.get("failure_reason"),
        "board_snapshot_id": matched.get("snapshot_id"),
        "league_diagnostic": matched.get("league_diagnostic"),
    }
    entry = matched.get("entry")
    if matched["status"] != "MATCHED" or not entry:
        return base

    mapping = MARKET_TO_SPORTYBET.get(market)
    if not mapping:
        return {**base, "status": "MARKET_NOT_FOUND",
                "event_id": entry.get("event_id"),
                "failure_reason": f"market {market!r} has no SportyBet mapping"}
    market_id, specifier, outcome_id = mapping
    base.update({"event_id": entry.get("event_id"), "market_id": market_id,
                 "outcome_id": outcome_id, "specifier": specifier or None})

    refs = entry.get("market_refs")
    if refs is None:
        # Compatibility for old persisted snapshots and compact unit-test
        # boards. A canonical price proves this exact selection was parsed.
        price = (entry.get("prices") or {}).get(market)
        if price and float(price) > 1.0:
            return {**base, "status": "BOOKABLE", "sportybet_available": True,
                    "sportybet_odds": float(price), "failure_reason": None}
        return {**base, "status": "MARKET_NOT_FOUND",
                "failure_reason": "requested market is not on the SportyBet event"}

    market_ref = refs.get(f"{market_id}|{specifier}")
    if not market_ref:
        return {**base, "status": "MARKET_NOT_FOUND",
                "failure_reason": "requested market is not on the SportyBet event"}
    outcome = (market_ref.get("outcomes") or {}).get(outcome_id)
    if not outcome:
        return {**base, "status": "SELECTION_NOT_FOUND",
                "failure_reason": "requested outcome is not on the SportyBet market"}
    if not outcome.get("active", False):
        return {**base, "status": "SELECTION_NOT_FOUND",
                "failure_reason": "requested SportyBet outcome is suspended"}
    price = outcome.get("odds")
    try:
        price = float(price)
    except (TypeError, ValueError):
        price = None
    if price is None or price <= 1.0:
        return {**base, "status": "ODDS_UNAVAILABLE",
                "failure_reason": "requested SportyBet outcome has no usable odds"}
    return {**base, "status": "BOOKABLE", "sportybet_available": True,
            "sportybet_odds": round(price, 3), "failure_reason": None}


def availability_from_fixture(fixture: dict, market: str) -> dict:
    """Selection availability after a fixture was enriched once per pipeline."""
    odds = fixture.get("odds") or {}
    match = fixture.get("_sportybet_match") or {}
    mapping = MARKET_TO_SPORTYBET.get(market)
    status = match.get("status") or "SPORTYBET_DATA_ERROR"
    base = {
        "status": status, "sportybet_available": False,
        "event_id": odds.get("sportybet_event_id"),
        "market_id": mapping[0] if mapping else None,
        "outcome_id": mapping[2] if mapping else None,
        "specifier": (mapping[1] or None) if mapping else None,
        "sportybet_odds": None,
        "fixture_match_method": match.get("fixture_match_method"),
        "fixture_match_confidence": match.get("fixture_match_confidence", 0.0),
        "failure_reason": match.get("failure_reason"),
        "board_snapshot_id": (fixture.get("_sportybet_board_meta") or {}).get(
            "snapshot_id") or odds.get("sportybet_snapshot_id"),
        "league_diagnostic": match.get("league_diagnostic"),
    }
    if status != "MATCHED" or not odds.get("sportybet_event_id"):
        return base
    if not mapping:
        return {**base, "status": "MARKET_NOT_FOUND",
                "failure_reason": f"market {market!r} has no SportyBet mapping"}

    market_id, specifier, outcome_id = mapping
    refs = odds.get("sportybet_market_refs") or {}
    market_ref = refs.get(f"{market_id}|{specifier}")
    if not market_ref:
        return {**base, "status": "MARKET_NOT_FOUND",
                "failure_reason": "requested market is not on the SportyBet event"}
    outcome = (market_ref.get("outcomes") or {}).get(outcome_id)
    if not outcome:
        return {**base, "status": "SELECTION_NOT_FOUND",
                "failure_reason": "requested outcome is not on the SportyBet market"}
    if not outcome.get("active", False):
        return {**base, "status": "SELECTION_NOT_FOUND",
                "failure_reason": "requested SportyBet outcome is suspended"}
    price = outcome.get("odds")
    try:
        price = float(price)
    except (TypeError, ValueError):
        price = None
    if price is None or price <= 1.0:
        return {**base, "status": "ODDS_UNAVAILABLE",
                "failure_reason": "requested SportyBet outcome has no usable odds"}
    return {**base, "status": "BOOKABLE", "sportybet_available": True,
            "sportybet_odds": round(price, 3), "failure_reason": None}


def lookup(board: dict, home: str, away: str, commence: str = "",
           league: str = "") -> dict | None:
    """Compatibility wrapper returning only a safely matched fixture."""
    matched = match_fixture(board, home, away, commence, league)
    return matched.get("entry") if matched.get("status") == "MATCHED" else None


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
    meta = board_metadata(board)
    for fx in fixtures:
        try:
            match = match_fixture(
                board, fx["home"]["name"], fx["away"]["name"],
                fx.get("commence_time", ""), fx.get("league", ""))
        except (KeyError, TypeError):
            continue
        fx["_sportybet_match"] = {
            key: value for key, value in match.items() if key != "entry"}
        fx["_sportybet_board_meta"] = meta
        hit = match.get("entry")
        if not hit:
            continue
        odds = dict(fx.get("odds") or {})
        odds.update(hit["prices"])
        odds["margins"] = hit["margins"]
        odds["provider"] = "SportyBet"
        odds["sportybet_event_id"] = hit["event_id"]
        odds["sportybet_market_refs"] = hit.get("market_refs")
        odds["sportybet_competition"] = hit.get("competition")
        odds["sportybet_snapshot_id"] = meta.get("snapshot_id")
        fx["odds"] = odds
        matched += 1
    return matched


def board_status() -> dict:
    """What the cache holds, for the admin dashboard and health checks."""
    cached = _db_get(_CACHE_KEY) or {}
    fixtures = cached.get("fixtures") or {}
    metadata = cached.get("metadata") or {}
    board = _snapshot(fixtures, metadata)
    entries = [entry for _, entry in _board_entries(board)]
    margins = [m for f in entries for m in (f.get("margins") or {}).values()]
    out = {
        "fixtures": len(entries),
        "cache_age_hours": (round((time.time() - cached["fetched_at"]) / 3600.0, 2)
                            if cached.get("fetched_at") else None),
        "base_url": BASE_URL,
        "priced_markets": len(margins),
        **{k: metadata.get(k) for k in (
            "snapshot_id", "declared_total", "fetched_total", "page_count",
            "required_pages", "is_complete", "error")},
    }
    if margins:
        margins.sort()
        out["margin_median"] = round(margins[len(margins) // 2], 5)
        out["margin_best_decile"] = round(margins[max(0, len(margins) // 10)], 5)
    return out
