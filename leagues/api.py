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


@router.get("/ml-shadow")
async def ml_shadow(days: int = 60):
    """How the trained ensemble is doing against the model actually in use.

    Both are scored on the same settled legs, so this is the evidence that
    decides whether the ensemble gets to move a published number. Brier score
    is the measure — mean squared error of the probability — because accuracy
    alone rewards a model that is confidently right and confidently wrong in
    equal measure, which is exactly what we are trying to avoid.

    Only legs where the ensemble had an opinion are compared; it declines on
    unpriced fixtures by design.
    """
    try:
        from leagues.ml_models import status as ml_status
        from leagues.picks_db import get_history

        pairs = []
        for slip in get_history(limit_days=days):
            for leg in slip.get("picks", []):
                if leg.get("status") not in ("won", "lost"):
                    continue
                ml = leg.get("ml_confidence")
                pub = leg.get("confidence")
                if ml is None or pub is None:
                    continue
                pairs.append((float(pub), float(ml), leg["status"] == "won",
                              leg.get("market")))

        if not pairs:
            # Same key as the populated response below. Reporting the model
            # under "ml" here and "model" there meant a caller had to know
            # which branch it hit to find the same field.
            return {
                "status": "success",
                "compared_legs": 0,
                "verdict": "No settled legs carry an ensemble opinion yet. "
                           "Shadow mode records one on every new pick from a "
                           "priced fixture; come back once those settle.",
                "model": ml_status(),
            }

        n = len(pairs)
        won = sum(1 for _, _, w, _ in pairs if w)
        brier_pub = sum((p - w) ** 2 for p, _, w, _ in pairs) / n
        brier_ml = sum((m - w) ** 2 for _, m, w, _ in pairs) / n
        mean_pub = sum(p for p, _, _, _ in pairs) / n
        mean_ml = sum(m for _, m, _, _ in pairs) / n
        actual = won / n

        by_market: dict[str, dict] = {}
        for pub, ml, w, market in pairs:
            b = by_market.setdefault(market or "?", {"n": 0, "pub": 0.0,
                                                     "ml": 0.0, "won": 0})
            b["n"] += 1
            b["pub"] += (pub - w) ** 2
            b["ml"] += (ml - w) ** 2
            b["won"] += int(w)
        for b in by_market.values():
            b["brier_published"] = round(b.pop("pub") / b["n"], 4)
            b["brier_ml"] = round(b.pop("ml") / b["n"], 4)
            b["hit_rate"] = round(b.pop("won") / b["n"], 4)

        better = brier_ml < brier_pub
        margin = abs(brier_pub - brier_ml)
        # 30 legs is not a verdict. Saying so is the whole point of shadowing.
        confident = n >= 100 and margin > 0.01

        return {
            "status": "success",
            "compared_legs": n,
            "actual_hit_rate": round(actual, 4),
            "published": {"mean_confidence": round(mean_pub, 4),
                          "brier": round(brier_pub, 4)},
            "ml": {"mean_confidence": round(mean_ml, 4),
                   "brier": round(brier_ml, 4)},
            "by_market": by_market,
            "verdict": (
                f"Ensemble is {'ahead' if better else 'behind'} by "
                f"{margin:.4f} Brier over {n} legs. "
                + ("Enough evidence to act on." if confident else
                   "Not enough to act on yet — needs 100+ legs and a clear margin.")
            ),
            "model": ml_status(),
        }
    except Exception as e:
        logger.error(f"ML shadow evaluation failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/live-scores")
async def get_live_scores():
    """Scores for the fixtures on today's card, keyed by match_id.

    Served apart from the card on purpose: the card is locked at 08:00 and must
    not change, while a score changes every few minutes. Merging them would
    force a choice between a stale score and a card that rewrites itself.
    """
    try:
        from leagues.live_scores import scores_for_card
        result = scores_for_card()
        return {"status": "success", "count": len(result.get("scores", {})), **result}
    except Exception as e:
        logger.error(f"Live scores failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/bookable-now")
async def get_bookable_now():
    """A slip built only from fixtures that have not kicked off yet.

    The 08:00 card is deliberately frozen — it is what people booked and what
    the record scores — so by mid-afternoon some of its legs have started and a
    late visitor cannot place it. This is a separate, freshly built slip from
    whatever is still ahead, so they have something they can actually get on.

    Never archived and never settled: it regenerates on every request, so it
    has no fixed identity to score, and counting it would let the track record
    quietly reroll its losers.
    """
    try:
        from leagues.daily_feed import build_bookable_now
        result = build_bookable_now()
        if not result:
            return {"status": "success", "available": False,
                    "reason": "No fixtures left to bet on today."}
        return {"status": "success", "available": True, **result}
    except Exception as e:
        logger.error(f"Bookable-now build failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.post("/check-results")
async def trigger_results_check():
    """Manually trigger a results check (also runs hourly in the background)."""
    try:
        from leagues.results_checker import check_all_pending, settle_published_slips
        summary = check_all_pending()
        slips = settle_published_slips()
        # Newly settled legs are exactly what the calibration is fitted on, so
        # refit now rather than serving a stale correction for up to six hours.
        try:
            from leagues.calibrator import fit_calibration
            fit = fit_calibration(force=True)
            summary["calibration_legs"] = fit.get("n", 0)
        except Exception as e:
            logger.warning(f"calibration refit after settlement failed: {e}")
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


@router.post("/restart")
async def restart_everything(full_rollover: bool = True, republish_card: bool = True):
    """Clean slate: fresh rollover chain from day 1, today's card rebuilt.

    What this clears:
    - the whole rollover chain, including settled days, so it restarts at day 1
    - today's locked card, so it republishes under the current rules

    What it deliberately keeps, and why: the settled slip archive. The
    calibration is *fitted on* those outcomes — it is the thing currently
    holding published confidence to within a point of reality above 65%.
    Deleting the history would not give the predictions a fresh start, it would
    remove the correction and put the over-confidence straight back. It is also
    the track record, and one that drops its losing days is worth nothing.
    """
    try:
        from datetime import datetime, timezone
        from database import SessionLocal
        from leagues.rollover_db import RolloverDay
        from leagues import daily_feed
        from leagues.picks_db import DailyCard

        out: dict = {"status": "success"}
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if full_rollover:
            db = SessionLocal()
            try:
                removed = db.query(RolloverDay).delete()
                db.commit()
                out["rollover_days_cleared"] = removed
            finally:
                db.close()

        if republish_card:
            publish_date = daily_feed._publish_date()
            db = SessionLocal()
            try:
                gone = (db.query(DailyCard)
                        .filter(DailyCard.publish_date == publish_date).delete())
                db.commit()
                out["cards_cleared"] = gone
                out["publish_date"] = publish_date
            finally:
                db.close()

        daily_feed._accum_cache.update({"result": None, "ts": 0.0})
        result = daily_feed.build_daily_accumulators(force=True)
        if not result:
            raise HTTPException(503, "No fixtures available to rebuild from.")

        accums = result.get("accumulators", {})
        out["card"] = {
            k: {"picks": len(v.get("games", [])),
                "odds": v.get("total_odds"),
                "lands": v.get("hit_probability") or v.get("today_hit_probability")}
            for k, v in accums.items()
        }
        out["kept"] = ("settled slip archive — the calibration is fitted on it, "
                       "and it is the published track record")
        return out
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Restart failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.post("/repair-singles")
async def repair_singles():
    """Re-score singles tiers that were settled under the accumulator rule.

    Over 1.5 publishes ten independent bets, but every slip was settled by
    "any leg lost, so the slip lost". A tier hitting nine from ten was being
    recorded as a loss. This tags those slips as singles and re-derives their
    status from the legs, which are stored correctly and untouched.
    """
    try:
        import json as _json
        from database import SessionLocal
        from leagues.picks_db import PublishedSlip, ensure_table

        ensure_table()
        fixed = []
        db = SessionLocal()
        try:
            rows = db.query(PublishedSlip).filter(
                PublishedSlip.category == "over_1_5").all()
            for r in rows:
                legs = _json.loads(r.picks or "[]")
                r.presentation = "singles"
                results = [l.get("status") or "pending" for l in legs]
                if not results or any(o == "pending" for o in results):
                    new_status = "pending"
                else:
                    staked = sum(1 for o in results if o in ("won", "lost"))
                    returned = sum(float(l.get("odds") or 0)
                                   for l, o in zip(legs, results) if o == "won")
                    new_status = "won" if returned > staked else "lost"
                if new_status != r.status:
                    fixed.append({"date": r.date, "was": r.status, "now": new_status,
                                  "legs": f"{sum(1 for o in results if o=='won')}W"
                                          f"/{sum(1 for o in results if o=='lost')}L"})
                    r.status = new_status
            db.commit()
        finally:
            db.close()
        return {"status": "success", "slips_retagged": len(rows), "restated": fixed}
    except Exception as e:
        logger.error(f"repair-singles failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.post("/rebuild-rollover")
async def rebuild_rollover():
    """Rebuild the unsettled part of the rollover chain.

    The chain used to aim at ~1.9x a day, which forced two legs around 65% and
    left each day landing about 43% of the time. A ten-day chain needs every
    day, so that design completed 0.43^10 — two chances in ten thousand — and
    it duly went 0 for 4 with every loss caused by the second leg. Days are now
    a single pick near 80%.

    Days already published for future dates still carry the old two-leg build,
    so they are dropped and regenerated. Settled days are never touched: the
    losses stay on the record, because a track record that deletes its losing
    days is worth nothing.
    """
    try:
        from datetime import datetime, timezone
        from leagues.rollover_db import drop_pending_days
        from leagues import daily_feed

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        dropped = drop_pending_days(today)

        daily_feed._accum_cache.update({"result": None, "ts": 0.0})
        result = daily_feed.build_daily_accumulators(force=True)
        rollover = (result or {}).get("accumulators", {}).get("rollover", {})

        return {
            "status": "success",
            "dropped_pending_days": dropped,
            "chain_length": rollover.get("chain_length"),
            "today_hit_probability": rollover.get("today_hit_probability"),
        }
    except Exception as e:
        logger.error(f"Rollover rebuild failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.post("/repair-card")
async def repair_card():
    """Fill tiers today's locked card left empty, without touching the rest.

    A tier can be published empty for two quite different reasons — the day
    genuinely could not reach the target, or the value gate rejected the only
    slip available. When a gate turns out to have been mis-set, the tier stays
    blank until the next 08:00 WAT publish even though a perfectly good slip
    exists for fixtures that have not kicked off.

    This rebuilds the card and copies across only the tiers that are currently
    empty. Anything already published is left untouched, so the guarantee that
    matters — a slip you booked this morning is still the slip on the site —
    holds exactly as before.
    """
    try:
        from leagues import daily_feed
        from leagues.picks_db import fill_empty_card_tiers

        fresh = daily_feed.build_daily_accumulators(force=True)
        if not fresh:
            raise HTTPException(404, "Could not rebuild the card")

        publish_date = daily_feed._publish_date()
        filled = fill_empty_card_tiers(publish_date, fresh.get("accumulators", {}))

        # Rebuilding with force=True leaves the *unlocked* card in the response
        # cache, which would serve freshly-reselected picks past the lock until
        # the TTL expired. Drop it so the next read comes off the repaired card.
        daily_feed._accum_cache.update({"result": None, "ts": 0.0})

        return {"status": "success", "publish_date": publish_date, "filled": filled}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Card repair failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/calibration-fit")
async def get_calibration_fit():
    """The correction currently being applied to model probabilities.

    `/calibration` reports whether published confidences matched reality.
    This reports what is being done about it: the fitted shift per market
    group, the sample behind each one, and worked examples of what the
    correction does to a few reference probabilities — which is much easier to
    sanity-check than a shift in log-odds.
    """
    try:
        from leagues.calibrator import status
        return {"status": "success", **status()}
    except Exception as e:
        logger.error(f"Calibration fit fetch failed: {e}", exc_info=True)
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
                key = (f["match_id"], outcome)
                if key in seen:
                    continue
                seen.add(key)
                label = {"home_win": f["home"]["name"], "away_win": f["away"]["name"]}.get(outcome, "Draw")
                rows.append({
                    "match_id": f["match_id"],
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
