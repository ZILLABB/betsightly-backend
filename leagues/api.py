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
async def get_value_bets(days_ahead: int = 3, limit: int = 40, min_ev: float = 0.02):
    """Bets priced above fair value once every bookmaker is compared.

    Against a single book this list is always empty, and for a structural
    reason: DraftKings runs ~9% overround on these leagues and our
    probabilities are derived from its own prices, so the model reproduces the
    market and expected value settles at minus the margin.

    Shopping the whole market changes the arithmetic rather than the model.
    Measured on Arsenal vs Coventry across 39 books, taking the best quote on
    each outcome gives an overround of 0.9996 — the house edge disappears, and
    individual quotes scatter widely (Coventry ranged 13.0 to 20.0). Value is
    then consensus probability, the median de-vigged view of all 39 books,
    multiplied by the best price anyone is offering. It is positive precisely
    when one book is out of step with everybody else, which is a real edge in
    a way that beating a single book's own de-vigged number never was.

    Two honest caveats travel with each row, and both are returned so the
    frontend can show them: exchanges quote before commission (typically 2-5%,
    which eats part of a small edge), and the best price is often the one with
    the lowest stake limit.
    """
    try:
        from leagues.engine import run_pipeline
        from leagues.odds_shop import shop_odds, lookup, budget_status

        all_picks, fixtures = run_pipeline(days_ahead=days_ahead)

        # Only shop leagues we are actually publishing from, busiest first —
        # the free tier is 500 credits a month and blanket fetching every
        # league would exhaust it inside a week. The budget guard inside
        # shop_odds stops early if the daily ceiling is reached.
        from collections import Counter
        from leagues.odds_shop import SLUG_TO_ODDS_KEY
        ranked = [s for s, _ in Counter(f["league_slug"] for f in fixtures).most_common()
                  if s in SLUG_TO_ODDS_KEY]
        shopped = shop_odds(ranked[:6])

        rows = []
        seen = set()
        for f in fixtures:
            hit = lookup(shopped, f["home"]["name"], f["away"]["name"])
            if not hit:
                continue
            for outcome, o in hit["outcomes"].items():
                cp, bp = o.get("consensus_prob"), o.get("best_price")
                if not cp or not bp:
                    continue
                ev = cp * bp - 1
                if ev < min_ev:
                    continue
                key = (f["id"], outcome)
                if key in seen:
                    continue
                seen.add(key)
                label = {"home_win": f["home"]["name"], "away_win": f["away"]["name"]}.get(outcome, "Draw")
                rows.append({
                    "match_id": f["id"],
                    "home_team": f["home"]["name"],
                    "away_team": f["away"]["name"],
                    "home_team_logo": f["home"].get("logo"),
                    "away_team_logo": f["away"].get("logo"),
                    "league": f["league"],
                    "kickoff": f["commence_time"],
                    "prediction": f"{label} Win" if outcome != "draw" else "Draw",
                    "market": outcome,
                    "market_group": "match_result",
                    "confidence": round(cp, 4),
                    "odds": bp,
                    "odds_provider": o.get("best_book"),
                    "book_count": o.get("books"),
                    "expected_value": round(ev, 4),
                    "edge": round(cp - 1.0 / bp, 4),
                    "fair_odds": round(1.0 / cp, 2),
                    "house_edge": round(-ev * 100, 2),
                    "positive_ev": True,
                    "is_exchange": (o.get("best_book") or "").lower() in
                        ("betfair", "smarkets", "matchbook", "betdaq"),
                })

        rows.sort(key=lambda r: r["expected_value"], reverse=True)
        return {
            "status": "success",
            "count": len(rows),
            "positive_ev_count": len(rows),
            "best_expected_value": rows[0]["expected_value"] if rows else None,
            "books_compared": max((r["book_count"] or 0) for r in rows) if rows else 0,
            "budget": budget_status(),
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
