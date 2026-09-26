"""
Results checker for picks (WC + club leagues).

Smart scheduling: polls every hour but only calls APIs once
all pending picks' games have finished (~3h after last kickoff).

Scores source priority:
  1. API-Football (api-sports.io) — 100 free calls/day, no quota issues
  2. The Odds API — fallback if API-Football unavailable

Public entry points:
- check_all_pending() — scan all unresolved chain days, update statuses
- run_loop()          — background thread with smart scheduling
"""

import os
import json
import hashlib
import logging
import re
import time
import threading
import unicodedata
import requests
from leagues.competition_registry import regulation_score
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


# ── API-Football league mapping ──────────────────────────────
# Maps Odds API sport keys → API-Football league IDs
APIFOOTBALL_LEAGUES = {
    "soccer_fifa_world_cup": 1,
    "soccer_spain_segunda_division": 141,
    "soccer_chile_campeonato": 265,
    "soccer_finland_veikkausliiga": 244,
    "soccer_league_of_ireland": 357,
    "soccer_brazil_campeonato": 71,
    "soccer_norway_eliteserien": 103,
    "soccer_sweden_allsvenskan": 113,
    "soccer_conmebol_copa_libertadores": 13,
    "soccer_conmebol_copa_sudamericana": 11,
}

SCORES_SPORTS_WC = ["soccer_fifa_world_cup"]

_last_successful_check: Optional[str] = None

# Reporting age is diagnostic only. It is never grounds for a void without
# explicit verified fixture status or market push semantics.
MISSING_RESULT_GRACE = timedelta(hours=48)


# ── ESPN scores fetcher (PRIMARY — no API key needed) ────────

# Derived from the league list we actually publish picks for, so a pick can
# never be created in a league whose results we cannot then check.
def _build_espn_slug_map():
    try:
        from leagues.espn_source import ESPN_CLUB_LEAGUES
        return {f"soccer_{slug}": slug for slug in ESPN_CLUB_LEAGUES}
    except Exception:
        return {}

ESPN_LEAGUE_SLUGS = _build_espn_slug_map()
SCORES_SPORTS_CLUB = list(ESPN_LEAGUE_SLUGS.keys())


def _fetch_espn_scores(espn_slug: str, date_str: str) -> List[dict]:
    """Fetch finished scores from ESPN for one date. No API key needed."""
    try:
        resp = requests.get(
            f"https://site.api.espn.com/apis/site/v2/sports/soccer/{espn_slug}/scoreboard",
            params={"dates": date_str},
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        return resp.json().get("events", [])
    except Exception as e:
        logger.error(f"ESPN fetch error {espn_slug}/{date_str}: {e}")
        return []


def _collect_espn_scores(sport_keys: List[str], dates: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch scores from ESPN (free, no key). Returns composite-keyed dict.

    Also fetches ±1 day for each date because ESPN uses US Eastern dates,
    so a 01:00 UTC game on June 16 appears under June 15 in ESPN.
    """
    # Expand dates to include ±1 day to catch timezone-shifted listings
    expanded = set()
    for d in dates:
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            expanded.add((dt - timedelta(days=1)).strftime("%Y-%m-%d"))
            expanded.add(d)
            expanded.add((dt + timedelta(days=1)).strftime("%Y-%m-%d"))
        except Exception:
            expanded.add(d)

    finished: Dict[str, Dict[str, Any]] = {}
    fetched = set()
    for sk in sport_keys:
        espn_slug = ESPN_LEAGUE_SLUGS.get(sk)
        if not espn_slug:
            continue
        for date_str in sorted(expanded):
            cache_key = f"{espn_slug}|{date_str}"
            if cache_key in fetched:
                continue
            fetched.add(cache_key)
            espn_date = date_str.replace("-", "")
            for event in _fetch_espn_scores(espn_slug, espn_date):
                comp = (event.get("competitions") or [{}])[0]
                status = comp.get("status", {}).get("type", {}).get("name", "")
                if not comp.get("status", {}).get("type", {}).get("completed"):
                    continue
                teams = comp.get("competitors", [])
                if len(teams) < 2:
                    continue
                home_data = next((t for t in teams if t.get("homeAway") == "home"), teams[0])
                away_data = next((t for t in teams if t.get("homeAway") == "away"), teams[1])
                home = home_data.get("team", {}).get("displayName", "")
                away = away_data.get("team", {}).get("displayName", "")
                score = regulation_score(comp)
                if not score:
                    continue
                home_score, away_score = score["home_score"], score["away_score"]

                payload = {
                    "home": home,
                    "away": away,
                    "home_score": home_score,
                    "away_score": away_score,
                    "completed": True,
                    **{key: score.get(key) for key in (
                        "score_90", "score_extra_time", "penalty_score",
                        "qualified_team", "match_status",
                    )},
                }
                # Index under BOTH the ESPN date and the original requested dates
                # so matching works regardless of timezone shift
                ck = f"{_normalize_name(home)}|{_normalize_name(away)}|{date_str}"
                finished[ck] = payload
                # Also index under all requested dates for this home/away pair
                for orig_date in dates:
                    alt_ck = f"{_normalize_name(home)}|{_normalize_name(away)}|{orig_date}"
                    if alt_ck not in finished:
                        finished[alt_ck] = payload
            time.sleep(0.2)
    return finished


# ── API-Football scores fetcher (SECONDARY) ─────────────────

def _get_apifootball_key() -> str:
    # Deployment templates and the example environment use the longer name.
    # Keep the original name for installations that already configured it.
    return (os.getenv("API_FOOTBALL_KEY") or
            os.getenv("API_FOOTBALL_API_KEY") or
            os.getenv("APIFOOTBALL_API_KEY") or "")


def _fetch_apifootball_scores(league_id: int, date_from: str, date_to: str) -> List[dict]:
    """Fetch finished fixtures from API-Football."""
    api_key = _get_apifootball_key()
    if not api_key:
        return []
    try:
        resp = requests.get(
            "https://v3.football.api-sports.io/fixtures",
            params={"league": league_id, "season": 2026, "from": date_from, "to": date_to, "status": "FT"},
            headers={"x-apisports-key": api_key},
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        if data.get("errors"):
            return []
        return data.get("response", [])
    except Exception as e:
        logger.error(f"API-Football fetch error league {league_id}: {e}")
        return []


def _collect_apifootball_scores(sport_keys: List[str], date_from: str, date_to: str) -> Dict[str, Dict[str, Any]]:
    """Fetch scores from API-Football (needs API_FOOTBALL_KEY)."""
    finished: Dict[str, Dict[str, Any]] = {}
    for sk in sport_keys:
        league_id = APIFOOTBALL_LEAGUES.get(sk)
        if not league_id:
            continue
        for fx in _fetch_apifootball_scores(league_id, date_from, date_to):
            teams = fx.get("teams", {})
            goals = fx.get("goals", {})
            scores = fx.get("score", {})
            regulation = scores.get("fulltime") or goals
            fixture_info = fx.get("fixture", {})
            home = teams.get("home", {}).get("name", "")
            away = teams.get("away", {}).get("name", "")
            home_score = regulation.get("home")
            away_score = regulation.get("away")
            if home_score is None or away_score is None:
                continue
            payload = {"home": home, "away": away, "home_score": int(home_score), "away_score": int(away_score), "completed": True,
                       "provider": "api-football", "provider_event_id": fixture_info.get("id"),
                       "score_90": {"home": int(home_score), "away": int(away_score)},
                       "score_extra_time": scores.get("extratime"),
                       "penalty_score": scores.get("penalty"),
                       "match_status": (fixture_info.get("status") or {}).get("short")}
            fixture_date = (fixture_info.get("date") or "")[:10]
            ck = f"{_normalize_name(home)}|{_normalize_name(away)}|{fixture_date}"
            finished[ck] = payload
        time.sleep(0.3)
    return finished


# ── Odds API scores fetcher (FALLBACK) ──────────────────────

def _get_odds_api_key() -> str:
    return os.getenv("ODDS_API_KEY", "")


def fetch_scores(sport_key: str, days_from: int = 3) -> List[dict]:
    """Fetch finished match scores from The Odds API."""
    api_key = _get_odds_api_key()
    if not api_key:
        return []
    try:
        resp = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores",
            params={"apiKey": api_key, "daysFrom": days_from, "dateFormat": "iso"},
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning(f"Odds API scores {sport_key} → HTTP {resp.status_code}")
            return []
        return resp.json()
    except Exception as e:
        logger.error(f"Odds API scores error {sport_key}: {e}")
        return []


def _collect_oddsapi_scores(sport_keys: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fallback: fetch scores from The Odds API."""
    finished: Dict[str, Dict[str, Any]] = {}
    for sk in sport_keys:
        for fx in fetch_scores(sk, days_from=3):
            if not fx.get("completed"):
                continue
            scores = fx.get("scores") or []
            home = fx.get("home_team", "")
            away = fx.get("away_team", "")
            home_score = None
            away_score = None
            for s in scores:
                if _normalize_name(s.get("name", "")) == _normalize_name(home):
                    try:
                        home_score = int(s.get("score") or 0)
                    except Exception:
                        pass
                elif _normalize_name(s.get("name", "")) == _normalize_name(away):
                    try:
                        away_score = int(s.get("score") or 0)
                    except Exception:
                        pass
            if home_score is None or away_score is None:
                continue
            payload = {
                "home": home,
                "away": away,
                "home_score": home_score,
                "away_score": away_score,
                "completed": True,
                "provider": "odds-api", "provider_event_id": fx.get("id"),
            }
            mid = fx.get("id")
            if mid:
                finished[mid] = payload
            commence = fx.get("commence_time", "")[:10]
            ck = f"{_normalize_name(home)}|{_normalize_name(away)}|{commence}"
            finished[ck] = payload
        time.sleep(0.2)
    return finished


# ── Unified scores collector ─────────────────────────────────


def _collect_espn_scores_ranged(
    start_date: str, end_date: str, league_slugs: set[str] | None = None,
) -> Dict[str, Dict[str, Any]]:
    """Finished scores across every tracked league for a date range.

    ESPN's scoreboard accepts dates=YYYYMM for complete monthly boards. The
    fixture source already uses this contract; the old results-only date range
    silently produced no scores when ESPN rejected it. Keyed by
    "home|away|date" plus a looser "home|away" so callers can match either way.
    """
    from concurrent.futures import ThreadPoolExecutor

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=1)
        end = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    except Exception:
        return {}
    slugs = sorted(league_slugs if league_slugs is not None
                   else set(ESPN_LEAGUE_SLUGS.values()))
    month = start.date().replace(day=1)
    months = []
    while month <= end.date():
        months.append(month.strftime("%Y%m"))
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)

    def fetch(request: tuple[str, str]) -> tuple[list[dict], str | None]:
        slug, month_key = request
        try:
            resp = requests.get(
                f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard",
                params={"dates": month_key, "limit": 500}, timeout=25,
            )
            if resp.status_code != 200:
                return [], f"HTTP_{resp.status_code}"
            payload = resp.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
                return [], "INVALID_RESPONSE"
            return payload["events"], None
        except requests.Timeout:
            return [], "TIMEOUT"
        except Exception:
            return [], "FETCH_ERROR"

    finished: Dict[str, Dict[str, Any]] = {}
    failures: Dict[str, int] = {}
    requests_made = [(slug, month_key) for slug in slugs for month_key in months]
    with ThreadPoolExecutor(max_workers=16) as pool:
        for (slug, _), (events, error) in zip(requests_made, pool.map(fetch, requests_made)):
            if error:
                failures[error] = failures.get(error, 0) + 1
                continue
            for event in events:
                comp = (event.get("competitions") or [{}])[0]
                if not comp.get("status", {}).get("type", {}).get("completed"):
                    continue
                teams = comp.get("competitors", [])
                if len(teams) < 2:
                    continue
                hd = next((t for t in teams if t.get("homeAway") == "home"), teams[0])
                ad = next((t for t in teams if t.get("homeAway") == "away"), teams[1])
                home = hd.get("team", {}).get("displayName", "")
                away = ad.get("team", {}).get("displayName", "")
                score = regulation_score(comp)
                if not score:
                    continue
                hs, as_ = score["home_score"], score["away_score"]
                payload = {"home": home, "away": away, "home_score": hs,
                           "away_score": as_, "completed": True,
                           "provider": "espn", "provider_event_id": event.get("id"),
                           "league_slug": slug,
                           **{key: score.get(key) for key in (
                               "score_90", "score_extra_time", "penalty_score",
                               "qualified_team", "match_status",
                           )}}
                date = (event.get("date") or "")[:10]
                dated_key = f"{_normalize_name(home)}|{_normalize_name(away)}|{date}"
                prior = finished.get(dated_key)
                if prior and prior.get("provider_event_id") != event.get("id"):
                    # Same names/date can exist in different competitions.
                    # Never silently overwrite one final with another.
                    finished[dated_key] = {"ambiguous": True}
                elif not prior:
                    finished[dated_key] = payload
                pair_key = f"{_normalize_name(home)}|{_normalize_name(away)}"
                pair_prior = finished.get(pair_key)
                if pair_prior and pair_prior.get("provider_event_id") != event.get("id"):
                    finished[pair_key] = {"ambiguous": True}
                elif not pair_prior:
                    finished[pair_key] = payload
    logger.info("ESPN result collection requests=%s failed=%s final_scores=%s failure_categories=%s",
                len(requests_made), sum(failures.values()), len(finished), failures)
    return finished


def _known_score_slugs(picks: list[dict]) -> set[str] | None:
    """Limit requests to published leagues only when every slug is known."""
    known = set(ESPN_LEAGUE_SLUGS.values())
    slugs = {str(pick.get("league_slug") or "") for pick in picks}
    return slugs if slugs and slugs <= known else None



def _collect_scores_for_picks(picks: list[dict]) -> tuple[Dict[str, Dict[str, Any]], str]:
    """Merge verified finals from supported sources without losing partial ESPN coverage.

    Fallback calls are limited to the unresolved picks' explicitly mapped
    sports. A current ESPN slug is not presumed to be an Odds API sport key.
    """
    dates = sorted({str(p.get("commence_time") or p.get("kickoff") or
                        p.get("date") or "")[:10] for p in picks})
    dates = [date for date in dates if date]
    if not dates:
        return {}, "none"

    finished = _collect_espn_scores_ranged(
        dates[0], dates[-1], _known_score_slugs(picks))
    sources = ["espn"] if finished else []

    def missing() -> list[dict]:
        return [p for p in picks if not _lookup_score(
            finished, p.get("home_team", ""), p.get("away_team", ""),
            str(p.get("commence_time") or p.get("kickoff") or
                p.get("date") or "")[:10])]

    def sport_keys(rows: list[dict], supported: set[str] | None = None,
                   infer_espn_slug: bool = False) -> list[str]:
        keys = {str(p.get("sport_key") or p.get("odds_api_sport_key") or
                    ("soccer_" + str(p.get("league_slug") or "")
                     if infer_espn_slug else "")) for p in rows}
        keys.discard("")
        keys.discard("soccer_")
        return sorted(key for key in keys if supported is None or key in supported)

    def merge(other: dict, source: str) -> None:
        if not other:
            return
        sources.append(source)
        for key, payload in other.items():
            prior = finished.get(key)
            if (prior and not prior.get("ambiguous") and
                    (prior.get("home_score"), prior.get("away_score")) !=
                    (payload.get("home_score"), payload.get("away_score"))):
                finished[key] = {"ambiguous": True}
            elif not prior:
                finished[key] = payload

    unresolved = missing()
    api_keys = sport_keys(unresolved, set(APIFOOTBALL_LEAGUES), True)
    if unresolved and api_keys and _get_apifootball_key():
        merge(_collect_apifootball_scores(api_keys, dates[0], dates[-1]),
              "api-football")

    unresolved = missing()
    odds_keys = sport_keys(unresolved)
    if unresolved and odds_keys and _get_odds_api_key():
        merge(_collect_oddsapi_scores(odds_keys), "odds-api")

    logger.info("Score collection picks=%s resolved=%s sources=%s fallback_leagues=%s",
                len(picks), len(picks) - len(missing()), ",".join(sources) or "none",
                len(api_keys))
    return finished, "+".join(sources) or "none"


def _collect_finished_scores(checkable_rows, has_club_picks: bool = True) -> tuple[Dict[str, Dict[str, Any]], str]:
    """Collect finals for pending rollover picks using the shared source path."""
    picks = []
    for row in checkable_rows:
        try:
            picks.extend(json.loads(row.picks or "[]"))
        except Exception:
            continue
    return _collect_scores_for_picks(picks)


# ── Pick evaluation ──────────────────────────────────────────

def _evaluate_pick(pick: dict, home_score: int, away_score: int) -> str:
    """Grade a market against a verified 90-minute score, or leave it pending."""
    # Persisted rollover legs store the diversity group in ``market`` and the
    # actual selection in ``market_key``.  Always prefer the precise key: a
    # group such as ``goals`` is not enough to distinguish Under 4.5 from
    # Over 1.5, and historically those newer lines were silently voided.
    market = pick.get("market_key") or pick.get("market", "match_result")
    market_group = pick.get("market_group") or market
    prediction = (pick.get("prediction") or "").lower()
    total = home_score + away_score
    diff = home_score - away_score

    home = (pick.get("home_team") or "").lower()
    away = (pick.get("away_team") or "").lower()

    if market in ("home_win", "away_win", "draw"):
        if market == "home_win":
            return "won" if diff > 0 else "lost"
        if market == "away_win":
            return "won" if diff < 0 else "lost"
        return "won" if diff == 0 else "lost"

    if market_group == "match_result":
        if "draw" in prediction and "or" not in prediction:
            return "won" if diff == 0 else "lost"
        if home and home in prediction:
            return "won" if diff > 0 else "lost"
        if away and away in prediction:
            return "won" if diff < 0 else "lost"
        return "pending"

    if market in ("home_or_draw", "away_or_draw", "home_or_away"):
        if market == "home_or_draw":
            return "won" if diff >= 0 else "lost"
        if market == "away_or_draw":
            return "won" if diff <= 0 else "lost"
        return "won" if diff != 0 else "lost"

    if market_group == "double_chance":
        if "or draw" in prediction:
            if home and home in prediction:
                return "won" if diff >= 0 else "lost"
            if away and away in prediction:
                return "won" if diff <= 0 else "lost"
        return "pending"

    if market in ("dnb_home", "dnb_away"):
        if diff == 0:
            return "void"
        won = diff > 0 if market == "dnb_home" else diff < 0
        return "won" if won else "lost"

    # Match totals. Half-goal lines cannot push, so integer comparison is
    # exact and covers every line the predictor can publish.
    if market.startswith(("over_", "under_")):
        try:
            line = float(market.rsplit("_", 2)[-2] + "." + market.rsplit("_", 1)[-1])
        except (ValueError, IndexError):
            return "pending"
        won = total > line if market.startswith("over_") else total < line
        return "won" if won else "lost"

    # Per-team totals use the same key suffix, but settle against the named
    # team's score rather than the match total.
    if market.startswith(("home_over_", "away_over_",
                          "home_under_", "away_under_")):
        parts = market.split("_")
        try:
            line = float(parts[-2] + "." + parts[-1])
        except (ValueError, IndexError):
            return "pending"
        scored = home_score if market.startswith("home_") else away_score
        won = scored > line if "_over_" in market else scored < line
        return "won" if won else "lost"

    # Backwards-compatible text grading for old rows that only stored a group.
    if market_group == "goals":
        import re
        hit = re.search(r"\b(over|under)\s+(\d+(?:\.\d+)?)", prediction)
        if not hit:
            return "pending"
        direction, line_text = hit.groups()
        line = float(line_text)
        won = total > line if direction == "over" else total < line
        return "won" if won else "lost"

    if market in ("btts_yes", "btts_no"):
        yes = home_score > 0 and away_score > 0
        return "won" if yes == (market == "btts_yes") else "lost"

    if market_group == "btts":
        # Check the negative first: "Both Teams to Score - No" also contains
        # "both teams to score", so testing the positive first settles every
        # BTTS-No pick as though it were BTTS-Yes.
        if "no" in prediction.replace("not ", "no "):
            return "won" if (home_score == 0 or away_score == 0) else "lost"
        if "yes" in prediction or "both teams to score" in prediction:
            return "won" if (home_score >= 1 and away_score >= 1) else "lost"
        return "pending"

    return "pending"


def _settlement_detail(pick: dict, match: dict | None,
                       now: datetime | None = None) -> tuple[str, dict]:
    """One auditable leg decision from the same evaluator used by all products."""
    current = now or datetime.now(timezone.utc)
    if not match:
        kickoff_text = (pick.get("commence_time") or pick.get("kickoff") or
                        pick.get("date") or "")
        try:
            kickoff = datetime.fromisoformat(str(kickoff_text).replace("Z", "+00:00"))
            if kickoff.tzinfo is None:
                kickoff = kickoff.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            kickoff = None
        reason = ("RESULT_NOT_FINAL" if kickoff and
                  current < kickoff + timedelta(hours=3)
                  else "FINAL_SCORE_UNVERIFIED")
        return "pending", {"settlement_pending_reason": reason}
    if match.get("ambiguous"):
        return "pending", {"settlement_pending_reason": "AMBIGUOUS_FIXTURE"}
    outcome = _evaluate_pick(pick, match["home_score"], match["away_score"])
    if outcome == "pending":
        return outcome, {"settlement_pending_reason": "UNSUPPORTED_MARKET"}
    return outcome, {"settlement_evidence": {
        "provider": match.get("provider"),
        "provider_event_id": match.get("provider_event_id"),
        "home_score": match["home_score"],
        "away_score": match["away_score"],
        "score_90": match.get("score_90"),
        "match_status": match.get("match_status"),
        "observed_at": current.isoformat(),
    }}


TEAM_ALIASES = {
    "usa": "united states",
    "united states": "usa",
    "dr congo": "congo dr",
    "congo dr": "dr congo",
    "bosnia & herzegovina": "bosnia-herzegovina",
    "bosnia-herzegovina": "bosnia & herzegovina",
    "bosnia and herzegovina": "bosnia-herzegovina",
    "türkiye": "turkey",
    "turkey": "türkiye",
    "czechia": "czech republic",
    "czech republic": "czechia",
    "korea republic": "south korea",
    "south korea": "korea republic",
    "ivory coast": "cote d'ivoire",
    "cote d'ivoire": "ivory coast",
    "cabo verde": "cape verde",
    "cape verde": "cabo verde",
}


def _normalize_name(name: str) -> str:
    if not name:
        return ""
    value = unicodedata.normalize("NFKD", str(name).casefold())
    value = value.translate(str.maketrans({"ø": "o", "ł": "l", "đ": "d", "ß": "ss"}))
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"\bf\.?c\.?\b", "fc", value)
    value = re.sub(r"\bc\.?f\.?\b", "cf", value)
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    tokens = value.split()
    # Club designators are inconsistent across score feeds. Do not remove
    # youth, women's or reserve markers: those identify different teams.
    return " ".join(token for token in tokens if token not in {"fc", "cf"})


def _lookup_score(scores: Dict[str, Dict[str, Any]], home: str, away: str,
                  date: str = "") -> Optional[Dict[str, Any]]:
    # Prefer an exact fixture date before the loose home|away fallback.
    home_key = _normalize_name(home)
    away_key = _normalize_name(away)
    aliases = {_normalize_name(key): _normalize_name(value)
               for key, value in TEAM_ALIASES.items()}
    home_alias = aliases.get(home_key, home_key)
    away_alias = aliases.get(away_key, away_key)

    # If the caller knows the fixture date, keep the lookup date-scoped.
    # Falling back to a loose home|away key can grade a rematch against the
    # wrong game when the same teams occur more than once in the score window.
    # A missing exact-date score stays pending rather than becoming a false
    # win, loss or age-based void.
    if date:
        candidates = [
            f"{home_key}|{away_key}|{date}",
            f"{home_alias}|{away_alias}|{date}",
        ]
    else:
        # Legacy callers without a date may still use the old pair key.
        candidates = [
            f"{home_key}|{away_key}",
            f"{home_alias}|{away_alias}",
        ]

    for key in candidates:
        hit = scores.get(key)
        if hit and not hit.get("ambiguous"):
            return hit
    return None


def _lookup_settlement_score(scores: Dict[str, Dict[str, Any]], home: str,
                             away: str, date: str = "") -> Optional[Dict[str, Any]]:
    """Keep ambiguous fixture evidence visible to settlement diagnostics.

    General score consumers deliberately receive no score for ambiguous
    matches. Settlement needs the marker so it can record the truthful reason
    for leaving a leg pending, without grading either candidate.
    """
    score = _lookup_score(scores, home, away, date)
    if score or not date:
        return score
    home_key = _normalize_name(home)
    away_key = _normalize_name(away)
    aliases = {_normalize_name(key): _normalize_name(value)
               for key, value in TEAM_ALIASES.items()}
    for key in (f"{home_key}|{away_key}|{date}",
                f"{aliases.get(home_key, home_key)}|"
                f"{aliases.get(away_key, away_key)}|{date}"):
        candidate = scores.get(key)
        if candidate and candidate.get("ambiguous"):
            return {"ambiguous": True}
    return None


# ── Smart scheduling helpers ─────────────────────────────────

def _get_checkable_rows(pending_rows) -> list:
    """Return only rows whose ALL picks have already kicked off (commence_time < now)."""
    now = datetime.now(timezone.utc)
    checkable = []
    for row in pending_rows:
        try:
            picks = json.loads(row.picks or "[]")
        except Exception:
            continue
        if not picks:
            continue
        all_started = True
        for pick in picks:
            ct = pick.get("commence_time", "")
            if not ct:
                continue
            try:
                dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                if dt > now:
                    all_started = False
                    break
            except Exception:
                pass
        if all_started:
            checkable.append(row)
    return checkable


def _all_games_finished(rows) -> bool:
    """Check if all picks in the given rows have had time to finish (3h after last kickoff)."""
    now = datetime.now(timezone.utc)
    latest = None
    for row in rows:
        try:
            picks = json.loads(row.picks or "[]")
        except Exception:
            continue
        for pick in picks:
            ct = pick.get("commence_time", "")
            if not ct:
                continue
            try:
                dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                if latest is None or dt > latest:
                    latest = dt
            except Exception:
                pass
    if latest is None:
        return True
    ready_at = latest + timedelta(hours=3)
    if now >= ready_at:
        return True
    wait_min = int((ready_at - now).total_seconds() / 60)
    logger.info(
        f"Results check: last started game kicked off {latest.strftime('%H:%M UTC')} — "
        f"waiting until {ready_at.strftime('%H:%M UTC')} ({wait_min}min left)"
    )
    return False


def _already_checked_today(rows) -> bool:
    """Skip if we already did a successful check after these rows' last game."""
    # No `global` needed: this only reads the module-level value. Declaring it
    # suggested an assignment that never happens.
    if not _last_successful_check:
        return False
    latest = None
    for row in rows:
        try:
            picks = json.loads(row.picks or "[]")
        except Exception:
            continue
        for pick in picks:
            ct = pick.get("commence_time", "")
            if not ct:
                continue
            try:
                dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                if latest is None or dt > latest:
                    latest = dt
            except Exception:
                pass
    if not latest:
        return False
    try:
        last_check = datetime.fromisoformat(_last_successful_check)
        return last_check > latest + timedelta(hours=3)
    except Exception:
        return False


def _missing_result_expired(pick: dict, now: datetime | None = None) -> bool:
    """Whether a scoreless fixture has had a fair result-reporting window."""
    raw = pick.get("commence_time") or ""
    if not raw:
        return False
    try:
        kickoff = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return (now or datetime.now(timezone.utc)) >= kickoff + MISSING_RESULT_GRACE


def _rollover_day_status(results: list[str]) -> str:
    """Settle an accumulator correctly when one or more legs are void."""
    if not results or any(result == "pending" for result in results):
        return "pending"
    if any(result == "lost" for result in results):
        return "lost"
    if all(result == "void" for result in results):
        return "void"
    if all(result in ("won", "void") for result in results):
        return "won"
    return "pending"


# ── Fuzzy team name matching ─────────────────────────────────

def _fuzzy_match_team(pick_name: str, score_keys: list[str]) -> Optional[str]:
    """Try to match a pick's team name against available score keys.

    API-Football and The Odds API sometimes use different team names
    (e.g. "Curacao" vs "Curaçao", "DR Congo" vs "Congo DR").
    """
    pick_lower = _normalize_name(pick_name)
    if not pick_lower:
        return None

    # Extract the significant words (skip "fc", "sc", etc.)
    skip = {"fc", "sc", "cf", "ac", "as", "us", "cd", "ud", "rcd", "rc"}
    pick_words = [w for w in pick_lower.split() if w not in skip and len(w) > 1]

    for key in score_keys:
        parts = key.split("|")
        if len(parts) < 2:
            continue
        score_home = parts[0]
        score_away = parts[1]

        for score_team in [score_home, score_away]:
            score_words = [w for w in score_team.split() if w not in skip and len(w) > 1]
            # Check if any significant word from the pick appears in the score team
            if any(pw in score_team for pw in pick_words if len(pw) >= 4):
                return key
            if any(sw in pick_lower for sw in score_words if len(sw) >= 4):
                return key
    return None


# ── Main check logic ─────────────────────────────────────────

def _sync_chain_to_db():
    """Ensure all chain days are persisted to the DB (uses cached result, no API calls)."""
    try:
        from leagues.daily_feed import build_daily_accumulators
        result = build_daily_accumulators(force=False, allow_generation=False)
        if result:
            chain = (result.get("accumulators") or {}).get("rollover", {}).get("chain", [])
            logger.info(f"Chain sync: {len(chain)} days in chain after rebuild")
        else:
            logger.info("Chain sync: no accumulators built (no predictions)")
    except Exception as e:
        logger.warning(f"Chain-to-DB sync failed: {e}")


def check_all_pending() -> Dict[str, int]:
    """Scan all pending rollover days; mark won/lost where matches finished."""
    global _last_successful_check
    summary = {"checked_chain_days": 0, "marked_won": 0, "marked_lost": 0,
               "marked_void": 0, "still_pending": 0, "api_calls": 0,
               "source": "none"}
    try:
        from leagues.rollover_db import RolloverDay
        from database import SessionLocal
    except Exception as e:
        logger.warning(f"Results check skipped — DB not available: {e}")
        return summary

    _sync_chain_to_db()

    try:
        db = SessionLocal()
        try:
            pending = db.query(RolloverDay).filter(RolloverDay.status == "pending").all()
            summary["checked_chain_days"] = len(pending)

            if not pending:
                logger.info("Results check: no pending chain days in DB")
                return summary

            checkable = _get_checkable_rows(pending)
            future_count = len(pending) - len(checkable)
            if future_count:
                logger.info(f"Results check: {len(checkable)} checkable rows, {future_count} future days skipped")

            if not checkable:
                logger.info("Results check: all pending days are future — nothing to check yet")
                summary["still_pending"] = len(pending)
                return summary

            # A late fixture on one day must not hold up already-finished
            # independent days in the chain.
            ready = [row for row in checkable if _all_games_finished([row])]
            summary["still_pending"] = len(pending) - len(ready)
            if not ready:
                return summary

            finished, source = _collect_finished_scores(ready, has_club_picks=True)
            summary["source"] = source
            summary["api_calls"] = len(finished)
            if not finished:
                logger.info("Results check: no verified final scores; legs remain pending")

            for row in ready:
                try:
                    picks = json.loads(row.picks or "[]")
                except Exception:
                    picks = []

                if not picks:
                    continue

                pick_results = []
                pick_details = []
                for pick in picks:
                    if pick.get("status") in ("won", "lost", "void"):
                        pick_results.append(pick["status"])
                        pick_details.append({})
                        continue
                    mid = pick.get("match_id")
                    home = pick.get("home_team", "")
                    away = pick.get("away_team", "")
                    ct = (pick.get("commence_time") or "")[:10]
                    match_date = ct or (getattr(row, "date", "") or "")[:10]

                    # Use the same conservative fixture matcher as published
                    # slips. A one-team fuzzy match can pick the wrong fixture
                    # on a busy date (or even reverse home/away), corrupting the
                    # public rollover record. Exact provider IDs remain valid
                    # when a score source supplies them; otherwise both teams
                    # and the fixture date must agree, including known aliases.
                    match_data = finished.get(mid) if mid else None
                    if not match_data:
                        match_data = _lookup_settlement_score(
                            finished,
                            home,
                            away,
                            match_date,
                        )

                    if not match_data or match_data.get("ambiguous"):
                        # Age is not evidence of cancellation or a void. ESPN
                        # can miss a league or be temporarily unavailable.
                        logger.info(f"Day {row.day_number}: no verified final score for {home} vs {away} (date={match_date})")
                        outcome, detail = _settlement_detail(pick, match_data)
                        pick_results.append(outcome)
                        pick_details.append(detail)
                        continue
                    r, detail = _settlement_detail(pick, match_data)
                    logger.info(f"Day {row.day_number}: {home} vs {away} → {match_data['home_score']}-{match_data['away_score']} → {r}")
                    pick_results.append(r)
                    pick_details.append(detail)

                # Record the outcome of each individual leg, not just the day.
                # Without this the chain can say a day was lost but not which
                # pick lost it, and every leg-level probability we published is
                # thrown away — leaving nothing to calibrate against.
                for pick, outcome, detail in zip(picks, pick_results, pick_details):
                    if outcome in ("won", "lost", "void"):
                        pick["status"] = outcome
                        pick.pop("settlement_pending_reason", None)
                        if detail.get("settlement_evidence") and not pick.get("settlement_evidence"):
                            pick["settlement_evidence"] = detail["settlement_evidence"]
                    elif detail.get("settlement_pending_reason"):
                        pick["settlement_pending_reason"] = detail["settlement_pending_reason"]
                row.picks = json.dumps(picks)

                day_status = _rollover_day_status(pick_results)
                if day_status == "lost":
                    row.status = day_status
                    summary["marked_lost"] += 1
                elif day_status == "won":
                    row.status = day_status
                    summary["marked_won"] += 1
                elif day_status == "void":
                    row.status = day_status
                    summary["marked_void"] += 1
                else:
                    summary["still_pending"] += 1

            db.commit()
            # The daily endpoint caches the locked card for 15 minutes. Its
            # rollover section is refreshed from these rows, so leaving the
            # cache intact makes a settled day continue to display as pending
            # until both backend and frontend caches expire.
            if summary["marked_won"] or summary["marked_lost"] or summary["marked_void"]:
                try:
                    from leagues.daily_feed import _accum_cache
                    _accum_cache.update({"result": None, "ts": 0.0})
                except Exception:
                    pass
            _last_successful_check = datetime.now(timezone.utc).isoformat()
            logger.info(f"Results check complete: {summary}")
            return summary
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Results check failed: {e}", exc_info=True)
        return summary


def run_loop():
    """Background thread: check every hour, call APIs only when games are done."""
    time.sleep(60)
    iteration = 0
    while True:
        iteration += 1
        try:
            result = check_all_pending()
            if result.get("api_calls"):
                logger.info(f"Results check used {result['source']} ({result['api_calls']} matches found)")
        except Exception as e:
            logger.error(f"Results check loop iteration failed: {e}")
        try:
            settle_published_slips()
        except Exception as e:
            logger.error(f"Slip settlement failed: {e}")
        try:
            settle_builder_predictions()
        except Exception as e:
            logger.error(f"Builder settlement failed: {e}")
        time.sleep(3600)

        if iteration % 168 == 0:
            try:
                from leagues.rollover_db import cleanup_old_chains
                cleanup_old_chains(keep_recent_chains=3)
            except Exception as e:
                logger.error(f"Rollover cleanup failed: {e}")


def start_background_loop():
    """Spawn the background results-checker thread."""
    t = threading.Thread(target=run_loop, daemon=True)
    t.start()
    logger.info("Results checker started (hourly poll, API-Football primary, Odds API fallback)")
    return t


# ── Category slip settlement ─────────────────────────────────

def settle_published_slips() -> Dict[str, int]:
    """Settle archived category slips (banker / 2 odds / 5 odds / ...).

    Only the rollover chain used to be settled, so the Results page had a
    track record for one product and nothing for the rest. This walks the
    published_slips archive, scores each leg against real results, and marks
    the slip won or lost.
    """
    from leagues.picks_db import pending_slips, settle_slip
    import json as _json

    today = datetime.utcnow().strftime("%Y-%m-%d")
    slips = pending_slips(today)
    if not slips:
        return {"slips_checked": 0, "won": 0, "lost": 0, "still_pending": 0}

    # Reuse the same source/fallback path as rollover; a partial provider
    # response must still settle every safely matched leg it contains.
    published_picks = [{**pick, "date": pick.get("date") or slip.date}
                       for slip in slips
                       for pick in _json.loads(slip.picks or "[]")]
    scores, _ = _collect_scores_for_picks(published_picks)

    won = lost = still = 0
    for slip in slips:
        picks = _json.loads(slip.picks or "[]")
        outcomes: List[str] = []
        details: list[dict] = []
        for pick in picks:
            if pick.get("status") in ("won", "lost", "void"):
                outcomes.append(pick["status"])
                details.append({})
                continue
            match_date = (pick.get("commence_time") or slip.date or "")[:10]
            match = _lookup_settlement_score(
                scores,
                pick.get("home_team", ""),
                pick.get("away_team", ""),
                match_date,
            )
            outcome, detail = _settlement_detail(pick, match)
            outcomes.append(outcome)
            details.append(detail)

        status = settle_slip(slip.id, outcomes, details)
        if status == "won":
            won += 1
        elif status == "lost":
            lost += 1
        else:
            still += 1

    if won or lost:
        logger.info(f"Slip settlement: {won} won, {lost} lost, {still} pending")
    return {"slips_checked": len(slips), "won": won, "lost": lost, "still_pending": still}


def _proposed_published_slip_status(picks: list[dict], outcomes: list[str],
                                    presentation: str) -> str:
    """Mirror the published-slip status policy without touching an ORM row.

    Reconciliation must be able to compare an old archived verdict with the
    verdict the current canonical evaluator would produce.  Keeping this
    calculation side-effect free is intentional: this report is not a hidden
    backfill path.
    """
    if (presentation or "accumulator") == "singles":
        if not outcomes or any(outcome == "pending" for outcome in outcomes):
            return "pending"
        staked = sum(1 for outcome in outcomes if outcome in ("won", "lost"))
        returned = sum(
            float(pick.get("odds") or 0)
            for pick, outcome in zip(picks, outcomes) if outcome == "won"
        )
        return "won" if returned > staked else "lost"
    if any(outcome == "lost" for outcome in outcomes):
        return "lost"
    if outcomes and all(outcome == "void" for outcome in outcomes):
        return "void"
    if outcomes and all(outcome in ("won", "void") for outcome in outcomes):
        return "won"
    return "pending"


def reconcile_published_slips(*, start_date: str = "2026-09-15",
                              end_date: str = "2026-09-24",
                              dry_run: bool = True) -> dict:
    """Read-only, bounded comparison of archived slips against final scores.

    This is deliberately separate from normal settlement.  It reads every
    archived slip in the requested range, including already decided slips,
    then re-evaluates copied leg dictionaries through ``_settlement_detail``.
    It neither assigns ORM attributes nor commits a transaction.  Callers may
    use the report to review apparent historical false voids or losses before
    any separately authorised repair is considered.
    """
    if not dry_run:
        raise ValueError("published-slip reconciliation is strictly read-only; dry_run must be true")
    try:
        start = datetime.fromisoformat(start_date).date()
        end = datetime.fromisoformat(end_date).date()
    except (TypeError, ValueError) as exc:
        raise ValueError("start_date and end_date must be ISO dates") from exc
    today = datetime.now(timezone.utc).date()
    if start > end or end > today or (end - start).days > 31:
        raise ValueError("reconciliation window must be ordered, past-or-present, and at most 32 days")

    from database import SessionLocal
    from leagues.picks_db import PublishedSlip

    report = {
        "dry_run": True,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "slips_scanned": 0,
        "legs_scanned": 0,
        "score_source": "none",
        "slips": [],
        "likely_historical_false_voids": [],
        "likely_incorrect_losses": [],
        "unresolved_legs": [],
    }
    db = SessionLocal()
    try:
        rows = (
            db.query(PublishedSlip)
            .filter(PublishedSlip.date >= start.isoformat())
            .filter(PublishedSlip.date <= end.isoformat())
            .order_by(PublishedSlip.date.asc(), PublishedSlip.id.asc())
            .all()
        )
        # Detach the data from the ORM before evaluation.  In particular, do
        # not let score evidence or a proposed leg outcome mutate the archive.
        archived = []
        for row in rows:
            try:
                picks = json.loads(row.picks or "[]")
            except (TypeError, ValueError):
                picks = []
            archived.append({
                "id": row.id, "date": row.date, "category": row.category,
                "status": row.status or "pending",
                "presentation": row.presentation or "accumulator",
                "stored_picks_hash": hashlib.sha256(
                    (row.picks or "").encode()
                ).hexdigest(),
                "picks": picks if isinstance(picks, list) else [],
            })
    finally:
        db.close()

    score_picks = [
        {**pick, "date": pick.get("date") or row["date"]}
        for row in archived for pick in row["picks"]
    ]
    scores, source = _collect_scores_for_picks(score_picks)
    report["score_source"] = source
    current = datetime.now(timezone.utc)

    for row in archived:
        leg_reports = []
        outcomes = []
        for index, original_pick in enumerate(row["picks"]):
            # Nested mutable evidence is copied too, even though the evaluator
            # currently only reads the pick.  This keeps the read-only
            # contract obvious if its implementation grows later.
            pick = json.loads(json.dumps(original_pick))
            match_date = (pick.get("commence_time") or pick.get("date") or
                          row["date"] or "")[:10]
            match = _lookup_settlement_score(
                scores, pick.get("home_team", ""), pick.get("away_team", ""),
                match_date,
            )
            proposed, detail = _settlement_detail(pick, match, current)
            stored = pick.get("status") or "pending"
            evidence = detail.get("settlement_evidence")
            unresolved_reason = detail.get("settlement_pending_reason")
            leg = {
                "index": index,
                "fixture": {
                    "home_team": pick.get("home_team"),
                    "away_team": pick.get("away_team"),
                    "date": match_date,
                },
                "market": pick.get("market") or pick.get("market_key"),
                "prediction": pick.get("prediction"),
                "stored_outcome": stored,
                "proposed_outcome": proposed,
                "stored_evidence": pick.get("settlement_evidence"),
                "stored_pending_reason": pick.get("settlement_pending_reason"),
                "score_evidence": evidence,
                "unresolved_reason": unresolved_reason,
            }
            leg_reports.append(leg)
            outcomes.append(proposed)
            report["legs_scanned"] += 1
            if proposed == "pending":
                report["unresolved_legs"].append({
                    "slip_id": row["id"], "category": row["category"], **leg,
                })
            if stored == "void" and proposed in ("won", "lost"):
                report["likely_historical_false_voids"].append({
                    "slip_id": row["id"], "category": row["category"], **leg,
                })
            if stored == "lost" and proposed in ("won", "void"):
                report["likely_incorrect_losses"].append({
                    "slip_id": row["id"], "category": row["category"], **leg,
                })

        proposed_status = _proposed_published_slip_status(
            row["picks"], outcomes, row["presentation"])
        slip_report = {
            "slip_id": row["id"], "date": row["date"],
            "category": row["category"], "stored_status": row["status"],
            "proposed_status": proposed_status, "presentation": row["presentation"],
            "stored_picks_hash": row["stored_picks_hash"],
            "legs": leg_reports,
        }
        report["slips"].append(slip_report)
        report["slips_scanned"] += 1
        if row["status"] == "void" and proposed_status in ("won", "lost"):
            report["likely_historical_false_voids"].append({
                "slip_id": row["id"], "category": row["category"],
                "level": "slip", "stored_status": row["status"],
                "proposed_status": proposed_status,
            })
        if row["status"] == "lost" and proposed_status in ("won", "void"):
            report["likely_incorrect_losses"].append({
                "slip_id": row["id"], "category": row["category"],
                "level": "slip", "stored_status": row["status"],
                "proposed_status": proposed_status,
            })
    logger.info("Published-slip reconciliation read %s slips / %s legs (%s to %s)",
                report["slips_scanned"], report["legs_scanned"],
                report["start_date"], report["end_date"])
    return report


def settle_builder_predictions(scores: dict | None = None,
                               now: datetime | None = None) -> Dict[str, int]:
    """Settle unique Builder prediction sets with the canonical evaluator."""
    from leagues.builder_runs import pending_predictions, settle_prediction

    current = now or datetime.now(timezone.utc)
    rows = pending_predictions()
    summary = {"builds_checked": len(rows), "won": 0, "lost": 0,
               "void": 0, "still_pending": 0}
    if not rows:
        return summary

    if scores is None:
        all_picks = [pick for row in rows
                     for pick in json.loads(row.get("picks") or "[]")]
        due_picks = [pick for pick in all_picks if
                     str(pick.get("kickoff") or pick.get("date") or "")[:10]
                     <= current.strftime("%Y-%m-%d")]
        scores, _ = _collect_scores_for_picks(due_picks)

    for row in rows:
        picks = json.loads(row.get("picks") or "[]")
        outcomes = []
        details = []
        for pick in picks:
            if pick.get("status") in ("won", "lost", "void"):
                outcomes.append(pick["status"])
                details.append({})
                continue
            match_date = str(pick.get("kickoff") or pick.get("date") or "")[:10]
            match = _lookup_settlement_score(
                scores,
                pick.get("home_team", ""),
                pick.get("away_team", ""),
                match_date,
            )
            outcome, detail = _settlement_detail(pick, match, current)
            outcomes.append(outcome)
            details.append(detail)
        status = settle_prediction(row["selection_fingerprint"], outcomes, details)
        key = status if status in ("won", "lost", "void") else "still_pending"
        summary[key] += 1
    return summary

def backfill_leg_status(limit_days: int = 30, *, dry_run: bool = True,
                        start_date: str | None = None,
                        end_date: str | None = None) -> Dict[str, int]:
    """Fill in per-leg outcomes on chain days that were settled before we
    started recording them.

    Day-level status is left untouched — those results are already final and
    published. This only recovers the leg detail, which is what calibration
    and "which pick actually lost it" both need.
    """
    from leagues.rollover_db import RolloverDay
    from database import SessionLocal

    if not 1 <= limit_days <= 120:
        raise ValueError("limit_days must be between 1 and 120")
    today = datetime.now(timezone.utc).date()
    end = datetime.fromisoformat(end_date).date() if end_date else today
    start = (datetime.fromisoformat(start_date).date() if start_date else
             end - timedelta(days=limit_days - 1))
    if end > today or start > end or (end - start).days >= limit_days:
        raise ValueError("backfill window must be bounded and not in the future")
    out = {"days_scanned": 0, "days_updated": 0, "legs_filled": 0,
           "still_pending": 0, "ambiguous": 0, "unsupported": 0,
           "dry_run": dry_run, "start_date": start.isoformat(),
           "end_date": end.isoformat()}
    try:
        db = SessionLocal()
        try:
            rows = (
                db.query(RolloverDay)
                .filter(RolloverDay.status.in_(("won", "lost")))
                .filter(RolloverDay.date >= start.isoformat())
                .filter(RolloverDay.date <= end.isoformat())
                .all()
            )
            todo = []
            for row in rows:
                try:
                    picks = json.loads(row.picks or "[]")
                except Exception:
                    continue
                if picks and any(p.get("status") not in ("won", "lost", "void") for p in picks):
                    todo.append((row, picks))

            out["days_scanned"] = len(todo)
            if not todo:
                return out

            # One ranged request per league, run in parallel. The per-date
            # collector used elsewhere would issue 91 leagues x ~30 dates with
            # a sleep between each — thousands of calls that never finish
            # inside a request timeout.
            unresolved = [dict(pick, date=(pick.get("commence_time") or row.date))
                          for row, picks in todo for pick in picks
                          if pick.get("status") not in ("won", "lost", "void")]
            scores, _ = _collect_scores_for_picks(unresolved)

            for row, picks in todo:
                changed = False
                for pick in picks:
                    if pick.get("status") in ("won", "lost", "void"):
                        continue
                    match = _lookup_settlement_score(
                        scores,
                        pick.get("home_team", ""),
                        pick.get("away_team", ""),
                        (pick.get("commence_time") or row.date or "")[:10],
                    )
                    outcome, detail = _settlement_detail(pick, match)
                    if outcome == "pending":
                        reason = detail.get("settlement_pending_reason")
                        out["still_pending"] += 1
                        if reason == "AMBIGUOUS_FIXTURE":
                            out["ambiguous"] += 1
                        elif reason == "UNSUPPORTED_MARKET":
                            out["unsupported"] += 1
                        continue
                    pick["status"] = outcome
                    pick.update(detail)
                    out["legs_filled"] += 1
                    changed = True
                if changed:
                    if not dry_run:
                        row.picks = json.dumps(picks)
                    out["days_updated"] += 1

            if not dry_run:
                db.commit()
            logger.info(f"Leg backfill: {out}")
            return out
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Leg backfill failed: {e}")
        return out
