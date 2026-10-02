"""
Leagues — API Endpoints

The multi-league prediction engine (ESPN fixtures + ELO ratings + optional
bookmaker odds). Successor to the World Cup 2026 module; the WC-specific
endpoints (fixtures/groups/teams) were removed with the tournament.

Mounted twice in main.py:
- /api/leagues/*   — canonical
- /api/worldcup/*  — back-compat alias for older frontend builds

Provides:
- GET  /daily-accumulators — daily category picks + rollover chain
- POST /check-results      — manually trigger the results checker
- GET  /debug-rollover     — rollover DB state + score-matching debug info
"""

import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from utils.security import require_api_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Leagues"])


@router.get(
    "/slip-builder/v2/staging-evidence-status",
    dependencies=[Depends(require_api_key)],
)
async def staging_v2_evidence_status():
    """Read-only staging V2 worker state and supplemental blocker counts."""
    from leagues.football_first_shadow_v2_automation import status
    return status()


@router.post(
    "/slip-builder/v2/staging-evidence-refresh",
    dependencies=[Depends(require_api_key)],
)
async def staging_v2_evidence_refresh(force_history: bool = False):
    """Trigger one non-blocking staging-only V2 evidence cycle."""
    from leagues.football_first_shadow_v2_automation import trigger_once
    return trigger_once(force_history=bool(force_history))


@router.get(
    "/slip-builder/v2/shadow-board-status",
    dependencies=[Depends(require_api_key)],
)
async def sportybet_first_shadow_board_status():
    """Read-only SportyBet-first shadow inventory health.

    This endpoint never refreshes providers and the shadow inventory cannot
    publish, book, settle, or replace the production prepared board.
    """
    from leagues.sportybet_inventory import status

    return status()


@router.get(
    "/slip-builder/v2/shadow-board-compare",
    dependencies=[Depends(require_api_key)],
)
async def sportybet_first_shadow_board_compare():
    """Cache-only SportyBet-first coverage/support comparison."""
    from leagues.sportybet_shadow_compare import status

    return status()


@router.get(
    "/slip-builder/v2/shadow-prediction-board-status",
    dependencies=[Depends(require_api_key)],
)
async def sportybet_first_shadow_prediction_board_status():
    """Read-only current-engine overlap on the SportyBet-first shadow board."""
    from leagues.sportybet_shadow_board import status

    return status()


@router.get("/decision-quality", dependencies=[Depends(require_api_key)])
async def decision_quality_report(days: int = 30):
    """Admin-gated, read-only readiness and decision-memory report."""
    from leagues.decision_archive import quality_report
    return quality_report(days)


@router.post("/decision-replay/{snapshot_id}",
             dependencies=[Depends(require_api_key)])
async def replay_decision_snapshot(snapshot_id: str,
                                   policy: str = "CURRENT_POLICY"):
    """Provider-isolated replay. It cannot publish, book, or settle."""
    from leagues.decision_archive import replay
    try:
        return replay(snapshot_id, policy)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/daily-accumulators")
def get_daily_accumulators():
    """Daily accumulator picks (2 odds / 5 odds / 10 odds / over 1.5 / rollover)."""
    from leagues.history_readiness import HistoryNotReady
    try:
        from leagues.daily_feed import build_daily_accumulators
        result = build_daily_accumulators(allow_generation=False)
        if not result:
            raise HTTPException(404, "No predictions available")
        return result
    except HTTPException:
        raise
    except HistoryNotReady:
        from leagues.history_readiness import status
        raise HTTPException(503, {"reason": "history_not_ready", "history": status()})
    except Exception as e:
        logger.error(f"Error building daily accumulators: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/history-readiness")
def get_history_readiness():
    """Credential-free evidence readiness, without provider or database URLs."""
    from leagues.history_readiness import status
    return status()


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


class FootballFirstShadowReviewRequest(BaseModel):
    decision: str
    reviewer: str | None = None
    note: str | None = None


@router.get("/football-first-shadow")
def football_first_shadow_report():
    try:
        from leagues.football_first_shadow_observations import shadow_report
        return shadow_report()
    except Exception as e:
        logger.error(
            f"Football-first shadow report failed: {e}",
            exc_info=True,
        )
        raise HTTPException(500, str(e))


@router.post(
    "/football-first-shadow/settle",
    dependencies=[Depends(require_api_key)],
)
def football_first_shadow_settle(limit: int = 250):
    try:
        from leagues.football_first_shadow_observations import (
            settle_pending_observations,
        )
        return settle_pending_observations(
            limit=max(1, min(1000, int(limit)))
        )
    except Exception as e:
        logger.error(
            f"Football-first shadow settlement failed: {e}",
            exc_info=True,
        )
        raise HTTPException(500, str(e))


@router.get(
    "/football-first-shadow/review",
    dependencies=[Depends(require_api_key)],
)
def football_first_shadow_review_packet():
    try:
        from leagues.football_first_shadow_observations import review_packet
        return review_packet()
    except Exception as e:
        logger.error(
            f"Football-first shadow review packet failed: {e}",
            exc_info=True,
        )
        raise HTTPException(500, str(e))


@router.post(
    "/football-first-shadow/review",
    dependencies=[Depends(require_api_key)],
)
def football_first_shadow_record_review(
    request: FootballFirstShadowReviewRequest,
):
    try:
        from leagues.football_first_shadow_observations import record_review
        return record_review(
            request.decision,
            reviewer=request.reviewer,
            note=request.note,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except Exception as e:
        logger.error(
            f"Football-first shadow review decision failed: {e}",
            exc_info=True,
        )
        raise HTTPException(500, str(e))


@router.get("/football-first-shadow-v2")
def football_first_shadow_v2_report():
    """Read-only prospective V2 evidence report."""
    try:
        from leagues.football_first_shadow_v2_observations import (
            shadow_report,
        )

        return shadow_report()

    except Exception as e:
        logger.error(
            f"Football-first V2 shadow report failed: {e}",
            exc_info=True,
        )

        raise HTTPException(
            500,
            str(e),
        )


@router.post(
    "/football-first-shadow-v2/settle",
    dependencies=[
        Depends(
            require_api_key
        )
    ],
)
def football_first_shadow_v2_settle(
    limit: int = 250,
):
    """Settle only the current V2 model-version observations."""
    try:
        from leagues.football_first_shadow_v2_observations import (
            settle_pending_observations,
        )

        return (
            settle_pending_observations(
                limit=max(
                    1,
                    min(
                        1000,
                        int(
                            limit
                        ),
                    ),
                )
            )
        )

    except Exception as e:
        logger.error(
            f"Football-first V2 settlement failed: {e}",
            exc_info=True,
        )

        raise HTTPException(
            500,
            str(e),
        )


@router.get(
    "/football-first-shadow-v2/review",
    dependencies=[
        Depends(
            require_api_key
        )
    ],
)
def football_first_shadow_v2_review_packet():
    """Return V2-only evidence and human-review gates."""
    try:
        from leagues.football_first_shadow_v2_observations import (
            review_packet,
        )

        return review_packet()

    except Exception as e:
        logger.error(
            f"Football-first V2 review packet failed: {e}",
            exc_info=True,
        )

        raise HTTPException(
            500,
            str(e),
        )


@router.post(
    "/football-first-shadow-v2/review",
    dependencies=[
        Depends(
            require_api_key
        )
    ],
)
def football_first_shadow_v2_record_review(
    request: FootballFirstShadowReviewRequest,
):
    """Record a V2 human decision without changing the live model."""
    try:
        from leagues.football_first_shadow_v2_observations import (
            record_review,
        )

        return record_review(
            request.decision,
            reviewer=request.reviewer,
            note=request.note,
        )

    except ValueError as exc:
        raise HTTPException(
            409,
            str(exc),
        )

    except Exception as e:
        logger.error(
            f"Football-first V2 review decision failed: {e}",
            exc_info=True,
        )

        raise HTTPException(
            500,
            str(e),
        )


@router.get(
    "/football-first-shadow-v2/automation"
)
def football_first_shadow_v2_automation_status():
    """Read-only health for staging prospective-evidence automation."""

    try:
        from leagues.football_first_shadow_v2_automation import (
            status as automation_status,
        )

        from leagues.football_first_shadow_v2_observations import (
            shadow_report,
        )

        report = (
            shadow_report()
        )

        return {
            "status":
                "success",

            "automation":
                automation_status(),

            "model":
                report.get(
                    "model"
                ),

            "observations":
                report.get(
                    "observations"
                ),

            "evidence_progress":
                report.get(
                    "evidence_progress"
                ),

            "comparison_status":
                (
                    report.get(
                        "comparison"
                    )
                    or {}
                ).get(
                    "status"
                ),

            "automatic_promotion":
                False,
        }

    except Exception as e:
        logger.error(
            f"Football-first V2 automation status failed: {e}",
            exc_info=True,
        )

        raise HTTPException(
            500,
            str(e),
        )


@router.get("/live-scores")
def get_live_scores():
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
def get_bookable_now():
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
        picks, _, board = _public_prepared_board(2)
        result = build_bookable_now(all_picks=picks)
        if not result:
            return {"status": "success", "available": False,
                    "reason": "No fixtures left to bet on today.", "board": board}
        return {"status": "success", "available": True, **result,
                "board": board}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bookable-now build failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.post("/check-results", dependencies=[Depends(require_api_key)])
async def trigger_results_check():
    """Manually trigger a results check (also runs hourly in the background)."""
    try:
        from leagues.results_checker import (
            check_all_pending, settle_builder_predictions,
            settle_published_slips,
        )
        summary = check_all_pending()
        slips = settle_published_slips()
        builders = settle_builder_predictions()
        try:
            from leagues.football_first_shadow_observations import (
                settle_pending_observations,
            )
            football_first_shadow = settle_pending_observations()
        except Exception as e:
            logger.warning(
                f"football-first shadow settlement during check-results failed: {e}"
            )
            football_first_shadow = {
                "status": "ERROR",
                "error_type": type(e).__name__,
            }
        # Newly settled legs are exactly what the calibration is fitted on, so
        # refit now rather than serving a stale correction for up to six hours.
        try:
            from leagues.calibrator import fit_calibration
            fit = fit_calibration(force=True)
            summary["calibration_legs"] = fit.get("n", 0)
        except Exception as e:
            logger.warning(f"calibration refit after settlement failed: {e}")
        return {
            "status": "success",
            **summary,
            "slips": slips,
            "builders": builders,
            "football_first_shadow": football_first_shadow,
        }
    except Exception as e:
        logger.error(f"Results check trigger failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.post("/run-daily", dependencies=[Depends(require_api_key)])
async def trigger_daily_run(force: bool = False, publish: bool = True):
    """Settle, publish today's card, then distribute. Safe to call twice.

    The scheduled entry point. Guarded by X-API-Key because it is expensive
    and side-effectful — it posts to Telegram — not because the data is
    secret. Idempotent regardless: a second call on the same publishing day
    returns `skipped` rather than repeating the work.
    """
    try:
        from leagues.scheduler import start_daily_job
        return start_daily_job(force=force, publish=publish)
    except Exception as e:
        logger.error(f"Daily run failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/daily-runs")
async def get_daily_runs(limit: int = 14):
    """Whether the daily job actually ran, and what it did."""
    from leagues.scheduler import last_runs
    runs = last_runs(limit=limit)
    return {"status": "success", "count": len(runs), "runs": runs}


@router.post("/book-tiers", dependencies=[Depends(require_api_key)])
async def trigger_tier_booking(force: bool = False):
    """Generate SportyBet booking codes for today's published tiers.

    Runs as part of the daily job; exposed separately so a tier that failed to
    book — a fixture missing from the board, a market suspended — can be
    retried without republishing the card. Idempotent: a tier already holding
    a valid code is left alone unless `force` is set.
    """
    try:
        from leagues.booking import book_card
        from leagues.daily_feed import build_daily_accumulators, _publish_date
        card = build_daily_accumulators(allow_generation=False)
        if not card:
            raise HTTPException(404, "no card to book")
        result = book_card(_publish_date(), card.get("accumulators") or {}, force=force)
        # Manual incident recovery must become visible immediately, just like
        # the scheduler path. Otherwise the cached code-free card survives.
        from leagues import daily_feed
        daily_feed._accum_cache.update({"result": None, "ts": 0.0})
        return {"status": "success", **result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Tier booking failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/bookings")
async def get_bookings(date: str | None = None):
    """Booking codes for a publishing day, and why any tier has none."""
    from leagues.booking import bookings_for, leg_fingerprint
    from leagues.daily_feed import _publish_date, build_daily_accumulators
    day = date or _publish_date()
    stored = bookings_for(day)

    # Why a tier on the card has no code, answered from the same place the
    # codes are read. Stored bookings and the served card agreeing on every
    # input while the card still carries nothing is a gap that cannot be seen
    # from either endpoint alone.
    attach: dict = {}
    try:
        card = build_daily_accumulators(allow_generation=False) or {}
        accs = card.get("accumulators") or {}
        attach = {
            "card_date": card.get("date"),
            "dates_match": card.get("date") == day,
            "tiers_on_card": sorted(accs.keys()),
            "tiers_stored": sorted(stored.keys()),
            "carrying_a_booking": sorted(
                k for k, v in accs.items()
                if isinstance(v, dict) and v.get("booking")),
            "fingerprints": {
                k: {"stored": (stored.get(k) or {}).get("leg_fingerprint"),
                    "live": leg_fingerprint((v or {}).get("games") or [])}
                for k, v in accs.items()
                if isinstance(v, dict) and (stored.get(k) or {}).get("leg_fingerprint")
            },
        }
    except Exception as e:
        attach = {"error": f"{type(e).__name__}: {e}"}

    return {"status": "success", "date": day,
            "count": sum(1 for v in stored.values()
                         if v.get("status") == "active"),
            "bookings": stored,
            "attach": attach}


# Built slips, keyed on (target, horizon, day). Generating one runs the
# optimizer and posts a booking, so an uncached public endpoint would let a
# refresh loop mint codes at a bookmaker indefinitely. Two readers asking for
# the same thing on the same day get the same slip, which is also the honest
# answer — there is one best combination, not one per visitor.
_SLIP_CACHE: dict = {}
_SLIP_TTL = 1800
_SLIP_LOCKS: dict = {}
_V2_TARGET_CACHE: dict = {}
_V2_TARGET_LOCKS: dict = {}
_BUILDER_REVISION_LOCKS: dict = {}
_MAX_BUILDER_CACHE_ENTRIES = 32


def _prune_builder_results(cache: dict, locks: dict, now: float) -> None:
    """Bound full response retention without removing an in-flight lock."""
    expired = [key for key, item in cache.items()
               if now - float(item.get("ts") or 0) >= _SLIP_TTL]
    for key in expired:
        cache.pop(key, None)
    while len(cache) > _MAX_BUILDER_CACHE_ENTRIES:
        oldest = min(cache, key=lambda key: cache[key].get("ts", 0))
        cache.pop(oldest, None)
    for key, lock in list(locks.items()):
        if key not in cache and not lock.locked():
            locks.pop(key, None)


class BuilderRevisionRequest(BaseModel):
    revision: int = Field(ge=1)
    request_id: str = Field(min_length=8, max_length=64)
    edit_token: str = Field(min_length=24, max_length=128)
    action: str
    selection_id: str | None = None
    fixture_id: str | None = None
    target: float | None = None



class BuilderV2Filters(BaseModel):
    horizon: str = "7_days"
    markets: list[str] = Field(default_factory=list)
    min_odds: float | None = None
    max_odds: float | None = None
    min_probability: float | None = Field(default=None, ge=0, le=1)
    min_trust_grade: str = "B"
    include_leagues: list[str] = Field(default_factory=list)
    exclude_leagues: list[str] = Field(default_factory=list)
    exclude_fixture_ids: list[str] = Field(default_factory=list)
    exclude_team_ids: list[str] = Field(default_factory=list)
    require_bookable: bool = True
    # Anonymous-only until an authenticated Builder context exists server-side.
    anonymous_id: str | None = Field(default=None, min_length=16, max_length=128)


class BuilderV2Request(BuilderV2Filters):
    mode: str
    target_odds: float | None = None
    game_count: int | None = None
    max_games: int | None = None
    fill_strategy: str = "strict_selected_markets"
    refresh: bool = False
    build_another: bool = False


class BuilderV2ManualRequest(BuilderV2Filters):
    selection_ids: list[str] = Field(default_factory=list)


def _builder_v2_payload(model: BaseModel) -> dict:
    """Return only fields that belong to Builder selection/optimization."""
    payload = (
        model.model_dump()
        if hasattr(model, "model_dump")
        else model.dict()
    )
    payload.pop("anonymous_id", None)
    # User-history behavior is orchestrated by the API boundary and must not
    # become a prediction/model/cache input.
    payload.pop("build_another", None)
    return payload


def _builder_v2_persistence_payload(
    model: BaseModel,
    engine_payload: dict | None = None,
) -> dict:
    """Restore request identity only for audit/history persistence."""
    payload = dict(engine_payload or _builder_v2_payload(model))
    anonymous_id = getattr(model, "anonymous_id", None)
    if anonymous_id:
        payload["anonymous_id"] = anonymous_id
    if bool(getattr(model, "build_another", False)):
        payload["build_another"] = True
    return payload

def _record_v2_result(payload: dict, result: dict, started: float) -> None:
    """Adapt V2 to the existing settlement archive; log only safe facts."""
    import time
    from leagues.builder_runs import record_run

    persistence_started = time.perf_counter()
    try:
        record_run(
            payload.get("target_odds") if payload.get("mode") == "target_odds" else None,
            payload.get("horizon", "7_days"), bool(payload.get("refresh")),
            result, cached=bool(result.get("cached")), request_id=result["request_id"],
            mode=payload.get("mode", "target_odds"),
            fill_strategy=payload.get("fill_strategy") if payload.get("mode") == "game_count" else None,
            requested_markets=payload.get("markets") or [],
            requested_game_count=(payload.get("game_count")
                                  if payload.get("mode") == "game_count" else None),
        )
        if payload.get("anonymous_id"):
            from leagues.ticket_history import record_generated_ticket
            record_generated_ticket(payload, result)
    except Exception as exc:
        logger.error("builder_v2_persistence_failed request_id=%s error_type=%s",
                     result["request_id"], type(exc).__name__)
    booking = result.get("booking") or {}
    diagnostics = result.get("selection_diagnostics_v2") or result.get("selection_diagnostics") or {}
    logger.info("builder_v2_result %s", {
        "request_id": result["request_id"], "mode": payload.get("mode"),
        "horizon": payload.get("horizon"),
        "board_snapshot_id": (result.get("board") or {}).get("board_snapshot_id"),
        "candidate_count": diagnostics.get("approved_count"),
        "delivered": len(result.get("games") or []), "shortfall": result.get("shortfall"),
        "booking_status": booking.get("booking_status"),
        "readback_status": booking.get("readback_validation"), "status": result.get("status"),
        "requested_target": payload.get("target_odds"), "achieved_odds": result.get("odds"),
        "best_reachable": result.get("best_reachable"),
        "binding_constraints": diagnostics.get("primary_binding_constraint"),
        "requested_selection_count": len(payload.get("selection_ids") or []),
        "invalid_count": len(result.get("invalid_selections") or []),
        "valid_count": result.get("valid_count", len(result.get("games") or [])),
        "candidate_timing_ms": diagnostics.get("timing_ms"),
        "booking_timing_ms": booking.get("timing_ms"),
        "generation_timing_ms": result.get("timing_ms"),
        "persistence_ms": round((time.perf_counter() - persistence_started) * 1000),
        "duration_ms": round((time.perf_counter() - started) * 1000),
    })

def _start_builder_revision(target: float, horizon: str, result: dict) -> dict:
    # Generation owns provenance; a later refresh cannot relabel this slip.
    if result.get("board"):
        if result.get("status") != "success" or not result.get("games"):
            return result
        from leagues.builder_revisions import create_initial_run
        return create_initial_run(target, horizon, result)
    try:
        from leagues.engine import prepared_board_status
        state = prepared_board_status(days_ahead=7)
        result = {**result, "board": {
            "ready": bool(state.get("ready")),
            "degraded": bool(state.get("degraded")),
            "complete": bool(state.get("complete")),
            "fixture_count": int(state.get("fixture_count") or 0),
            "generated_at": state.get("generated_at"),
            "board_snapshot_id": state.get("board_snapshot_id"),
            "board_age_seconds": state.get("age_seconds"),
            "board_source": state.get("board_source"),
            "raw_fixture_count": int(state.get("raw_fixture_count") or 0),
            "evaluated_fixture_count": int(
                state.get("evaluated_fixture_count") or 0
            ),
            "successful_league_count": int(
                state.get("successful_league_count") or 0
            ),
            "requested_league_count": int(
                state.get("requested_league_count") or 0
            ),
            "failed_league_count": int(
                state.get("failed_league_count") or 0
            ),
        }}
    except Exception:
        result = dict(result)
    if result.get("status") != "success" or not result.get("games"):
        return result
    from leagues.builder_revisions import create_initial_run

    return create_initial_run(target, horizon, result)


def _cached_slip_is_placeable(result: dict, now: datetime | None = None) -> bool:
    """A cached slip must still contain only matches a user can book."""
    from leagues.availability import all_games_actionable

    now = now or datetime.now(timezone.utc)
    return all_games_actionable(result.get("games") or [], now)


def _cached_target_result_is_reusable(
    result: dict, now: datetime | None = None
) -> bool:
    """V2 target cache may reuse only an exact active SportyBet booking."""
    from leagues.booking import booking_lifecycle

    now = now or datetime.now(timezone.utc)
    games = result.get("games") or []

    if not games or not _cached_slip_is_placeable(result, now):
        return False

    checked = booking_lifecycle(result.get("booking") or {}, games, now)

    return bool(
        checked
        and checked.get("actionable")
        and checked.get("booking_status") in {"FULL", "REBUILT_FULL"}
        and str(checked.get("readback_validation") or "").upper() == "PASSED"
        and checked.get("share_code")
    )


def _log_builder_board(builder_run_id: str, target: float, horizon: str,
                       response: dict) -> None:
    """Emit safe board provenance for every Builder outcome."""
    board = response.get("board") or {}
    diagnostics = response.get("selection_diagnostics") or {}
    sporty = response.get("sportybet_board") or {}
    logger.info("builder_board %s", {
        "builder_run_id": builder_run_id, "horizon": horizon,
        "requested_target": round(float(target), 2),
        "board_snapshot_id": board.get("board_snapshot_id"),
        "board_generated_at": board.get("generated_at"),
        "board_age_seconds": board.get("board_age_seconds"),
        "board_source": board.get("board_source"),
        "ready": board.get("ready"), "degraded": board.get("degraded"),
        "complete": board.get("complete"),
        "requested_league_count": board.get("requested_league_count"),
        "successful_league_count": board.get("successful_league_count"),
        "failed_league_count": board.get("failed_league_count"),
        "raw_fixture_count": board.get("raw_fixture_count"),
        "evaluated_fixture_count": board.get("evaluated_fixture_count"),
        "approved_canonical_candidate_count": diagnostics.get(
            "after_policy_and_canonical_ranking"
        ),
        "optimizer_candidate_count": response.get("optimizer_candidate_count"),
        "sportybet_snapshot_id": sporty.get("snapshot_id"),
        "sportybet_page_count": sporty.get("page_count"),
        "sportybet_declared_pages": sporty.get("required_pages"),
        "sportybet_parsed_fixture_total": sporty.get("parsed_fixture_total"),
        "optimizer_status": response.get("optimization_status"),
        "achieved_odds": response.get("odds") or response.get("best_reachable"),
        "primary_binding_constraint": diagnostics.get(
            "primary_binding_constraint"
        ),
    })


@router.get("/slip-builder/targets")
async def slip_builder_targets():
    """The targets offered, and what each is actually worth."""
    from leagues.builder_v2 import V2_HORIZONS
    from leagues.slip_builder import (
        HORIZONS,
        MAX_LEGS,
        MAX_TARGET,
        MIN_TARGET,
        TARGETS,
    )

    return {
        "status": "success",
        "targets": TARGETS,
        "min": MIN_TARGET,
        "max": MAX_TARGET,
        "max_legs": MAX_LEGS,
        "horizons": sorted(V2_HORIZONS),
        "legacy_horizons": sorted(HORIZONS),
        "note": (
            "The return shown is the model's joint hit probability "
            "multiplied by the displayed odds. It is an estimate, not a guarantee."
        ),
    }


@router.post("/slip-builder/v2/candidates")
async def slip_builder_v2_candidates(request: BuilderV2Filters):
    """Browse the current approved V2 candidate board without rebuilding providers."""
    import asyncio
    import os
    from leagues.builder_v2 import list_candidates

    if os.getenv("BUILDER_ENGINE", "v2").strip().lower() != "v2":
        return {"status": "unavailable", "reason": "builder_mode_disabled", "retryable": False}
    return await asyncio.to_thread(
        list_candidates,
        _builder_v2_payload(request),
    )


@router.post("/slip-builder/v2/generate")
async def slip_builder_v2_generate(request: BuilderV2Request):
    """Build target/count/strongest V2 slips from the prepared trusted board."""
    import asyncio
    import json
    import time as _t

    from leagues.builder_v2 import generate_v2

    request_id = str(uuid.uuid4())
    payload = _builder_v2_payload(request)

    if request.build_another:
        payload["_build_another"] = True

        if request.anonymous_id:
            try:
                from leagues.ticket_history import recent_exposure
                payload["_recent_exposure"] = await asyncio.to_thread(
                    recent_exposure,
                    request.anonymous_id,
                )
            except Exception as exc:
                # Diversification is optional context. A history failure must
                # never break an otherwise valid Builder request.
                logger.warning(
                    "builder_recent_exposure_failed error_type=%s",
                    type(exc).__name__,
                )
                payload["_recent_exposure"] = {
                    "history_ticket_count": 0,
                    "exact_selection_ids": [],
                    "recent_fixture_ids": [],
                    "team_counts": {},
                    "league_counts": {},
                    "market_counts": {},
                }

    import os
    engine = os.getenv("BUILDER_ENGINE", "v2").strip().lower()
    if engine == "legacy":
        if request.mode != "target_odds" or request.horizon not in {"today", "7_days"} or any(
            payload.get(key) for key in (
                "markets", "include_leagues", "exclude_leagues",
                "exclude_fixture_ids", "exclude_team_ids", "min_odds", "max_odds",
                "min_probability",
            )
        ) or request.min_trust_grade != "B" or not request.require_bookable:
            return {"status": "unavailable", "reason": "builder_mode_disabled", "retryable": False}
        return await _legacy_slip_builder_generate(
            request.target_odds or 0,
            "week" if request.horizon == "7_days" else "today",
            request.refresh,
        )
    if engine != "v2":
        return {"status": "unavailable", "reason": "builder_engine_disabled", "retryable": False}
    started = _t.perf_counter()

    if request.mode == "target_odds":
        from leagues.daily_feed import _publish_date
        from leagues.engine import prepared_board_status

        # Target Odds is cached because its optimizer is more expensive than
        # the structural Builder modes. The prepared-board identity must be
        # part of that cache key, though: after a board refresh we must never
        # keep serving a combination selected from the previous fixture/price
        # snapshot merely because the request payload and WAT date are equal.
        cache_board = prepared_board_status(days_ahead=7)
        cache_board_identity = (
            cache_board.get("board_snapshot_id"),
            cache_board.get("generated_at"),
            int(cache_board.get("evaluated_fixture_count") or 0),
        )

        cache_key = (
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ),
            _publish_date(),
            cache_board_identity,
        )
        hit = (
            None
            if request.build_another
            else _V2_TARGET_CACHE.get(cache_key)
        )
        if (
            hit and not request.refresh
            and (_t.time() - hit["ts"]) < _SLIP_TTL
            and _cached_target_result_is_reusable(hit["result"])
        ):
            result = {**hit["result"], "cached": True}
        else:
            lock = _V2_TARGET_LOCKS.setdefault(
                cache_key,
                asyncio.Lock(),
            )
            async with lock:
                hit = (
            None
            if request.build_another
            else _V2_TARGET_CACHE.get(cache_key)
        )
                if (
                    hit and not request.refresh
                    and (_t.time() - hit["ts"]) < _SLIP_TTL
                    and _cached_target_result_is_reusable(hit["result"])
                ):
                    result = {**hit["result"], "cached": True}
                else:
                    result = await asyncio.to_thread(
                        generate_v2,
                        payload,
                    )
                    if (
                        not request.build_another
                        and result.get("status") == "success"
                        and _cached_target_result_is_reusable(result)
                    ):
                        _V2_TARGET_CACHE[cache_key] = {
                            "result": result,
                            "ts": _t.time(),
                        }
                        _prune_builder_results(
                            _V2_TARGET_CACHE, _V2_TARGET_LOCKS, _t.time(),
                        )
                    result = {**result, "cached": False}
    else:
        result = await asyncio.to_thread(
            generate_v2,
            payload,
        )

    if (
        request.mode == "target_odds"
        and result.get("status") == "success"
        and result.get("games")
    ):
        result = await asyncio.to_thread(_start_builder_revision,
            float(request.target_odds or result.get("odds") or 2),
            request.horizon,
            result,
        )

    result["request_id"] = request_id
    await asyncio.to_thread(
        _record_v2_result,
        _builder_v2_persistence_payload(request, payload),
        result,
        started,
    )
    return result


@router.post("/slip-builder/v2/manual")
async def slip_builder_v2_manual(request: BuilderV2ManualRequest):
    """Book only the exact approved selection IDs chosen by the user."""
    import asyncio
    import os
    import time
    from leagues.builder_v2 import manual_build

    if os.getenv("BUILDER_ENGINE", "v2").strip().lower() != "v2":
        return {"status": "unavailable", "reason": "builder_mode_disabled", "retryable": False}
    started = time.perf_counter()
    request_id = str(uuid.uuid4())
    payload = _builder_v2_payload(request)
    result = await asyncio.to_thread(
        manual_build,
        payload,
    )
    result["request_id"] = request_id
    persistence_payload = _builder_v2_persistence_payload(request, payload)
    persistence_payload["mode"] = "manual"
    await asyncio.to_thread(
        _record_v2_result,
        persistence_payload,
        result,
        started,
    )
    return result

@router.post("/slip-builder/generate")
async def slip_builder_generate(target: float, horizon: str = "week",
                                refresh: bool = False):
    """Deprecated query contract; selection and cache belong to V2."""
    return await slip_builder_v2_generate(BuilderV2Request(
        mode="target_odds", target_odds=target,
        horizon="7_days" if horizon == "week" else horizon,
        refresh=refresh,
    ))


async def _legacy_slip_builder_generate(target: float, horizon: str = "week",
                                       refresh: bool = False):
    """Build a slip to a requested multiplier and book it."""
    import time as _t
    from database import log_pool_exception, log_pool_status
    from utils.runtime_metrics import log_runtime_memory

    # Audit/request identity is deliberately distinct from the persisted
    # revision-chain ID returned by ``create_initial_run``.
    request_id = str(uuid.uuid4())

    log_pool_status(
        "builder_start", request_id=request_id,
        target=round(float(target), 2),
        horizon=horizon,
        refresh=bool(refresh),
    )
    log_runtime_memory(
        "builder_start", target=round(float(target), 2), horizon=horizon,
        refresh=bool(refresh),
    )
    from leagues.daily_feed import _publish_date
    from leagues.engine import prepared_board_status, start_prepared_board_refresh
    from leagues.slip_builder import HORIZONS, MAX_TARGET, MIN_TARGET, generate

    if not (MIN_TARGET <= float(target) <= MAX_TARGET):
        return {
            "status": "error",
            "reason": (
                f"Choose a target between {MIN_TARGET:g} and {MAX_TARGET:g}."
            ),
        }
    if horizon not in HORIZONS:
        return {
            "status": "error",
            "reason": f"Horizon must be one of {sorted(HORIZONS)}.",
        }

    key = (round(float(target), 2), horizon, _publish_date())
    hit = _SLIP_CACHE.get(key)
    if (hit and not refresh and (_t.time() - hit["ts"]) < _SLIP_TTL
            and _cached_slip_is_placeable(hit["result"])):
        response = _start_builder_revision(
            target, horizon, {**hit["result"], "cached": True}
        )
        response["request_id"] = request_id
        try:
            from leagues.builder_runs import record_run
            record_run(target, horizon, refresh, response, cached=True,
                       request_id=request_id)
        except Exception as exc:
            logger.warning(f"Builder run audit failed: {exc}")
        _log_builder_board(response.get("builder_run_id", request_id), target, horizon, response)
        log_pool_status(
            "builder_end", target=key[0], horizon=horizon,
            status=response.get("status"), cached=True,
        )
        log_runtime_memory(
            "builder_end", target=key[0], horizon=horizon,
            status=response.get("status"), cached=True,
        )
        return response

    board = prepared_board_status(days_ahead=7)
    if not board.get("ready"):
        from leagues.history_readiness import status as history_status
        from leagues.engine import start_history_prewarm
        history = history_status()
        if not history["usable"]:
            start_history_prewarm(request_triggered=True)
            return {
                "status": "unavailable", "reason": "history_not_ready",
                "retryable": True, "history": history,
                "requested_target": round(float(target), 2),
                "horizon": horizon, "request_id": request_id,
            }
        refresh_started = start_prepared_board_refresh(
            days_ahead=7, force=True
        )
        response = {
            "status": "unavailable",
            "reason": "board_refreshing",
            "retryable": True,
            "refresh_started": refresh_started,
            "board": board,
            "requested_target": round(float(target), 2),
            "horizon": horizon,
            "request_id": request_id,
        }
        log_pool_status(
            "builder_end", target=key[0], horizon=horizon,
            status="board_refreshing", cached=False,
        )
        log_runtime_memory(
            "builder_end", target=key[0], horizon=horizon,
            status="board_refreshing", cached=False,
        )
        _log_builder_board(request_id, target, horizon, response)
        return response
    if board.get("stale"):
        # Keep serving the last safe evaluated board while a single background
        # refresh replaces it. A provider refresh must not block this request.
        board["refresh_started"] = start_prepared_board_refresh(
            days_ahead=7, force=True
        )

    # Coalesce identical work. The model/board/booking functions are blocking,
    # so move them off the event loop while one coroutine owns this key.
    import asyncio
    lock = _SLIP_LOCKS.setdefault(key, asyncio.Lock())
    try:
        async with lock:
            hit = _SLIP_CACHE.get(key)
            if (hit and not refresh and (_t.time() - hit["ts"]) < _SLIP_TTL
                    and _cached_slip_is_placeable(hit["result"])):
                result = _start_builder_revision(
                    target, horizon, {**hit["result"], "cached": True}
                )
                result["request_id"] = request_id
                try:
                    from leagues.builder_runs import record_run
                    record_run(target, horizon, refresh, result, cached=True,
                               request_id=request_id)
                except Exception as exc:
                    logger.warning(f"Builder run audit failed: {exc}")
                _log_builder_board(result.get("builder_run_id", request_id), target, horizon, result)
                log_pool_status(
                    "builder_end", target=key[0], horizon=horizon,
                    status=result.get("status"), cached=True,
                )
                log_runtime_memory(
                    "builder_end", target=key[0], horizon=horizon,
                    status=result.get("status"), cached=True,
                )
                return result
            # `refresh` bypasses only the finished-slip cache. Public clicks
            # consume the already prepared board and never force a full
            # provider/model/SportyBet refresh in the request path.
            result = await asyncio.to_thread(
                generate, target, horizon=horizon, force=False
            )
            if result.get("status") == "success":
                _SLIP_CACHE[key] = {"result": result, "ts": _t.time()}
                _prune_builder_results(_SLIP_CACHE, _SLIP_LOCKS, _t.time())
    except Exception as e:
        logger.error(f"Slip build failed: {e}", exc_info=True)
        log_pool_exception(
            "builder_pool_timeout", e, target=key[0], horizon=horizon,
        )
        log_pool_status(
            "builder_error", level=logging.ERROR, target=key[0],
            horizon=horizon, error_type=type(e).__name__,
        )
        log_runtime_memory(
            "builder_error", level=logging.ERROR, target=key[0],
            horizon=horizon, error_type=type(e).__name__,
        )
        try:
            from leagues.builder_runs import record_run
            record_run(target, horizon, refresh,
                       {"status": "error", "reason": type(e).__name__},
                       request_id=request_id)
        except Exception as exc:
            logger.warning(f"Builder run audit failed: {exc}")
        raise HTTPException(500, str(e))

    response = _start_builder_revision(
        target, horizon, {**result, "cached": False}
    )
    response["request_id"] = request_id
    try:
        from leagues.builder_runs import record_run
        record_run(target, horizon, refresh, response,
                   request_id=request_id)
    except Exception as exc:
        logger.warning(f"Builder run audit failed: {exc}")
    _log_builder_board(response.get("builder_run_id", request_id), target, horizon, response)
    log_pool_status(
        "builder_end", target=key[0], horizon=horizon,
        status=response.get("status"), cached=False,
    )
    log_runtime_memory(
        "builder_end", target=key[0], horizon=horizon,
        status=response.get("status"), cached=False,
    )
    return response


def _public_prepared_board(horizon: int) -> tuple[list[dict], list[dict], dict]:
    """A public read never starts provider/model work on its request thread."""
    from leagues.engine import (prepared_board, start_history_prewarm,
                                start_prepared_board_refresh)

    # A single scheduled seven-day snapshot covers all public horizons.
    picks, fixtures, board = prepared_board(horizon)
    if board.get("ready") and fixtures:
        if board.get("stale"):
            board["refresh_started"] = start_prepared_board_refresh(
                days_ahead=7, force=True)
        return picks, fixtures, board

    from leagues.history_readiness import status as history_status
    history = history_status()
    if not history["usable"]:
        started = start_history_prewarm(request_triggered=True)
        reason = "history_not_ready"
    else:
        started = start_prepared_board_refresh(days_ahead=7, force=True)
        reason = "board_refreshing"
    raise HTTPException(503, {
        "reason": reason, "retryable": True, "refresh_started": started,
        "board": board, "history": history,
    })


@router.get("/recommendations")
def get_fixture_recommendations(date: str | None = None,
                                      days_ahead: int = 3):
    """One ranked football opinion per analysed fixture on a WAT date."""
    try:
        from leagues.recommendation_board import build_recommendation_board

        horizon = max(1, min(7, days_ahead))
        picks, fixtures, board = _public_prepared_board(horizon)
        result = build_recommendation_board(picks, fixtures, date=date)
        result["board"] = board
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Fixture recommendation board failed: %s", e,
                     exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/recommendations/diagnostics",
            dependencies=[Depends(require_api_key)])
async def recommendation_diagnostics(date: str | None = None):
    """Internal board and Daily portfolio explanation without raw model data."""
    try:
        from leagues.daily_feed import build_daily_accumulators, _publish_date
        from leagues.recommendation_board import build_recommendation_board

        picks, fixtures, prepared = _public_prepared_board(4)
        board = build_recommendation_board(picks, fixtures, date=date)
        daily = build_daily_accumulators(preview={
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "target_wat_date": date or _publish_date(),
            "picks": picks, "fixtures": fixtures,
        })
        accumulators = (daily or {}).get("accumulators") or {}
        tiers = {}
        for name in ("banker", "2_odds", "5_odds", "10_odds", "rollover"):
            tier = accumulators.get(name) or {}
            tiers[name] = {
                "selected": bool(tier.get("selected")),
                "result_status": tier.get("result_status"),
                "achieved_odds": tier.get("total_odds"),
                "legs": len(tier.get("games") or []),
                "joint_probability": tier.get("hit_probability"),
                "reason": tier.get("reason"),
            }
        return {
            "status": "success",
            "date": board["date"],
            "board_summary": board["summary"],
            "market_distribution": board["market_distribution"],
            "board": prepared,
            "daily_tiers": tiers,
            "portfolio": accumulators.get("_portfolio") or {},
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Recommendation diagnostics failed: %s", e,
                     exc_info=True)
        raise HTTPException(500, str(e))

@router.post("/slip-builder/{run_id}/revise")
async def slip_builder_revise(run_id: str, request: BuilderRevisionRequest):
    """Apply one intent-only edit to the latest immutable Builder revision."""
    import asyncio
    from database import log_pool_exception, log_pool_status
    from leagues import builder_revisions
    from leagues.builder_editor import revise
    import time as _t

    lock = _BUILDER_REVISION_LOCKS.setdefault(run_id, asyncio.Lock())
    started_at = _t.perf_counter()
    safe_request_id = request.request_id[:12]
    log_pool_status(
        "builder_revision_start", run_id=run_id[:8],
        revision=request.revision, action=request.action,
        request_id=safe_request_id,
    )
    logger.info(
        "builder_revision_start run_id=%s request_id=%s revision=%s action=%s",
        run_id[:8], safe_request_id, request.revision, request.action,
    )
    try:
        async with lock:
            return await asyncio.to_thread(
                revise,
                run_id=run_id,
                edit_token=request.edit_token,
                revision=request.revision,
                request_id=request.request_id,
                action=request.action,
                selection_id=request.selection_id,
                fixture_id=request.fixture_id,
                target=request.target,
            )
    except builder_revisions.StaleBuilderRevision as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "stale_revision",
                    "latest_revision": exc.latest_revision},
        )
    except builder_revisions.BuilderRunNotFound:
        raise HTTPException(status_code=404, detail="builder_run_not_found")
    except builder_revisions.BuilderRunForbidden:
        raise HTTPException(status_code=403, detail="builder_run_forbidden")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log_pool_exception(
            "builder_revision_pool_timeout", exc,
            run_id=run_id[:8], action=request.action,
        )
        logger.error("Builder revision failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="builder_revision_failed")
    finally:
        duration_ms = round((_t.perf_counter() - started_at) * 1000)
        log_pool_status(
            "builder_revision_end", run_id=run_id[:8],
            revision=request.revision, action=request.action,
            request_id=safe_request_id, duration_ms=duration_ms,
        )
        logger.info(
            "builder_revision_end run_id=%s request_id=%s revision=%s "
            "action=%s duration_ms=%s",
            run_id[:8], safe_request_id, request.revision, request.action,
            duration_ms,
        )


@router.get("/notification-log")
async def get_notification_log(limit: int = 40):
    """Which alerts were sent, when, and on which channel.

    There was no record at all before: duplicates were neither preventable nor
    visible after the fact, so "did this go out twice?" could only be answered
    by whoever received it.
    """
    from services.push_notification_service import delivery_log
    rows = delivery_log(limit=limit)
    return {"status": "success", "count": len(rows), "deliveries": rows}


@router.get("/bookmaker-status")
async def bookmaker_status():
    """The price feed behind the card: coverage and the margins it is seeing."""
    from leagues import sportybet
    return {"status": "success", "sportybet": sportybet.board_status()}


@router.get("/results")
def get_results(days: int = 30, category: str | None = None):
    """Settled history for every category, not just the rollover chain.

    Returns each published slip with its legs and outcome, plus a per-category
    performance summary (win rate, profit and ROI at level 1-unit stakes).
    """
    try:
        from leagues.picks_db import (
            get_history,
            performance_summary,
            product_performance_summary,
        )
        from leagues.rollover_db import history as rollover_history
        history = get_history(limit_days=days, category=category)

        by_date: dict[str, dict] = {}
        for slip in history:
            by_date.setdefault(slip["date"], {})[slip["category"]] = slip

        summary = performance_summary(
            limit_days=days
        )

        product_record = (
            product_performance_summary(
                limit_days=days
            )
        )

        # Totals split by unit. Over 1.5 is a list of singles and is counted in
        # individual picks; every other tier is one slip. Adding them into a
        # single "settled slips" figure — which the results page was doing —
        # reports ten separate bets as ten slips and overstates the count.
        totals = {
            "slips": {"won": 0, "lost": 0, "settled": 0,
                      "staked": 0.0, "returned": 0.0},
            "picks": {"won": 0, "lost": 0, "settled": 0,
                      "staked": 0.0, "returned": 0.0},
        }
        for cat in summary.values():
            bucket = totals["picks"] if cat.get("unit") == "pick" else totals["slips"]
            for key in ("won", "lost", "settled", "staked", "returned"):
                bucket[key] += cat.get(key, 0)
        for bucket in totals.values():
            n = bucket["settled"]
            bucket["win_rate"] = round(bucket["won"] / n, 4) if n else None
            bucket["profit"] = round(bucket["returned"] - bucket["staked"], 2)
            bucket["roi"] = (round(bucket["profit"] / bucket["staked"], 4)
                             if bucket["staked"] else None)
        bookable = {"settled": 0, "won": 0, "lost": 0,
                    "staked": 0.0, "returned": 0.0}
        for cat in summary.values():
            if cat.get("unit") != "slip":
                continue
            record = cat.get("bookable_record") or {}
            for key in bookable:
                bookable[key] += record.get(key, 0)
        bookable["profit"] = round(bookable["returned"] - bookable["staked"], 2)
        bookable["roi"] = (
            round(bookable["profit"] / bookable["staked"], 4)
            if bookable["staked"] else None
        )
        bookable["coverage"] = (
            round(bookable["settled"] / totals["slips"]["settled"], 4)
            if totals["slips"]["settled"] else 0.0
        )
        totals["slips"]["published_record"] = {
            key: totals["slips"][key]
            for key in ("settled", "won", "lost", "staked", "returned",
                        "profit", "roi")
        }
        totals["slips"]["bookable_record"] = bookable
        totals["combined_profit"] = round(
            totals["slips"]["profit"]
            + totals["picks"]["profit"],
            2,
        )

        totals["products"] = {
            key:
                product_record.get(key)
            for key in (
                "accounting_version",
                "unit",
                "won",
                "lost",
                "void",
                "pending",
                "settled",
                "win_rate",
                "oldest_pending_date",
            )
        }

        return {
            "status": "success",
            "days": days,
            "summary":
                summary,

            "product_record":
                product_record,

            "totals":
                totals,
            "history": history,
            "rollover_history": rollover_history(limit_days=days),
            "by_date": by_date,
        }
    except Exception as e:
        logger.error(f"Results fetch failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/runtime-status")
async def get_runtime_status():
    """Read-only runtime state; never triggers generation."""

    import os

    from utils.process_roles import (
        resolve_process_role,
        role_ownership,
    )

    environment = (
        os.getenv(
            "ENVIRONMENT",
            "development",
        )
        .strip()
        .lower()
    )

    default_background = (
        "true"
        if environment == "production"
        else "false"
    )

    background_jobs = (
        os.getenv(
            "ENABLE_BACKGROUND_JOBS",
            default_background,
        )
        .strip()
        .lower()
        in {
            "1",
            "true",
            "yes",
            "on",
        }
    )

    role = resolve_process_role(
        background_jobs,
        os.getenv(
            "BETSIGHTLY_PROCESS_ROLE",
            "",
        ),
    )

    ownership = role_ownership(
        role,
        background_jobs,
    )

    try:
        from leagues.results_checker import (
            settlement_status,
        )

        settlement = (
            settlement_status()
        )

    except Exception as exc:
        settlement = {
            "error":
                type(exc).__name__,
        }

    try:
        from leagues.engine import (
            prepared_board_status,
        )

        board = (
            prepared_board_status(
                days_ahead=7
            )
        )

        prepared = {
            "ready":
                bool(
                    board.get("ready")
                ),

            "degraded":
                bool(
                    board.get(
                        "degraded"
                    )
                ),

            "complete":
                bool(
                    board.get(
                        "complete"
                    )
                ),

            "age_seconds":
                board.get(
                    "age_seconds"
                ),

            "source":
                board.get(
                    "source"
                ),

            "provider":
                board.get(
                    "provider"
                ),
        }

    except Exception as exc:
        prepared = {
            "ready":
                False,

            "error":
                type(exc).__name__,
        }

    try:
        from leagues.scheduler import (
            last_runs,
        )

        recent_runs = last_runs(
            limit=3
        )

    except Exception as exc:
        recent_runs = [{
            "error":
                type(exc).__name__,
        }]

    try:
        from services.api_football_gateway import (
            quota_status,
        )

        api_football = (
            quota_status()
        )

    except Exception as exc:
        api_football = {
            "blocked":
                True,

            "block_reason":
                "status_error",

            "error":
                type(exc).__name__,
        }

    try:
        from leagues.runtime_heartbeat import (
            status as heartbeat_status,
        )

        background_process = (
            heartbeat_status(
                role="worker",
                stale_after_seconds=120,
            )
        )

    except Exception as exc:
        background_process = {
            "active":
                False,

            "error":
                type(exc).__name__,
        }

    return {
        "status":
            "success",

        "api_football":
            api_football,

        "background_process":
            background_process,

        "process": {
            "environment":
                environment,

            "role":
                role,

            "background_jobs":
                background_jobs,

            "owns_scheduler":
                ownership[
                    "scheduler"
                ],

            "owns_settlement":
                ownership[
                    "settlement"
                ],

            "owns_telegram_polling":
                ownership[
                    "telegram"
                ],
        },

        "settlement":
            settlement,

        "prepared_board":
            prepared,

        "recent_daily_runs":
            recent_runs,
    }


@router.get("/performance")
async def get_performance(days: int = 90):
    """Win rate, profit and ROI per category over the requested window."""
    try:
        from leagues.picks_db import (
            current_policy_performance, performance_summary,
        )
        return {
            "status": "success", "days": days,
            "summary": performance_summary(limit_days=days),
            "current_policy": current_policy_performance(limit_days=days),
        }
    except Exception as e:
        logger.error(f"Performance fetch failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/builder-performance")
async def get_builder_performance(days: int = 90):
    """Settlement, calibration and ROI for unique immutable Builder sets."""
    try:
        from leagues.builder_runs import performance
        return {"status": "success", "days": days, **performance(days)}
    except Exception as exc:
        logger.error(f"Builder performance fetch failed: {exc}", exc_info=True)
        raise HTTPException(500, str(exc))


@router.get(
    "/v2-closeout",
    dependencies=[Depends(require_api_key)],
)
async def get_v2_closeout(days: int = 90):
    """Read-only acceptance report for the original V2 scope."""
    try:
        from leagues.v2_closeout import report
        return report(
            days=max(
                1,
                min(
                    365,
                    int(days),
                ),
            )
        )
    except Exception as exc:
        logger.error(
            "V2 closeout report failed: %s",
            exc,
            exc_info=True,
        )
        raise HTTPException(
            500,
            str(exc),
        )


@router.post("/backfill-legs", dependencies=[Depends(require_api_key)])
async def trigger_leg_backfill(days: int = 30, dry_run: bool = True,
                               start_date: str | None = None,
                               end_date: str | None = None):
    """Review a bounded historical window; only an explicit apply writes legs."""
    try:
        from leagues.results_checker import backfill_leg_status
        return {"status": "success", **backfill_leg_status(
            limit_days=days, dry_run=dry_run,
            start_date=start_date, end_date=end_date)}
    except Exception as e:
        logger.error(f"Leg backfill failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.post("/reconcile-published-slips", dependencies=[Depends(require_api_key)])
async def reconcile_historical_published_slips(
        start_date: str = "2026-09-15", end_date: str = "2026-09-24",
        dry_run: bool = True):
    """Read-only historical settlement comparison for staging/admin review."""
    if not dry_run:
        raise HTTPException(400, "published-slip reconciliation is read-only; dry_run must be true")
    try:
        from leagues.results_checker import reconcile_published_slips
        return {"status": "success", **reconcile_published_slips(
            start_date=start_date, end_date=end_date, dry_run=True)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.error("Published-slip reconciliation failed: %s", exc, exc_info=True)
        raise HTTPException(500, str(exc))


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


@router.post("/restart", dependencies=[Depends(require_api_key)])
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


@router.post("/repair-void-slips", dependencies=[Depends(require_api_key)])
async def repair_void_slips():
    """Restate slips recorded as won whose every leg actually voided.

    The old rule was "all legs won or void", so a slip where every leg voided
    counted as a win. A void returns the stake — it wins nothing. The rule is
    fixed going forward; this corrects the records already written.
    """
    try:
        import json as _json
        from database import SessionLocal
        from leagues.picks_db import PublishedSlip, ensure_table

        ensure_table()
        fixed = []
        db = SessionLocal()
        try:
            for r in db.query(PublishedSlip).filter(
                    PublishedSlip.status == "won").all():
                legs = _json.loads(r.picks or "[]")
                if not legs:
                    continue
                states = [l.get("status") for l in legs]
                if all(st == "void" for st in states):
                    fixed.append({"date": r.date, "category": r.category,
                                  "legs": len(legs)})
                    r.status = "void"
            db.commit()
        finally:
            db.close()
        return {"status": "success", "restated": fixed, "count": len(fixed)}
    except Exception as e:
        logger.error(f"repair-void-slips failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.post("/repair-singles", dependencies=[Depends(require_api_key)])
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


@router.post("/rebuild-rollover", dependencies=[Depends(require_api_key)])
async def rebuild_rollover():
    """Rebuild the unsettled part of the rollover chain.

    The chain used to aim at ~1.9x a day, which forced two legs around 65% and
    left each day landing about 43% of the time. A ten-day chain needs every
    day, so that design completed 0.43^10 — two chances in ten thousand — and
    it duly went 0 for 4 with every loss caused by the second leg. The current
    challenge is three days, with each day constrained to 2x–3x and no more
    than six evidence-backed picks.

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


@router.post("/repair-card", dependencies=[Depends(require_api_key)])
async def repair_card():
    """Safely recover genuinely empty tiers from the prepared board.

    This endpoint intentionally does not force a prediction rebuild or use the
    legacy payload-only fill helper.  Recovery is transactional: card, slip,
    booking and provenance either all commit together or none do.
    """
    try:
        from leagues import daily_feed
        result = daily_feed.recover_today_empty_tiers()
        if result.get("status") == "COMPLETE":
            # Only discard the response cache after a transactional recovery
            # succeeded; a failed booking must leave the locked card untouched.
            if any(value.get("status") == "RECOVERED"
                   for value in result.get("tiers", {}).values()):
                daily_feed._accum_cache.update({"result": None, "ts": 0.0})
            return {"status": "success", "publish_date": daily_feed._publish_date(), **result}
        return {"status": "unavailable", **result}
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


@router.get("/odds-shop-status")
async def odds_shop_status():
    """Whether multi-book price shopping is actually working.

    It fails silently by design — a missing key returns {} and a non-200
    returns [] — so a broken shop looks exactly like a quiet day. This reports
    the real HTTP status instead of swallowing it.
    """
    try:
        import os
        import requests as _rq
        from leagues.odds_shop import (
            CACHE_PATH, SLUG_TO_ODDS_KEY, budget_status,
        )

        key = os.getenv("ODDS_API_KEY", "").strip()
        out = {
            "key_configured": bool(key),
            "budget": budget_status(),
            "mapped_leagues": len(SLUG_TO_ODDS_KEY),
            "cache_exists": CACHE_PATH.exists(),
        }
        if CACHE_PATH.exists():
            import json as _json
            import time as _time
            try:
                blob = _json.loads(CACHE_PATH.read_text())
                out["cache_age_hours"] = round(
                    (_time.time() - blob.get("ts", 0)) / 3600, 1)
                out["cache_fixtures"] = len(blob.get("data", {}))
            except Exception:
                out["cache_age_hours"] = None

        if not key:
            out["verdict"] = "ODDS_API_KEY is not set — no shopping happens at all."
            return {"status": "success", **out}

        # One real probe so the actual failure surfaces.
        resp = _rq.get(
            "https://api.the-odds-api.com/v4/sports/soccer_epl/odds",
            params={"apiKey": key, "regions": "eu,uk",
                    "markets": "h2h", "oddsFormat": "decimal"},
            timeout=25,
        )
        out["probe_http_status"] = resp.status_code
        out["quota_remaining"] = resp.headers.get("x-requests-remaining")
        out["quota_used"] = resp.headers.get("x-requests-used")
        if resp.status_code == 200:
            events = resp.json() or []
            out["probe_events"] = len(events)
            out["verdict"] = (
                f"Working. {len(events)} EPL fixtures priced, "
                f"{out['quota_remaining']} credits left."
            )
        else:
            body = resp.text[:300]
            out["probe_error"] = body
            out["verdict"] = f"The Odds API rejected the request: HTTP {resp.status_code}."
        return {"status": "success", **out}
    except Exception as e:
        logger.error(f"odds shop status failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/fixtures")
async def get_fixtures_list(days_ahead: int = 3):
    """Upcoming fixtures with prices and the leagues currently in play."""
    try:
        horizon = max(1, min(days_ahead, 7))
        _, fixtures, board = _public_prepared_board(horizon)
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
            "board": board,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Fixtures fetch failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/competition-coverage", dependencies=[Depends(require_api_key)])
async def competition_coverage(days_ahead: int = 7, refresh: bool = False):
    """Internal health report for every configured or explicitly rejected feed."""
    try:
        if refresh:
            environment = os.getenv(
                "ENVIRONMENT", ""
            ).strip().lower()

            role = os.getenv(
                "BETSIGHTLY_PROCESS_ROLE", ""
            ).strip().lower()

            if (
                environment in {"production", "prod"}
                or (
                    environment == "staging"
                    and role == "web"
                )
            ):
                raise HTTPException(409, {
                    "reason": "board_refresh_requires_worker",
                    "retryable": False,
                })
        from collections import Counter
        from leagues.base_rates import get_base_rates, rates_for
        from leagues.competition_registry import (
            UNAVAILABLE_COMPETITIONS, enabled_competitions,
        )
        from leagues.engine import run_pipeline
        from leagues.espn_source import fetch_health
        from leagues.elo_engine import cached_ratings, get_ratings

        horizon = max(1, min(days_ahead, 14))
        if refresh:
            _, fixtures = run_pipeline(days_ahead=horizon, force=True)
        else:
            _, fixtures, _ = _public_prepared_board(horizon)
        base_rates = get_base_rates(allow_refresh=refresh)
        ratings = get_ratings(force=True) if refresh else cached_ratings()
        provider_health = fetch_health()
        by_slug: dict[str, list[dict]] = {}
        for fixture in fixtures:
            by_slug.setdefault(fixture.get("league_slug", ""), []).append(fixture)

        rows = []
        for slug, meta in enabled_competitions().items():
            current = by_slug.get(slug, [])
            rate = rates_for(slug, base_rates)
            rating_pool = ("__international__" if meta.team_type == "NATIONAL"
                           else "__continental_club__" if meta.competition_type == "CONTINENTAL_CLUB"
                           else slug)
            market_counts = Counter(
                "priced" if (fixture.get("odds") or {}).get("implied") else "unpriced"
                for fixture in current
            )
            health = provider_health.get(slug) or {}
            rows.append({
                **meta.public_dict(),
                "configured": True,
                "provider_active": health.get("provider_active"),
                "scheduled_fixture_count": len(current),
                "priced_fixture_count": market_counts["priced"],
                "sportybet_matched_count": sum(
                    1 for fixture in current
                    if (fixture.get("odds") or {}).get("sportybet_event_id")
                ),
                "historical_sample": int((base_rates.get(slug) or {}).get("matches") or 0),
                "base_rate_source": rate.get("base_rate_source", "global_default"),
                "history_fallback": (
                    (base_rates.get("_history_fallback") or {}).get(slug)
                ),
                "rating_coverage": len(ratings.get(rating_pool) or {}),
                "last_successful_fetch": health.get("last_successful_fetch"),
                "error": health.get("error"),
            })
        for slug, reason in UNAVAILABLE_COMPETITIONS.items():
            rows.append({
                "slug": slug, "display_name": slug, "configured": False,
                "enabled": False, "provider_active": False,
                "scheduled_fixture_count": 0, "priced_fixture_count": 0,
                "sportybet_matched_count": 0, "historical_sample": 0,
                "base_rate_source": None, "rating_coverage": 0,
                "last_successful_fetch": None, "error": reason,
            })
        return {"status": "success", "competitions": rows}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"competition coverage failed: {e}", exc_info=True)
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
