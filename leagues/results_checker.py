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
import logging
import time
import threading
import requests
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
                if status != "STATUS_FULL_TIME":
                    continue
                teams = comp.get("competitors", [])
                if len(teams) < 2:
                    continue
                home_data = next((t for t in teams if t.get("homeAway") == "home"), teams[0])
                away_data = next((t for t in teams if t.get("homeAway") == "away"), teams[1])
                home = home_data.get("team", {}).get("displayName", "")
                away = away_data.get("team", {}).get("displayName", "")
                try:
                    home_score = int(home_data.get("score", 0))
                    away_score = int(away_data.get("score", 0))
                except (ValueError, TypeError):
                    continue

                payload = {
                    "home": home,
                    "away": away,
                    "home_score": home_score,
                    "away_score": away_score,
                    "completed": True,
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
    return os.getenv("API_FOOTBALL_KEY", "")


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
            fixture_info = fx.get("fixture", {})
            home = teams.get("home", {}).get("name", "")
            away = teams.get("away", {}).get("name", "")
            home_score = goals.get("home")
            away_score = goals.get("away")
            if home_score is None or away_score is None:
                continue
            payload = {"home": home, "away": away, "home_score": int(home_score), "away_score": int(away_score), "completed": True}
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

def _collect_finished_scores(checkable_rows, has_club_picks: bool = True) -> tuple[Dict[str, Dict[str, Any]], str]:
    """Collect finished scores. Returns (finished_dict, source_name).

    Priority:
      1. ESPN (free, no key, no quota — covers WC + some club leagues)
      2. API-Football (100 free calls/day, needs API_FOOTBALL_KEY)
      3. The Odds API (500 calls/month, fallback only)
    """
    sports = SCORES_SPORTS_WC + (SCORES_SPORTS_CLUB if has_club_picks else [])

    # Determine date range from checkable rows
    dates = set()
    for row in checkable_rows:
        try:
            picks = json.loads(row.picks or "[]")
        except Exception:
            continue
        for pick in picks:
            ct = (pick.get("commence_time") or "")[:10]
            if ct:
                dates.add(ct)
    if not dates:
        return {}, "none"

    date_list = sorted(dates)
    date_from = min(dates)
    date_to = max(dates)

    # 1. ESPN — free, no key, no quota
    finished = _collect_espn_scores(sports, date_list)
    if finished:
        logger.info(f"Scores from ESPN: {len(finished)} completed matches")
        return finished, "espn"

    # 2. API-Football — needs key but generous free tier
    if _get_apifootball_key():
        finished = _collect_apifootball_scores(sports, date_from, date_to)
        if finished:
            logger.info(f"Scores from API-Football: {len(finished)} completed matches")
            return finished, "api-football"

    # 3. Odds API — last resort (burns quota)
    if _get_odds_api_key():
        finished = _collect_oddsapi_scores(sports)
        if finished:
            logger.info(f"Scores from Odds API: {len(finished)} completed matches")
            return finished, "odds-api"

    logger.warning("No scores from any source (ESPN, API-Football, Odds API)")
    return {}, "none"


# ── Pick evaluation ──────────────────────────────────────────

def _evaluate_pick(pick: dict, home_score: int, away_score: int) -> str:
    """Compare a single pick against the actual score. Returns 'won' | 'lost' | 'void'."""
    market = pick.get("market", "match_result")
    prediction = (pick.get("prediction") or "").lower()
    total = home_score + away_score
    diff = home_score - away_score

    home = (pick.get("home_team") or "").lower()
    away = (pick.get("away_team") or "").lower()

    if market == "match_result":
        if "draw" in prediction and "or" not in prediction:
            return "won" if diff == 0 else "lost"
        if home and home in prediction:
            return "won" if diff > 0 else "lost"
        if away and away in prediction:
            return "won" if diff < 0 else "lost"
        return "void"

    if market == "double_chance":
        if "or draw" in prediction:
            if home and home in prediction:
                return "won" if diff >= 0 else "lost"
            if away and away in prediction:
                return "won" if diff <= 0 else "lost"
        return "void"

    if market == "goals":
        if "over 1.5" in prediction:
            return "won" if total > 1 else "lost"
        if "over 2.5" in prediction:
            return "won" if total > 2 else "lost"
        if "under 2.5" in prediction:
            return "won" if total <= 2 else "lost"
        if "over 0.5" in prediction:
            return "won" if total >= 1 else "lost"
        return "void"

    if market == "btts":
        # Check the negative first: "Both Teams to Score - No" also contains
        # "both teams to score", so testing the positive first settles every
        # BTTS-No pick as though it were BTTS-Yes.
        if "no" in prediction.replace("not ", "no "):
            return "won" if (home_score == 0 or away_score == 0) else "lost"
        if "yes" in prediction or "both teams to score" in prediction:
            return "won" if (home_score >= 1 and away_score >= 1) else "lost"
        return "void"

    return "void"


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
    return name.lower().strip()


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
    global _last_successful_check
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
        result = build_daily_accumulators(force=False)
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
    summary = {"checked_chain_days": 0, "marked_won": 0, "marked_lost": 0, "still_pending": 0, "api_calls": 0, "source": "none"}
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

            if not _all_games_finished(checkable):
                summary["still_pending"] = len(pending)
                return summary

            if _already_checked_today(checkable):
                logger.info("Results check: already checked after today's last game — skipping")
                summary["still_pending"] = len(pending)
                return summary

            finished, source = _collect_finished_scores(checkable, has_club_picks=True)
            summary["source"] = source
            summary["api_calls"] = len(finished)
            if not finished:
                logger.info("Results check: no finished matches from any source")
                return summary

            score_keys = list(finished.keys())

            for row in checkable:
                try:
                    picks = json.loads(row.picks or "[]")
                except Exception:
                    picks = []

                if not picks:
                    continue

                pick_results = []
                for pick in picks:
                    mid = pick.get("match_id")
                    home = pick.get("home_team", "")
                    away = pick.get("away_team", "")
                    ct = (pick.get("commence_time") or "")[:10]
                    composite = f"{_normalize_name(home)}|{_normalize_name(away)}|{ct}"

                    # Try exact match first
                    match_data = finished.get(mid) or finished.get(composite)

                    # Try with aliased team names (ESPN vs Odds API naming)
                    if not match_data:
                        home_alias = TEAM_ALIASES.get(_normalize_name(home), "")
                        away_alias = TEAM_ALIASES.get(_normalize_name(away), "")
                        for h in [_normalize_name(home), home_alias]:
                            for a in [_normalize_name(away), away_alias]:
                                if not h or not a:
                                    continue
                                alias_key = f"{h}|{a}|{ct}"
                                match_data = finished.get(alias_key)
                                if match_data:
                                    logger.info(f"Day {row.day_number}: alias matched '{home} vs {away}' → '{alias_key}'")
                                    break
                            if match_data:
                                break

                    # Fuzzy word-match if alias also fails
                    if not match_data:
                        fuzzy_key = _fuzzy_match_team(home, [k for k in score_keys if ct in k])
                        if fuzzy_key:
                            match_data = finished.get(fuzzy_key)
                            if match_data:
                                logger.info(f"Day {row.day_number}: fuzzy matched '{home} vs {away}' → '{fuzzy_key}'")

                    if not match_data:
                        logger.info(f"Day {row.day_number}: no score yet for {home} vs {away} (composite={composite})")
                        pick_results.append("pending")
                        continue
                    r = _evaluate_pick(pick, match_data["home_score"], match_data["away_score"])
                    logger.info(f"Day {row.day_number}: {home} vs {away} → {match_data['home_score']}-{match_data['away_score']} → {r}")
                    pick_results.append(r)

                # Record the outcome of each individual leg, not just the day.
                # Without this the chain can say a day was lost but not which
                # pick lost it, and every leg-level probability we published is
                # thrown away — leaving nothing to calibrate against.
                for pick, outcome in zip(picks, pick_results):
                    if outcome in ("won", "lost", "void"):
                        pick["status"] = outcome
                row.picks = json.dumps(picks)

                if any(r == "lost" for r in pick_results):
                    row.status = "lost"
                    summary["marked_lost"] += 1
                elif all(r == "won" for r in pick_results):
                    row.status = "won"
                    summary["marked_won"] += 1
                else:
                    summary["still_pending"] += 1

            db.commit()
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

    # Score every league we tip, across the dates in question
    dates = sorted({s.date for s in slips})
    scores = _collect_espn_scores(SCORES_SPORTS_CLUB, dates)

    def _lookup(home: str, away: str) -> Optional[Dict[str, Any]]:
        h, a = _normalize_name(home), _normalize_name(away)
        for key, val in scores.items():
            if _normalize_name(val.get("home", "")) == h and _normalize_name(val.get("away", "")) == a:
                return val
        # Fall back to alias forms for teams whose feeds disagree on naming
        h2 = TEAM_ALIASES.get(h, h)
        a2 = TEAM_ALIASES.get(a, a)
        for key, val in scores.items():
            if _normalize_name(val.get("home", "")) == h2 and _normalize_name(val.get("away", "")) == a2:
                return val
        return None

    won = lost = still = 0
    for slip in slips:
        picks = _json.loads(slip.picks or "[]")
        outcomes: List[str] = []
        for pick in picks:
            if pick.get("status") in ("won", "lost", "void"):
                outcomes.append(pick["status"])
                continue
            match = _lookup(pick.get("home_team", ""), pick.get("away_team", ""))
            if not match:
                outcomes.append("pending")
                continue
            outcomes.append(
                _evaluate_pick(
                    {**pick, "market": pick.get("market_group", pick.get("market", "match_result"))},
                    match["home_score"], match["away_score"],
                )
            )

        # A slip more than three days old that still cannot be scored is
        # voided rather than left pending forever.
        if "pending" in outcomes:
            age_days = (datetime.utcnow() - datetime.strptime(slip.date, "%Y-%m-%d")).days
            if age_days > 3:
                outcomes = ["void" if o == "pending" else o for o in outcomes]

        status = settle_slip(slip.id, outcomes)
        if status == "won":
            won += 1
        elif status == "lost":
            lost += 1
        else:
            still += 1

    if won or lost:
        logger.info(f"Slip settlement: {won} won, {lost} lost, {still} pending")
    return {"slips_checked": len(slips), "won": won, "lost": lost, "still_pending": still}


def _collect_espn_scores_ranged(start_date: str, end_date: str) -> Dict[str, Dict[str, Any]]:
    """Finished scores across every tracked league for a date range.

    ESPN accepts dates=YYYYMMDD-YYYYMMDD, so each league costs one request
    instead of one per day, and the leagues run concurrently. Keyed by
    "home|away|date" plus a looser "home|away" so callers can match either way.
    """
    from concurrent.futures import ThreadPoolExecutor

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=1)
        end = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    except Exception:
        return {}
    rng = f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"

    slugs = list(ESPN_LEAGUE_SLUGS.values()) + ["fifa.world"]

    def fetch(slug: str) -> List[dict]:
        try:
            resp = requests.get(
                f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard",
                params={"dates": rng, "limit": 500}, timeout=25,
            )
            if resp.status_code != 200:
                return []
            return resp.json().get("events", [])
        except Exception:
            return []

    finished: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=16) as pool:
        for events in pool.map(fetch, slugs):
            for event in events:
                comp = (event.get("competitions") or [{}])[0]
                if comp.get("status", {}).get("type", {}).get("name") != "STATUS_FULL_TIME":
                    continue
                teams = comp.get("competitors", [])
                if len(teams) < 2:
                    continue
                hd = next((t for t in teams if t.get("homeAway") == "home"), teams[0])
                ad = next((t for t in teams if t.get("homeAway") == "away"), teams[1])
                home = hd.get("team", {}).get("displayName", "")
                away = ad.get("team", {}).get("displayName", "")
                try:
                    hs, as_ = int(hd.get("score", 0)), int(ad.get("score", 0))
                except (TypeError, ValueError):
                    continue
                payload = {"home": home, "away": away, "home_score": hs,
                           "away_score": as_, "completed": True}
                date = (event.get("date") or "")[:10]
                finished[f"{_normalize_name(home)}|{_normalize_name(away)}|{date}"] = payload
                finished.setdefault(f"{_normalize_name(home)}|{_normalize_name(away)}", payload)
    return finished


def backfill_leg_status(limit_days: int = 120) -> Dict[str, int]:
    """Fill in per-leg outcomes on chain days that were settled before we
    started recording them.

    Day-level status is left untouched — those results are already final and
    published. This only recovers the leg detail, which is what calibration
    and "which pick actually lost it" both need.
    """
    from leagues.rollover_db import RolloverDay
    from database import SessionLocal

    out = {"days_scanned": 0, "days_updated": 0, "legs_filled": 0}
    try:
        db = SessionLocal()
        try:
            rows = (
                db.query(RolloverDay)
                .filter(RolloverDay.status.in_(("won", "lost")))
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
            dates = sorted({r.date for r, _ in todo})
            scores = _collect_espn_scores_ranged(dates[0], dates[-1])

            def _find(home: str, away: str, date: str):
                h, a = _normalize_name(home), _normalize_name(away)
                return scores.get(f"{h}|{a}|{date}") or scores.get(f"{h}|{a}")

            for row, picks in todo:
                changed = False
                for pick in picks:
                    if pick.get("status") in ("won", "lost", "void"):
                        continue
                    match = _find(pick.get("home_team", ""), pick.get("away_team", ""),
                                  (pick.get("commence_time") or "")[:10])
                    if not match:
                        continue
                    pick["status"] = _evaluate_pick(pick, match["home_score"], match["away_score"])
                    out["legs_filled"] += 1
                    changed = True
                if changed:
                    row.picks = json.dumps(picks)
                    out["days_updated"] += 1

            db.commit()
            logger.info(f"Leg backfill: {out}")
            return out
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Leg backfill failed: {e}")
        return out
