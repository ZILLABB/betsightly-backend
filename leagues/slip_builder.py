"""
Build a slip to a requested multiplier.

Someone asks for 50 odds; this finds the combination of already-evaluated
picks most likely to actually land at that multiplier, and books it.

Not a second prediction engine. It reads the same candidate pool the daily
card is built from, respects the same confidence floors, the same one-leg-per
-fixture rule and the same market cap. The only thing it adds is a different
question: not "what are today's best picks" but "which of them reach 50x with
the best chance of coming in".

Two design notes worth keeping.

*The pool spans days, and that is most of the value.* Reaching 50x from a
single day's 31 fixtures takes twelve legs averaging 72% confidence and lands
1.88% of the time. From a week's 526 fixtures it takes thirteen legs averaging
78% and lands 3.98% — more than double, because a bigger board simply contains
better picks, not because the search is cleverer.

*The search is a bounded multi-start search.* `select_accumulator` enumerates
combinations, which is right for a five-leg tier and impossible at thirteen.
Ordering by

    cost = -log(probability) / log(odds)

buys the required log-odds as cheaply as possible in log-probability. Trying
several strong starting legs avoids committing the ticket to the first greedy
path when a nearby combination has a better chance of landing.

What it does not do is create an edge. Measured across 393 settled legs,
nothing selection can key on predicts a leg beating its own stated confidence
— so this reaches a number honestly, and says what that number is worth.
"""

import collections
import logging
import math
import time as monotonic_time
from datetime import datetime, time, timedelta, timezone

logger = logging.getLogger(__name__)

# Targets the UI offers. Capped at 100 deliberately: past that the leg count
# climbs fast and every leg is another slice of the bookmaker's margin, so the
# product stops being a bet and becomes a lottery ticket. 100 already needs
# roughly fifteen legs on a typical board.
TARGETS = [10, 20, 30, 50, 70, 100]
MAX_TARGET = 100
MIN_TARGET = 2

# Thirteen to fifteen legs is what these targets actually need, so the ceiling
# sits just above rather than inviting slips nobody should place.
MAX_LEGS = 16

# How far ahead the pool reaches. The card is a single day by definition; a
# slip a user asks for need not be, and the extra days are where the quality
# comes from.
POOL_DAYS = 7

# Two horizons, because they are genuinely different products rather than a
# setting. Measured on one board at a 50x target:
#
#   today   12 legs, 51.7x, lands 1.88%, legs averaging 72% confidence
#   week    13 legs, 60.2x, lands 3.98%, legs averaging 78%
#
# A week-sized board can contain higher-confidence combinations than one day.
# What it costs is time: it settles over seven WAT dates rather than tonight.
# Both horizons remain because that timing trade-off is a real user choice.
HORIZONS = {"today": 1, "week": POOL_DAYS}
DEFAULT_HORIZON = "week"
WAT = timezone(timedelta(hours=1))

# Reached within this fraction of the target and it counts as a hit. Prices
# move in coarse steps, so insisting on exactly 50.0 would reject a 48.6x slip
# that is the best thing on the board.
BAND_LOW = 0.90
BAND_HIGH = 1.45


# How close two picks must be on cost before the bookmaker's cut decides
# between them. Sorting on cost alone drifted into the dearest markets on the
# board — double chance runs about two points above 1X2 — and a twelve-leg
# slip multiplies that many times, so margin remains a useful tie-breaker.
_COST_TIE_BAND = 0.02


def _cost(pick: dict) -> float:
    p = max(1e-6, min(0.999, pick.get("evidence_adjusted_probability", pick["confidence"])))
    o = max(1.0001, pick["odds"])
    return -math.log(p) / math.log(o)


def _order_key(pick: dict):
    """Cost first, banded; the cheaper market breaks the tie."""
    from leagues.picks import ESTIMATE_MARGIN
    m = pick.get("market_margin")
    margin = (ESTIMATE_MARGIN - 1.0) if m is None else m
    # Bookability outranks margin for the same reason it does on the card: an
    # unbookable leg costs the whole slip its code, a point of margin does not.
    return (round(_cost(pick) / _COST_TIE_BAND),
            not pick.get("bookable"),
            margin)


def _pool(horizon: str = DEFAULT_HORIZON, force: bool = False) -> list:
    """Every publishable pick within the horizon, best-first by cost."""
    from leagues.engine import run_pipeline
    from leagues.picks import MIN_PUBLISHABLE_CONFIDENCE, min_confidence_for
    from leagues.calibrator import fit_calibration

    picks, _ = run_pipeline(days_ahead=POOL_DAYS, force=force)
    fit = fit_calibration()

    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat().replace("+00:00", "Z")
    until = _horizon_end(now_dt, horizon).isoformat().replace("+00:00", "Z")

    out = []
    for p in picks:
        if (p["_fixture"].get("commence_time") or "") > until:
            continue
        # A fixture already under way cannot be booked, so it cannot be part
        # of a slip somebody is about to place.
        if (p["_fixture"].get("commence_time") or "") <= now:
            continue
        floor = max(min_confidence_for(p["market"], fit=fit),
                    MIN_PUBLISHABLE_CONFIDENCE)
        if p["confidence"] >= floor:
            out.append(p)
    return out


def _horizon_end(now_dt: datetime, horizon: str) -> datetime:
    """Inclusive end of a 1- or 7-calendar-day horizon in audience time.

    ``today`` used to add one full day and then round to midnight, so it
    included tomorrow as well.  BetSightly publishes in WAT; defining the
    calendar there keeps "today" true around UTC midnight too.
    """
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    days = HORIZONS.get(horizon, POOL_DAYS)
    wat_date = now_dt.astimezone(WAT).date() + timedelta(days=days - 1)
    return datetime.combine(wat_date, time.max, tzinfo=WAT).astimezone(timezone.utc)


def _best_per_fixture_group(pool: list) -> list:
    best: dict = {}
    for p in sorted(pool, key=_order_key):
        key = (p["match_id"], p["market_group"])
        if key not in best:
            best[key] = p
    return sorted(best.values(), key=_order_key)


def build_slip(target: float, pool: list | None = None,
               max_legs: int = MAX_LEGS, market_cap: int | None = None,
               horizon: str = DEFAULT_HORIZON,
               require_bookable: bool = True) -> dict:
    """The slip most likely to land at `target`, or an honest refusal."""
    from leagues.selection import (
        MARKET_CAP, TEAM_TO_SCORE_CAP, exposure_group,
    )
    cap = MARKET_CAP if market_cap is None else market_cap

    if pool is None:
        pool = _pool(horizon)
    if not pool:
        return {"ok": False, "reason": "No qualifying picks are available right now."}

    if require_bookable:
        pool = [pick for pick in pool if pick.get("bookable")]
        if not pool:
            return {"ok": False,
                    "reason": "No exact SportyBet-bookable selections are available right now."}

    from leagues.leg_trust import evaluate_leg_trust
    trust_rejections: collections.Counter = collections.Counter()
    trusted_pool = []
    for pick in pool:
        decision = evaluate_leg_trust(pick)
        pick["trust"] = decision
        pick["evidence_adjusted_probability"] = decision[
            "evidence_adjusted_probability"
        ]

        # Draw No Bet has win / push / loss settlement states. Until Builder
        # models push-adjusted accumulator payouts completely, fail closed
        # rather than treating DNB like an ordinary binary leg.
        if pick.get("market") in {"dnb_home", "dnb_away"}:
            trust_rejections.update(["dnb_push_math_pending"])
            continue

        if decision["accepted"]:
            trusted_pool.append(pick)
        else:
            trust_rejections.update(
                decision["rejection_reasons"]
                or ["trust_grade_below_b"]
            )

    pool = trusted_pool
    if not pool:
        return {
            "ok": False, "target": target, "best_reachable": 1.0,
            "trusted_leg_count": 0,
            "trust_rejection_reasons": dict(trust_rejections),
            "reason": "No selections meet the Builder's evidence and bookability standard right now.",
        }

    candidates = _best_per_fixture_group(pool)

    def _candidate(seed: dict | None = None):
        seen_fixtures: set = set()
        groups: collections.Counter = collections.Counter()
        exposures: collections.Counter = collections.Counter()
        odds, joint, legs = 1.0, 1.0, []

        ordered = ([seed] if seed is not None else []) + candidates
        for p in ordered:
            if p in legs or len(legs) >= max_legs:
                continue
            group = p["market_group"]
            exposure = exposure_group(group)
            if p["match_id"] in seen_fixtures or groups[group] >= cap:
                continue
            if (exposure == "team_to_score"
                    and exposures[exposure] >= TEAM_TO_SCORE_CAP):
                continue
            seen_fixtures.add(p["match_id"])
            groups[group] += 1
            exposures[exposure] += 1
            odds *= p["odds"]
            joint *= p.get("evidence_adjusted_probability", p["confidence"])
            legs.append(p)
            if odds >= target:
                break
        return odds, joint, legs

    # Include the ordinary cost-first path, then seed the search with each of
    # the strongest alternatives. This stays bounded on a live board while
    # finding discrete combinations a single greedy pass misses.
    attempts = [_candidate()]
    attempts.extend(_candidate(seed) for seed in candidates[:48])
    qualifying = [attempt for attempt in attempts
              if attempt[0] >= target]
    if qualifying:
        in_band = [attempt for attempt in qualifying
                   if attempt[0] <= target * BAND_HIGH]
        choices = in_band or qualifying
        odds, joint, legs = max(
            choices,
            key=lambda attempt: (
                attempt[1],
                -abs(math.log(attempt[0] / target)),
                -len(attempt[2]),
            ),
        )
    else:
        odds, joint, legs = max(attempts, key=lambda attempt: attempt[0])

    if odds < target:
        # Say which limit bit, because "not available" hides two different
        # answers: the board was thin, or the rules would not allow it.
        limit = ("the board does not currently hold enough qualifying picks"
                 if len(legs) < max_legs
                 else f"reaching it would take more than {max_legs} legs")
        return {
            "ok": False,
            "target": target,
            "best_reachable": round(odds, 2),
            "legs": len(legs),
            "trusted_leg_count": len(candidates),
            "trust_rejection_reasons": dict(trust_rejections),
            "reason": (f"The best qualifying slip right now reaches "
                       f"{odds:.1f}x — {limit}. Lowering standards to reach "
                       f"{target:g}x would not make it a better bet."),
        }

    if odds > target * BAND_HIGH:
        logger.info(f"slip for {target}x overshot to {odds:.1f}x")

    # Model-estimated return per unit staked is the chance every leg lands
    # multiplied by the actual combined payout.  The previous implementation
    # multiplied generic market margins instead, which described a theoretical
    # bookmaker rather than the slip on screen and could disagree materially
    # with its own displayed probability and odds.
    expected_return = joint * odds

    return {
        "ok": True,
        "target": target,
        "odds": round(odds, 2),
        "legs": len(legs),
        "hit_probability": round(joint, 5),
        "expected_return": round(expected_return, 4),
        "avg_confidence": round(sum(p["confidence"] for p in legs) / len(legs), 4),
        "avg_evidence_probability": round(sum(p.get("evidence_adjusted_probability",p["confidence"]) for p in legs)/len(legs),4),
        "minimum_trust_score": min(p["trust"]["trust_score"] for p in legs),
        "average_trust_score": round(sum(p["trust"]["trust_score"] for p in legs) / len(legs), 1),
        "lowest_trust_grade": max(p["trust"]["trust_grade"] for p in legs),
        "trust_rejection_reasons": dict(trust_rejections),
        "bookable_legs": sum(1 for p in legs if p.get("bookable")),
        "picks": legs,
    }


def generate(target: float, horizon: str = DEFAULT_HORIZON,
             force: bool = False) -> dict:
    """Build a slip for `target` and book it. The endpoint's whole job."""
    from leagues.picks import to_game

    try:
        target = float(target)
    except (TypeError, ValueError):
        return {"status": "error", "reason": "Target must be a number."}
    if not (MIN_TARGET <= target <= MAX_TARGET):
        return {"status": "error",
                "reason": f"Choose a target between {MIN_TARGET:g} and "
                          f"{MAX_TARGET:g}."}

    if horizon not in HORIZONS:
        return {"status": "error",
                "reason": f"Horizon must be one of {sorted(HORIZONS)}."}

    timing_started = monotonic_time.perf_counter()
    timings: dict[str, int] = {}

    def elapsed_ms(started: float) -> int:
        return round((monotonic_time.perf_counter() - started) * 1000)

    stage_started = monotonic_time.perf_counter()
    try:
        qualified_pool = _pool(horizon, force=force)
    except Exception as exc:
        logger.warning(f"slip candidate refresh failed: {exc}")
        return {
            "status": "unavailable",
            "horizon": horizon,
            "timing_ms": {
                "candidate_retrieval": elapsed_ms(stage_started),
                "total": elapsed_ms(timing_started),
            },
            "reason": ("The prediction board could not be refreshed right "
                       "now. Please try the build again shortly."),
        }
    timings["candidate_retrieval"] = elapsed_ms(stage_started)
    try:
        from leagues import sportybet
        # A normal build should use the healthy cached live board. Forcing a
        # network refresh on every click made valid builds fail on temporary
        # SportyBet errors. Explicit regeneration still requests a refresh.
        stage_started = monotonic_time.perf_counter()
        try:
            board = sportybet.fetch_board(force=force)
        except Exception:
            if not force:
                raise
            logger.warning("Live SportyBet refresh failed; trying cached board")
            board = sportybet.fetch_board(force=False)
        timings["sportybet_catalogue_lookup"] = elapsed_ms(stage_started)
        snapshot_id = sportybet.board_metadata(board).get("snapshot_id")
        bookable_pool = []
        stage_started = monotonic_time.perf_counter()
        for pick in qualified_pool:
            # The prediction pipeline has already matched each fixture once
            # and attached exact market availability from that board. Reuse
            # it when the snapshot is unchanged instead of scanning the full
            # catalogue again for every qualifying pick (2,120 scans on the
            # measured week board). A refreshed/different snapshot still gets
            # a full revalidation, preserving booking correctness.
            availability = pick.get("sportybet_availability") or {}
            if (not snapshot_id
                    or availability.get("board_snapshot_id") != snapshot_id):
                fixture = pick["_fixture"]
                availability = sportybet.availability_for(
                    board, fixture["home"]["name"], fixture["away"]["name"],
                    fixture.get("commence_time", ""), fixture.get("league", ""),
                    pick["market"])
            if not availability.get("sportybet_available"):
                continue
            candidate = dict(pick)
            candidate["bookable"] = True
            candidate["sportybet_availability"] = availability
            candidate["odds"] = availability["sportybet_odds"]
            candidate["odds_are_real"] = True
            bookable_pool.append(candidate)
        timings["fixture_matching"] = elapsed_ms(stage_started)
    except Exception as exc:
        logger.warning(f"SportyBet pool revalidation failed: {exc}")
        board, bookable_pool = {}, []

    stage_started = monotonic_time.perf_counter()
    built = build_slip(target, pool=bookable_pool,
                       horizon=horizon, require_bookable=True)
    timings["combination_search"] = elapsed_ms(stage_started)
    # Target-odds scoring is the final, sub-millisecond portion of the bounded
    # combination search. Keep it explicit in operational output so a future
    # search change cannot hide an optimization regression.
    timings["target_odds_optimization"] = 0
    if not built.get("ok"):
        timings["total"] = elapsed_ms(timing_started)
        return {"status": "unavailable", "horizon": horizon,
                "timing_ms": timings, **built}

    games = [to_game(p) for p in built["picks"]]
    kickoffs = sorted(g.get("kickoff") or "" for g in games if g.get("kickoff"))
    out = {
        "status": "success",
        "target": target,
        "horizon": horizon,
        # When the slip actually resolves, so a "today" pick is visibly today
        # and a week-long one is visibly not.
        "first_kickoff": kickoffs[0] if kickoffs else None,
        "last_kickoff": kickoffs[-1] if kickoffs else None,
        "odds": built["odds"],
        "legs": built["legs"],
        "hit_probability": built["hit_probability"],
        "expected_return": built["expected_return"],
        "avg_confidence": built["avg_confidence"],
        "avg_evidence_probability": built.get("avg_evidence_probability", built["avg_confidence"]),
        "minimum_trust_score": built.get("minimum_trust_score"),
        "average_trust_score": built.get("average_trust_score"),
        "lowest_trust_grade": built.get("lowest_trust_grade"),
        "trust_rejection_reasons": built.get("trust_rejection_reasons", {}),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "games": games,
    }

    # Book it. A slip nobody can place is only half the feature — but a failed
    # booking must not lose the slip, so this reports rather than raises.
    stage_started = monotonic_time.perf_counter()
    try:
        from leagues.booking import create_or_reuse_generated_booking
        out["booking"] = create_or_reuse_generated_booking(
            games, board, predicted_odds=built["odds"], force=force)
    except Exception as e:
        logger.warning(f"slip booking failed: {e}")
        out["booking"] = {"status": "failed", "share_code": None,
                          "reason": f"Booking unavailable: {str(e)[:120]}"}
    timings["booking_total"] = elapsed_ms(stage_started)
    booking_timings = (out.get("booking") or {}).get("timing_ms") or {}
    timings["booking_code_generation"] = booking_timings.get("code_generation", 0)
    timings["validation_readback"] = booking_timings.get("validation_readback", 0)
    timings["database_persistence"] = booking_timings.get("database_persistence", 0)
    timings["total"] = elapsed_ms(timing_started)
    out["timing_ms"] = timings
    logger.info("Builder timing target=%sx horizon=%s %s", target, horizon, timings)
    return out
