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
SCORES_SPORTS_CLUB = [
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

_last_successful_check: Optional[str] = None


# ── API-Football scores fetcher (PRIMARY) ────────────────────

def _get_apifootball_key() -> str:
    return os.getenv("API_FOOTBALL_KEY", "")


def _fetch_apifootball_scores(league_id: int, date_from: str, date_to: str) -> List[dict]:
    """Fetch finished fixtures from API-Football. Returns normalized list."""
    api_key = _get_apifootball_key()
    if not api_key:
        return []
    try:
        resp = requests.get(
            "https://v3.football.api-sports.io/fixtures",
            params={
                "league": league_id,
                "season": 2026,
                "from": date_from,
                "to": date_to,
                "status": "FT",
            },
            headers={"x-apisports-key": api_key},
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning(f"API-Football league {league_id} → HTTP {resp.status_code}")
            return []
        data = resp.json()
        errors = data.get("errors")
        if errors:
            logger.warning(f"API-Football league {league_id} errors: {errors}")
            return []
        return data.get("response", [])
    except Exception as e:
        logger.error(f"API-Football fetch error league {league_id}: {e}")
        return []


def _collect_apifootball_scores(sport_keys: List[str], date_from: str, date_to: str) -> Dict[str, Dict[str, Any]]:
    """Fetch scores from API-Football for the given sport keys.

    Returns {composite_key: {home, away, home_score, away_score, completed}}.
    Composite key = "home_lower|away_lower|date".
    """
    finished: Dict[str, Dict[str, Any]] = {}
    for sk in sport_keys:
        league_id = APIFOOTBALL_LEAGUES.get(sk)
        if not league_id:
            continue
        fixtures = _fetch_apifootball_scores(league_id, date_from, date_to)
        for fx in fixtures:
            teams = fx.get("teams", {})
            goals = fx.get("goals", {})
            fixture_info = fx.get("fixture", {})

            home = teams.get("home", {}).get("name", "")
            away = teams.get("away", {}).get("name", "")
            home_score = goals.get("home")
            away_score = goals.get("away")

            if home_score is None or away_score is None:
                continue

            payload = {
                "home": home,
                "away": away,
                "home_score": int(home_score),
                "away_score": int(away_score),
                "completed": True,
            }

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

    Priority: API-Football first, Odds API fallback.
    Uses checkable_rows to determine the date range needed.
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

    date_from = min(dates)
    date_to = max(dates)

    # Try API-Football first
    if _get_apifootball_key():
        finished = _collect_apifootball_scores(sports, date_from, date_to)
        if finished:
            logger.info(f"Scores from API-Football: {len(finished)} completed matches")
            return finished, "api-football"
        logger.warning("API-Football returned no scores — trying Odds API fallback")

    # Fallback: Odds API
    if _get_odds_api_key():
        finished = _collect_oddsapi_scores(sports)
        if finished:
            logger.info(f"Scores from Odds API fallback: {len(finished)} completed matches")
            return finished, "odds-api"
        logger.warning("Odds API also returned no scores")

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
        if "yes" in prediction or "both teams to score" in prediction:
            return "won" if (home_score >= 1 and away_score >= 1) else "lost"
        if "no" in prediction:
            return "won" if (home_score == 0 or away_score == 0) else "lost"
        return "void"

    return "void"


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
        from worldcup.daily_feed import build_daily_accumulators
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
        from worldcup.rollover_db import RolloverDay
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

                    # Fuzzy match if exact fails (different team name formats)
                    if not match_data:
                        fuzzy_key = _fuzzy_match_team(home, [k for k in score_keys if ct in k])
                        if fuzzy_key:
                            match_data = finished.get(fuzzy_key)
                            if match_data:
                                logger.info(f"Day {row.day_number}: fuzzy matched '{home} vs {away}' → key '{fuzzy_key}'")

                    if not match_data:
                        logger.info(f"Day {row.day_number}: no score yet for {home} vs {away} (composite={composite})")
                        pick_results.append("pending")
                        continue
                    r = _evaluate_pick(pick, match_data["home_score"], match_data["away_score"])
                    logger.info(f"Day {row.day_number}: {home} vs {away} → {match_data['home_score']}-{match_data['away_score']} → {r}")
                    pick_results.append(r)

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
        time.sleep(3600)

        if iteration % 168 == 0:
            try:
                from worldcup.rollover_db import cleanup_old_chains
                cleanup_old_chains(keep_recent_chains=3)
            except Exception as e:
                logger.error(f"Rollover cleanup failed: {e}")


def start_background_loop():
    """Spawn the background results-checker thread."""
    t = threading.Thread(target=run_loop, daemon=True)
    t.start()
    logger.info("Results checker started (hourly poll, API-Football primary, Odds API fallback)")
    return t
