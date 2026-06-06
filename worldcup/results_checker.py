"""
Results checker for picks (WC + club leagues).

Periodically asks The Odds API /scores endpoint for finished matches,
then marks each rollover-day's status as won/lost based on the picks
within it.

Public entry points:
- check_all_pending() — scan all unresolved chain days, update statuses
- run_loop()          — background thread that calls check_all_pending every 6h

Pure additive — never deletes data, never breaks the pipeline.
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

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")

# Map sport_key → friendly check (matches club_odds.ACTIVE_LEAGUES)
SCORES_SPORTS = [
    "soccer_fifa_world_cup",
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


def fetch_scores(sport_key: str, days_from: int = 3) -> List[dict]:
    """Fetch finished match scores from The Odds API."""
    if not ODDS_API_KEY:
        return []
    try:
        resp = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores",
            params={"apiKey": ODDS_API_KEY, "daysFrom": days_from, "dateFormat": "iso"},
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
        # "X or Draw"
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


def _collect_finished_scores() -> Dict[str, Dict[str, Any]]:
    """
    Return {match_key: {home, away, home_score, away_score, completed}}.

    Uses both match_id AND a "home_lower|away_lower|date" composite key,
    so we can match picks even if match_id-formats differ between calls.
    """
    finished: Dict[str, Dict[str, Any]] = {}
    for sk in SCORES_SPORTS:
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
            # Index by match_id and by composite key
            mid = fx.get("id")
            if mid:
                finished[mid] = payload
            commence = fx.get("commence_time", "")[:10]
            ck = f"{_normalize_name(home)}|{_normalize_name(away)}|{commence}"
            finished[ck] = payload
        time.sleep(0.2)
    return finished


def check_all_pending() -> Dict[str, int]:
    """Scan all pending rollover days; mark won/lost where matches finished."""
    summary = {"checked_chain_days": 0, "marked_won": 0, "marked_lost": 0, "still_pending": 0}
    try:
        from worldcup.rollover_db import RolloverDay
        from database import SessionLocal
    except Exception as e:
        logger.warning(f"Results check skipped — DB not available: {e}")
        return summary

    try:
        finished = _collect_finished_scores()
        if not finished:
            logger.info("Results check: no finished matches returned by Odds API")
            return summary

        db = SessionLocal()
        try:
            pending = db.query(RolloverDay).filter(RolloverDay.status == "pending").all()
            summary["checked_chain_days"] = len(pending)

            for row in pending:
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
                        pick_results.append("pending")
                        continue
                    r = _evaluate_pick(pick, match_data["home_score"], match_data["away_score"])
                    pick_results.append(r)

                # Day is "won" if all picks won, "lost" if any lost, else still pending
                if any(r == "lost" for r in pick_results):
                    row.status = "lost"
                    summary["marked_lost"] += 1
                elif all(r == "won" for r in pick_results):
                    row.status = "won"
                    summary["marked_won"] += 1
                else:
                    summary["still_pending"] += 1

            db.commit()
            logger.info(f"Results check: {summary}")
            return summary
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Results check failed: {e}", exc_info=True)
        return summary


def run_loop(interval_hours: float = 6.0):
    """Background thread entry point — runs check_all_pending every N hours."""
    while True:
        time.sleep(interval_hours * 3600)
        try:
            check_all_pending()
        except Exception as e:
            logger.error(f"Results check loop iteration failed: {e}")


def start_background_loop():
    """Spawn the background results-checker thread."""
    t = threading.Thread(target=run_loop, daemon=True)
    t.start()
    logger.info("Results checker background loop started (6h interval)")
    return t
