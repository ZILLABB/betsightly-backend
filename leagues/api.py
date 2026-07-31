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
    """Manually trigger a results check (also runs hourly in the background)."""
    try:
        from leagues.results_checker import check_all_pending, settle_published_slips
        summary = check_all_pending()
        slips = settle_published_slips()
        return {"status": "success", **summary, "slips": slips}
    except Exception as e:
        logger.error(f"Results check trigger failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/results")
async def get_results(days: int = 30, category: str | None = None):
    """Settled history for every category, not just the rollover chain.

    Returns each published slip with its legs and outcome, plus a per-category
    performance summary (win rate, profit and ROI at level 1-unit stakes).
    """
    try:
        from leagues.picks_db import get_history, performance_summary
        history = get_history(limit_days=days, category=category)

        by_date: dict[str, dict] = {}
        for slip in history:
            by_date.setdefault(slip["date"], {})[slip["category"]] = slip

        return {
            "status": "success",
            "days": days,
            "summary": performance_summary(limit_days=days),
            "history": history,
            "by_date": by_date,
        }
    except Exception as e:
        logger.error(f"Results fetch failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/performance")
async def get_performance(days: int = 90):
    """Win rate, profit and ROI per category over the requested window."""
    try:
        from leagues.picks_db import performance_summary
        return {"status": "success", "days": days, "summary": performance_summary(limit_days=days)}
    except Exception as e:
        logger.error(f"Performance fetch failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.post("/backfill-legs")
async def trigger_leg_backfill(days: int = 120):
    """Recover per-leg outcomes on chain days settled before we recorded them."""
    try:
        from leagues.results_checker import backfill_leg_status
        return {"status": "success", **backfill_leg_status(limit_days=days)}
    except Exception as e:
        logger.error(f"Leg backfill failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/calibration")
async def get_calibration(days: int = 180):
    """Predicted confidence against measured hit rate, by confidence band.

    The check that matters for a probability: when the site says 70%, does it
    land 70% of the time? Bands with no settled legs report `actual: null`
    rather than a fabricated zero.
    """
    try:
        from leagues.picks_db import calibration
        return {"status": "success", **calibration(limit_days=days)}
    except Exception as e:
        logger.error(f"Calibration fetch failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/value-bets")
async def get_value_bets(days_ahead: int = 3, limit: int = 40):
    """Picks ranked by how much of the price the bookmaker keeps.

    This deliberately does not claim to find profitable bets, because on this
    data none exist. Two facts make that unavoidable:

    - DraftKings runs about a 9% overround on 1X2 in these leagues, well above
      the 2-4% a sharp book charges.
    - Our probabilities are anchored to that same book's de-vigged closing
      prices, so by construction they land near the market's own view. A model
      that reproduces the market cannot beat it, and expected value settles at
      roughly minus the margin. The best pick available today sits at -2.0%.

    Beating the closing line needs information the closing line lacks —
    several books to shop between, or a market the book prices lazily. Until
    that exists, the useful question is not "which bet wins" but "which bet
    is least taxed", and a -2% pick over a -9% one is a real, bankable
    improvement. `positive_ev_count` reports genuine +EV picks so the figure
    is visible the moment it stops being zero.
    """
    try:
        from leagues.engine import run_pipeline

        all_picks, _ = run_pipeline(days_ahead=days_ahead)
        rows = [
            {
                "match_id": p["match_id"],
                "home_team": p["_fixture"]["home"]["name"],
                "away_team": p["_fixture"]["away"]["name"],
                "home_team_logo": p["_fixture"]["home"].get("logo"),
                "away_team_logo": p["_fixture"]["away"].get("logo"),
                "league": p["_fixture"]["league"],
                "kickoff": p["_fixture"]["commence_time"],
                "prediction": p["prediction"],
                "market": p["market"],
                "market_group": p["market_group"],
                "confidence": p["confidence"],
                "odds": p["odds"],
                "odds_provider": p["odds_provider"],
                "edge": p["edge"],
                "expected_value": p["expected_value"],
                # Price you would need for this to break even
                "fair_odds": round(1.0 / p["confidence"], 2) if p["confidence"] else None,
                # Share of stake the book keeps on this pick, as a percentage
                "house_edge": round(-p["expected_value"] * 100, 2),
                "positive_ev": p["expected_value"] > 0,
            }
            for p in all_picks
            if p.get("odds_are_real") and p.get("expected_value") is not None
        ]
        rows.sort(key=lambda r: r["expected_value"], reverse=True)
        return {
            "status": "success",
            "count": len(rows),
            "positive_ev_count": sum(1 for r in rows if r["positive_ev"]),
            "best_expected_value": rows[0]["expected_value"] if rows else None,
            "value_bets": rows[:limit],
        }
    except Exception as e:
        logger.error(f"Value bets fetch failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/fixtures")
async def get_fixtures_list(days_ahead: int = 3):
    """Upcoming fixtures with prices and the leagues currently in play."""
    try:
        from leagues.engine import run_pipeline

        _, fixtures = run_pipeline(days_ahead=days_ahead)
        leagues: dict[str, dict] = {}
        for f in fixtures:
            entry = leagues.setdefault(
                f["league_slug"], {"slug": f["league_slug"], "name": f["league"], "count": 0}
            )
            entry["count"] += 1
        return {
            "status": "success",
            "total": len(fixtures),
            "leagues": sorted(leagues.values(), key=lambda x: -x["count"]),
        }
    except Exception as e:
        logger.error(f"Fixtures fetch failed: {e}", exc_info=True)
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
