"""
Leagues — API Endpoints

The multi-league prediction engine (ESPN fixtures + ELO ratings + optional
bookmaker odds). Successor to the World Cup 2026 module; the WC-specific
endpoints (fixtures/groups/teams/value-bets) were removed with the tournament.

Mounted twice in main.py:
- /api/leagues/*   — canonical
- /api/worldcup/*  — back-compat alias for older frontend builds

Provides:
- GET  /daily-accumulators — daily category picks + rollover chain
- POST /check-results      — manually trigger the results checker
- GET  /debug-rollover     — rollover DB state + score-matching debug info
"""

import logging

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Leagues"])


@router.get("/daily-accumulators")
async def get_daily_accumulators():
    """Daily accumulator picks (2 odds / 5 odds / 10 odds / over 1.5 / rollover)."""
    try:
        from leagues.daily_feed import build_daily_accumulators
        result = build_daily_accumulators()
        if not result:
            raise HTTPException(404, "No predictions available")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error building daily accumulators: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.post("/check-results")
async def trigger_results_check():
    """Manually trigger a results check (also runs every 6h automatically)."""
    try:
        from leagues.results_checker import check_all_pending
        summary = check_all_pending()
        return {"status": "success", **summary}
    except Exception as e:
        logger.error(f"Results check trigger failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/debug-rollover")
async def debug_rollover():
    """Dump rollover DB state + scores matching debug info."""
    try:
        from leagues.rollover_db import RolloverDay
        from leagues.results_checker import _get_checkable_rows, _collect_finished_scores, _get_apifootball_key, _get_odds_api_key, ESPN_LEAGUE_SLUGS
        from database import SessionLocal
        import json as _json

        db = SessionLocal()
        try:
            rows = db.query(RolloverDay).order_by(RolloverDay.day_number).all()
            pending = [r for r in rows if r.status == "pending"]

            checkable = _get_checkable_rows(pending)
            checkable_days = {r.day_number for r in checkable}

            finished, source = _collect_finished_scores(checkable, has_club_picks=True) if checkable else ({}, "no_checkable")

            result = []
            for r in rows:
                picks = _json.loads(r.picks or "[]")
                result.append({
                    "day": r.day_number,
                    "date": r.date,
                    "status": r.status,
                    "checkable": r.day_number in checkable_days,
                    "num_picks": len(picks),
                    "picks_summary": [
                        {
                            "match": f"{p.get('home_team')} vs {p.get('away_team')}",
                            "commence_time": p.get("commence_time"),
                            "market": p.get("market"),
                            "prediction": p.get("prediction"),
                        }
                        for p in picks
                    ],
                })

            return {
                "total_rows": len(rows),
                "pending_count": len(pending),
                "checkable_count": len(checkable),
                "scores_source": source,
                "scores_found": len(finished),
                "espn_available": bool(ESPN_LEAGUE_SLUGS),
                "has_apifootball_key": bool(_get_apifootball_key()),
                "has_odds_api_key": bool(_get_odds_api_key()),
                "sample_scores": [
                    {"key": k, "home": v["home"], "away": v["away"], "score": f"{v['home_score']}-{v['away_score']}"}
                    for k, v in list(finished.items())[:8]
                ],
                "rows": result,
            }
        finally:
            db.close()
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}
