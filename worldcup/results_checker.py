"""
Results checker for picks (WC + club leagues).

Smart scheduling: polls every hour but only calls the Odds API once
all pending picks' games have finished (~3h after last kickoff).
This keeps API usage to ~10 calls/day instead of ~60.

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


def _get_api_key() -> str:
    return os.getenv("ODDS_API_KEY", "")

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


def fetch_scores(sport_key: str, days_from: int = 5) -> List[dict]:
    """Fetch finished match scores from The Odds API."""
    api_key = _get_api_key()
    if not api_key:
        logger.warning("ODDS_API_KEY not set — skipping scores fetch")
        return []
    try:
        resp = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores",
            params={"apiKey": api_key, "daysFrom": days_from, "dateFormat": "iso"},
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning(f"Scores fetch {sport_key} → HTTP {resp.status_code}")
            return []
        return resp.json()
    except Exception as e:
        logger.error(f"Scores fetch error {sport_key}: {e}")
        return []


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


def _get_checkable_rows(pending_rows) -> list:
    """Return only rows whose ALL picks have already kicked off (commence_time < now).

    Future days (e.g. Day 7-10) are excluded — we can't check scores
    for games that haven't started yet.
    """
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
    """Check if all picks in the given rows have had time to finish.

    A football match takes ~2h. The Odds API typically marks scores
    within 1h after FT. So we wait 3h after the last kickoff.
    Only considers rows whose games have already kicked off.
    """
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
    if not latest:
        return False
    try:
        last_check = datetime.fromisoformat(_last_successful_check)
        return last_check > latest + timedelta(hours=3)
    except Exception:
        return False


def _collect_finished_scores(has_club_picks: bool = True) -> Dict[str, Dict[str, Any]]:
    """
    Return {match_key: {home, away, home_score, away_score, completed}}.

    Uses both match_id AND a "home_lower|away_lower|date" composite key,
    so we can match picks even if match_id-formats differ between calls.
    """
    sports = SCORES_SPORTS_WC + (SCORES_SPORTS_CLUB if has_club_picks else [])
    finished: Dict[str, Dict[str, Any]] = {}
    for sk in sports:
        for fx in fetch_scores(sk, days_from=5):
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
    summary = {"checked_chain_days": 0, "marked_won": 0, "marked_lost": 0, "still_pending": 0, "api_calls": 0}
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

            finished = _collect_finished_scores(has_club_picks=True)
            summary["api_calls"] = len(SCORES_SPORTS_WC) + len(SCORES_SPORTS_CLUB)
            if not finished:
                logger.info("Results check: no finished matches returned by Odds API")
                return summary

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
                    match_data = finished.get(mid) or finished.get(composite)
                    if not match_data:
                        logger.info(f"Day {row.day_number}: no score yet for {home} vs {away} (id={mid}, composite={composite})")
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
            logger.info(f"Results check: {summary}")
            return summary
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Results check failed: {e}", exc_info=True)
        return summary


def run_loop():
    """Background thread: check every hour, but only call API when games are done.

    Hourly poll costs 0 API calls (just a DB query + time check).
    Only when all pending games have finished (~3h after last kickoff)
    does it actually call the Odds API (~10 calls). Then it won't
    call again until new pending games appear.

    Worst case: ~10 API calls/day = ~300/month.
    """
    time.sleep(60)  # let the app finish booting
    iteration = 0
    while True:
        iteration += 1
        try:
            result = check_all_pending()
            api_used = result.get("api_calls", 0)
            if api_used:
                logger.info(f"Results check used {api_used} API calls this iteration")
        except Exception as e:
            logger.error(f"Results check loop iteration failed: {e}")
        time.sleep(3600)  # check every hour (0 API calls if games not done)

        if iteration % 168 == 0:  # ~weekly at 1h interval
            try:
                from worldcup.rollover_db import cleanup_old_chains
                cleanup_old_chains(keep_recent_chains=3)
            except Exception as e:
                logger.error(f"Rollover cleanup failed: {e}")


def start_background_loop():
    """Spawn the background results-checker thread."""
    t = threading.Thread(target=run_loop, daemon=True)
    t.start()
    logger.info("Results checker started (hourly poll, API calls only after games finish)")
    return t
