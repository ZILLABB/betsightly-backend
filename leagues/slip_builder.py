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


DNB_MARKETS = {"dnb_home", "dnb_away"}


def _market_distribution(picks: list[dict]) -> dict[str, int]:
    return dict(collections.Counter(str(p.get("market") or "unknown") for p in picks))

# Builder-only candidate floors backed by Phase 2A replay evidence.
#
# These do not change the daily card or normal prediction tiers. They only
# allow the Builder to consider these markets before the stricter evidence,
# trust and exact-bookability gates decide whether a leg is actually usable.
BUILDER_MARKET_FLOORS = {
    "over_2_5": 0.60,
    "home_over_1_5": 0.65,
    "away_over_1_5": 0.65,
}


def _market_cap_for_target(target: float) -> int:
    """Use the public market cap at every target; quality never relaxes."""
    from leagues.selection import MARKET_CAP

    return MARKET_CAP


def _team_to_score_cap_for_target(target: float) -> int:
    """Use the public Team-to-Score cap at every target."""
    from leagues.selection import TEAM_TO_SCORE_CAP

    return TEAM_TO_SCORE_CAP


def _leg_settlement_probabilities(
    pick: dict,
) -> tuple[float, float, float] | None:
    """Return (win, push, loss) probabilities for one Builder leg.

    Normal markets are binary.

    DNB confidence is conditional on a decisive result, while a draw voids
    that leg. Convert the conditional DNB probability back into unconditional
    win / push / loss probabilities before accumulator maths.
    """
    probability = max(
        0.0,
        min(
            1.0,
            float(
                pick.get(
                    "evidence_adjusted_probability",
                    pick.get("confidence", 0.0),
                )
            ),
        ),
    )

    if pick.get("market") not in DNB_MARKETS:
        return probability, 0.0, 1.0 - probability

    model_probabilities = (pick.get("_model") or {}).get("probabilities") or {}
    draw_probability = model_probabilities.get("draw")

    # Never silently treat DNB as binary when its push probability is missing.
    if draw_probability is None:
        return None

    push_probability = max(
        0.0,
        min(1.0, float(draw_probability)),
    )
    decisive_probability = 1.0 - push_probability

    win_probability = probability * decisive_probability
    loss_probability = (1.0 - probability) * decisive_probability

    return (
        win_probability,
        push_probability,
        loss_probability,
    )


def _positive_payout_distribution(
    legs: list[dict],
) -> dict[float, float]:
    """Probability distribution of positive accumulator payout factors.

    Losing branches are omitted because they return zero.

    A DNB win contributes its quoted odds. A DNB push contributes 1.00.
    """
    states: dict[float, float] = {1.0: 1.0}

    for pick in legs:
        settlement = _leg_settlement_probabilities(pick)
        if settlement is None:
            return {}

        win_probability, push_probability, _ = settlement
        odds = float(pick["odds"])

        next_states: dict[float, float] = {}

        for payout, probability in states.items():
            win_payout = payout * odds
            next_states[win_payout] = (
                next_states.get(win_payout, 0.0) + probability * win_probability
            )

            if push_probability:
                next_states[payout] = (
                    next_states.get(payout, 0.0) + probability * push_probability
                )

        states = next_states

    return states


def _aggregate_credibility(legs: list[dict], odds: float,
                           expected_return: float,
                           model_hit_probability: float) -> dict:
    """Conservative diagnostic for accumulator edge claims.

    Each leg is recomputed at its evidence-derived lower reliability bound.
    Those lower bounds already incorporate sample uncertainty/shrinkage. The
    diagnostic also exposes concentration where an independence assumption is
    most fragile; it reports uncertainty but does not mutate selection policy.
    """
    from leagues.selection import exposure_group

    conservative_legs = []
    missing_bounds = 0
    for leg in legs:
        trust = leg.get("trust") or {}
        lower = trust.get("lower_reliability_bound")
        if lower is None:
            missing_bounds += 1
            lower = leg.get("evidence_adjusted_probability", leg.get("confidence", 0))
        conservative_legs.append({
            **leg,
            "evidence_adjusted_probability": max(0.0, min(1.0, float(lower))),
        })
    distribution = _positive_payout_distribution(conservative_legs)
    conservative_return = sum(payout * probability
                              for payout, probability in distribution.items())
    market_counts = collections.Counter(
        exposure_group(leg.get("market_group")) for leg in legs
    )
    league_counts = collections.Counter(
        str((leg.get("_fixture") or {}).get("league") or leg.get("league") or "unknown")
        for leg in legs
    )
    concentrated = bool(legs) and (
        max(market_counts.values(), default=0) > max(2, len(legs) // 2)
        or max(league_counts.values(), default=0) > max(2, len(legs) // 2)
    )
    break_even = 1.0 / max(1.0, float(odds))
    conservative_hit = 1.0
    for leg in conservative_legs:
        settlement = _leg_settlement_probabilities(leg)
        conservative_hit *= settlement[0] if settlement else 0.0
    if missing_bounds:
        status = "INSUFFICIENT_LOWER_BOUND_EVIDENCE"
    elif expected_return > 1.0 and conservative_return < 1.0:
        status = "EDGE_NOT_SUPPORTED_BY_LOWER_BOUNDS"
    else:
        status = "LOWER_BOUND_SUPPORTED"
    return {
        "status": status,
        "model_expected_return": round(expected_return, 4),
        "conservative_expected_return": round(conservative_return, 4),
        "model_hit_probability": round(model_hit_probability, 6),
        "conservative_hit_probability": round(conservative_hit, 6),
        "bookmaker_break_even_probability": round(break_even, 6),
        "missing_lower_bounds": missing_bounds,
        "extraordinary_claim": expected_return >= 2.0,
        "dependence_warning": concentrated,
        "market_concentration": dict(market_counts),
        "league_concentration": dict(league_counts),
        "action": "REPORT_ONLY_NO_POLICY_MUTATION",
    }


def _cost(pick: dict) -> float:
    settlement = _leg_settlement_probabilities(pick)

    # Missing DNB draw information should make the leg maximally unattractive.
    if settlement is None:
        return float("inf")

    win_probability, _, _ = settlement

    # Target construction uses the probability of actually winning at the
    # quoted odds. A DNB push keeps the ticket alive but contributes 1.00x.
    p = max(1e-6, min(0.999, win_probability))
    o = max(1.0001, pick["odds"])

    return -math.log(p) / math.log(o)


def _order_key(pick: dict):
    """Cost first, banded; the cheaper market breaks the tie."""
    from leagues.picks import ESTIMATE_MARGIN

    m = pick.get("market_margin")
    margin = (ESTIMATE_MARGIN - 1.0) if m is None else m
    # Bookability outranks margin for the same reason it does on the card: an
    # unbookable leg costs the whole slip its code, a point of margin does not.
    return (round(_cost(pick) / _COST_TIE_BAND), not pick.get("bookable"), margin)


def _pool(horizon: str = DEFAULT_HORIZON, force: bool = False) -> list:
    """Every Builder-qualified pick within the requested horizon."""
    from leagues.calibrator import fit_calibration
    from leagues.engine import run_pipeline
    from leagues.picks import (
        MIN_CANDIDATE_CONFIDENCE,
        MIN_PUBLISHABLE_CONFIDENCE,
        build_picks,
        min_confidence_for,
    )

    # run_pipeline still performs the expensive work exactly once:
    # fixtures, SportyBet matching, model prediction and ML overlay.
    #
    # Its returned picks have already passed the normal publication floors,
    # though, so rebuild picks from the already-evaluated fixtures using the
    # Builder-only market overrides. This is NOT a second prediction run.
    _, fixtures = run_pipeline(
        days_ahead=POOL_DAYS,
        force=force,
    )

    fit = fit_calibration()
    picks = []

    for fixture in fixtures:
        model = fixture.get("_model")
        if not model:
            continue

        picks.extend(
            build_picks(
                fixture,
                model,
                min_confidence=MIN_CANDIDATE_CONFIDENCE,
                fit=fit,
                market_floor_overrides=BUILDER_MARKET_FLOORS,
            )
        )

    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat().replace("+00:00", "Z")
    until = _horizon_end(now_dt, horizon).isoformat().replace("+00:00", "Z")

    out = []

    for p in picks:
        commence_time = p["_fixture"].get("commence_time") or ""

        if commence_time > until:
            continue

        if commence_time <= now:
            continue

        normal_floor = max(
            min_confidence_for(
                p["market"],
                fit=fit,
            ),
            MIN_PUBLISHABLE_CONFIDENCE,
        )

        floor = BUILDER_MARKET_FLOORS.get(
            p["market"],
            normal_floor,
        )

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


def _verified_optimize(candidates: list[dict], target: float, max_legs: int,
                       market_cap: int, team_to_score_cap: int,
                       under_cap: int = 2) -> tuple[float, float, list[dict], str]:
    """Solve the Builder's binary selection problem with HiGHS MILP.

    The first solve maximizes evidence-adjusted joint probability subject to
    reaching the target. If that is infeasible, the second solve verifies the
    maximum reachable multiplier under exactly the same safety constraints.
    """
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import csr_matrix
    from leagues.selection import exposure_group

    valid = []
    probabilities = []
    for pick in candidates:
        settlement = _leg_settlement_probabilities(pick)
        if settlement is None or float(pick.get("odds") or 0) <= 1.0:
            continue
        probability = settlement[0]
        if probability <= 0:
            continue
        valid.append(pick)
        probabilities.append(probability)
    if not valid:
        return 1.0, 1.0, [], "OPTIMAL"

    size = len(valid)
    rows: list[list[float]] = []
    upper: list[float] = []

    def limited(indices, limit):
        row = [0.0] * size
        for index in indices:
            row[index] = 1.0
        rows.append(row)
        upper.append(float(limit))

    limited(range(size), max_legs)
    fixtures: dict[str, list[int]] = collections.defaultdict(list)
    groups: dict[str, list[int]] = collections.defaultdict(list)
    for index, pick in enumerate(valid):
        fixtures[str(pick.get("match_id"))].append(index)
        groups[str(pick.get("market_group") or "other")].append(index)
    for indices in fixtures.values():
        limited(indices, 1)
    for indices in groups.values():
        limited(indices, market_cap)
    limited((i for i, p in enumerate(valid)
             if exposure_group(p.get("market_group")) == "team_to_score"),
            team_to_score_cap)
    limited((i for i, p in enumerate(valid)
             if str(p.get("market", "")).startswith("under_")), under_cap)

    log_odds = np.array([math.log(float(p["odds"])) for p in valid])
    risk = np.array([-math.log(max(1e-9, min(.999999, p)))
                     for p in probabilities])
    matrix = csr_matrix(np.asarray(rows, dtype=float))
    base_constraint = LinearConstraint(matrix, -np.inf, np.asarray(upper))
    target_constraint = LinearConstraint(
        csr_matrix(-log_odds.reshape(1, -1)), -np.inf,
        np.array([-math.log(target)]),
    )
    options = {"time_limit": 8.0, "mip_rel_gap": 1e-7}

    reached = milp(
        risk, integrality=np.ones(size), bounds=Bounds(0, 1),
        constraints=(base_constraint, target_constraint), options=options,
    )
    result = reached
    if reached.x is None:
        # Verify the maximum possible odds instead of describing a greedy
        # incumbent as "best reachable".
        result = milp(
            -log_odds, integrality=np.ones(size), bounds=Bounds(0, 1),
            constraints=base_constraint, options=options,
        )
    if result.x is None:
        return 1.0, 1.0, [], "HEURISTIC"

    selected = [valid[i] for i, value in enumerate(result.x) if value >= .5]
    odds = math.prod(float(p["odds"]) for p in selected)
    joint = math.prod(probabilities[i] for i, value in enumerate(result.x)
                      if value >= .5)
    status = "OPTIMAL" if result.status == 0 else "BOUNDED_OPTIMAL"
    return odds, joint, selected, status


def build_slip(
    target: float,
    pool: list | None = None,
    max_legs: int = MAX_LEGS,
    market_cap: int | None = None,
    horizon: str = DEFAULT_HORIZON,
    require_bookable: bool = True,
) -> dict:
    """The slip most likely to land at `target`, or an honest refusal."""
    from leagues.selection import exposure_group

    cap = _market_cap_for_target(target) if market_cap is None else market_cap
    team_to_score_cap = _team_to_score_cap_for_target(target)

    if pool is None:
        pool = _pool(horizon)
    if not pool:
        return {"ok": False, "result_status": "NO_SAFE_COMBINATION",
                "target": target, "best_reachable": 1.0,
                "optimization_status": "OPTIMAL", "candidate_count_initial": 0,
                "after_bookability": 0, "after_trust": 0, "after_policy": 0,
                "optimizer_candidate_count": 0, "fixture_count": 0,
                "market_distribution": {}, "binding_constraints": [],
                "max_legs": max_legs,
                "reason": "No qualifying picks are available right now."}
    diagnostics = {
        "candidate_count_initial": len(pool),
        "market_distribution_initial": _market_distribution(pool),
    }

    if require_bookable:
        pool = [pick for pick in pool if pick.get("bookable")]
        if not pool:
            return {
                "ok": False,
                "result_status": "INSUFFICIENT_BOOKABLE_FIXTURES",
                "target": target,
                "best_reachable": 1.0,
                "optimization_status": "OPTIMAL",
                "candidate_count_initial": diagnostics["candidate_count_initial"],
                "after_bookability": 0, "after_trust": 0, "after_policy": 0,
                "optimizer_candidate_count": 0, "fixture_count": 0,
                "market_distribution": {}, "binding_constraints": [],
                "max_legs": max_legs,
                "reason": "No exact SportyBet-bookable selections are available right now.",
            }
    diagnostics["after_bookability"] = len(pool)
    diagnostics["market_distribution_after_bookability"] = _market_distribution(pool)

    from leagues.leg_trust import evaluate_leg_trust

    trust_rejections: collections.Counter = collections.Counter()
    trusted_pool = []
    for pick in pool:
        decision = evaluate_leg_trust(pick)
        pick["trust"] = decision
        pick["evidence_adjusted_probability"] = decision[
            "evidence_adjusted_probability"
        ]

        if (
            pick.get("market") in DNB_MARKETS
            and _leg_settlement_probabilities(pick) is None
        ):
            trust_rejections.update(["dnb_missing_draw_probability"])
            continue

        if decision["accepted"]:
            trusted_pool.append(pick)
        else:
            trust_rejections.update(
                decision["rejection_reasons"] or ["trust_grade_below_b"]
            )

    pool = trusted_pool
    diagnostics["after_trust"] = len(pool)
    diagnostics["market_distribution_after_trust"] = _market_distribution(pool)
    if not pool:
        return {
            "ok": False,
            "result_status": "NO_SAFE_COMBINATION",
            "target": target,
            "best_reachable": 1.0,
            "trusted_leg_count": 0,
            "trust_rejection_reasons": dict(trust_rejections),
            "selection_diagnostics": diagnostics,
            "reason": "No selections meet the Builder's evidence and bookability standard right now.",
        }

    from leagues.fixture_ranker import builder_fixture_candidates
    candidates = builder_fixture_candidates(pool)
    diagnostics["after_policy_and_canonical_ranking"] = len(candidates)
    diagnostics["after_min_useful_odds"] = sum(1 for p in candidates if p.get("odds", 0) >= 1.12)
    diagnostics["after_policy"] = len(candidates)
    diagnostics["optimizer_candidate_count"] = len(candidates)
    diagnostics["fixture_count"] = len({p.get("match_id") for p in candidates})
    diagnostics["market_distribution_after_canonical_ranking"] = _market_distribution(candidates)
    diagnostics["public_rank_distribution"] = dict(collections.Counter(str(p.get("public_rank")) for p in candidates))
    diagnostics["trust_distribution"] = dict(collections.Counter(str((p.get("trust") or {}).get("evidence_state")) for p in candidates))
    diagnostics["quality_constraints"] = {"market_cap": cap, "team_to_score_cap": team_to_score_cap, "under_cap": 2, "max_legs": max_legs}
    if not candidates:
        return {
            "ok": False, "result_status": "NO_SAFE_COMBINATION",
            "target": target, "best_reachable": 1.0, "trusted_leg_count": 0,
            "trust_rejection_reasons": dict(trust_rejections),
            "selection_diagnostics": diagnostics,
            "reason": "No fixture has a top-ranked market that meets the Builder quality policy.",
        }

    def _candidate(
        seed: dict | None = None,
        candidate_pool: list | None = None,
    ):
        search_pool = (
            candidates
            if candidate_pool is None
            else candidate_pool
        )

        seen_fixtures: set = set()
        groups: collections.Counter = collections.Counter()
        exposures: collections.Counter = collections.Counter()
        under_count = 0
        odds, joint, legs = 1.0, 1.0, []

        ordered = (
            ([seed] if seed is not None else [])
            + search_pool
        )

        for p in ordered:
            if p in legs or len(legs) >= max_legs:
                continue

            group = p["market_group"]
            exposure = exposure_group(group)

            if (
                p["match_id"] in seen_fixtures
                or groups[group] >= cap
            ):
                continue

            if (
                exposure == "team_to_score"
                and exposures[exposure]
                >= team_to_score_cap
            ):
                continue

            if str(p.get("market", "")).startswith("under_") and under_count >= 2:
                continue

            settlement = _leg_settlement_probabilities(p)

            if settlement is None:
                continue

            win_probability, _, _ = settlement

            seen_fixtures.add(p["match_id"])
            groups[group] += 1
            exposures[exposure] += 1
            if str(p.get("market", "")).startswith("under_"):
                under_count += 1

            odds *= p["odds"]
            joint *= win_probability
            legs.append(p)

            if odds >= target:
                break

        return odds, joint, legs

    def _attempt_rank(attempt):
        attempt_odds, attempt_joint, attempt_legs = attempt

        return (
            attempt_odds <= target * BAND_HIGH,
            attempt_joint,
            -abs(
                math.log(
                    attempt_odds / target
                )
            ),
            -len(attempt_legs),
        )

    def _search(candidate_pool: list):
        attempts = [
            _candidate(
                candidate_pool=candidate_pool,
            )
        ]

        attempts.extend(
            _candidate(
                seed,
                candidate_pool,
            )
            for seed in candidate_pool[:48]
        )

        qualifying = [
            attempt
            for attempt in attempts
            if attempt[0] >= target
        ]

        if qualifying:
            return max(
                qualifying,
                key=_attempt_rank,
            )

        return max(
            attempts,
            key=lambda attempt: attempt[0],
        )

    # Solve the complete approved pool. The old bounded greedy search remains
    # only as a resilience fallback if the numerical optimizer is unavailable.
    try:
        odds, joint, legs, optimization_status = _verified_optimize(
            candidates, target, max_legs, cap, team_to_score_cap,
        )
    except Exception as exc:
        logger.warning("verified Builder optimization unavailable: %s", exc)
        odds, joint, legs = _search(candidates)
        optimization_status = "HEURISTIC"
    diagnostics["optimization_status"] = optimization_status

    # A greedy path can occasionally reserve a scarce market-group slot
    # for a slightly weaker leg. Test the selected fixtures one at a time:
    # removing one may expose a later candidate that makes the complete
    # target slip more likely to land.
    #
    # Two passes keep this bounded while allowing one improvement to expose
    # a second nearby improvement.
    if optimization_status == "HEURISTIC" and odds >= target:
        best = (odds, joint, legs)

        for _ in range(2):
            improved = best

            for selected in best[2]:
                reduced = [
                    candidate
                    for candidate in candidates
                    if candidate["match_id"]
                    != selected["match_id"]
                ]

                alternative = _search(reduced)

                if alternative[0] < target:
                    continue

                if (
                    _attempt_rank(alternative)
                    > _attempt_rank(improved)
                ):
                    improved = alternative

            if (
                _attempt_rank(improved)
                <= _attempt_rank(best)
            ):
                break

            best = improved

        odds, joint, legs = best

    selected_groups = collections.Counter(p.get("market_group") for p in legs)
    selected_exposures = collections.Counter(exposure_group(p.get("market_group")) for p in legs)
    selected_under_count = sum(
        str(p.get("market", "")).startswith("under_") for p in legs
    )
    diagnostics["after_exposure"] = len(legs)
    diagnostics["selected_market_distribution"] = _market_distribution(legs)
    diagnostics["binding_constraints"] = [
        *[f"market_group:{group}" for group, count in selected_groups.items()
          if count >= cap],
        *(["team_to_score"] if selected_exposures["team_to_score"] >= team_to_score_cap else []),
        *(["under"] if selected_under_count >= 2 else []),
        *(["max_legs"] if len(legs) >= max_legs else []),
    ]

    if odds < target:
        # Say which limit bit, because "not available" hides two different
        # answers: the board was thin, or the rules would not allow it.
        binding = diagnostics["binding_constraints"]
        if "max_legs" in binding:
            result_status = "MAX_LEGS_CAPPED"
        elif binding:
            result_status = "EXPOSURE_CAPPED"
        else:
            result_status = "QUALITY_CAPPED"
        verified = optimization_status in {"OPTIMAL", "BOUNDED_OPTIMAL"}
        description = ("The strongest verified combination" if verified
                       else "The current search found a qualifying combination")
        return {
            "ok": False,
            "result_status": result_status,
            "target": target,
            "best_reachable": round(odds, 2),
            "achieved_odds": round(odds, 2),
            "legs": len(legs),
            "picks": legs,
            "hit_probability": round(joint, 5),
            "trusted_leg_count": len(candidates),
            "optimization_status": optimization_status,
            "candidate_count_initial": diagnostics["candidate_count_initial"],
            "after_bookability": diagnostics.get("after_bookability", 0),
            "after_trust": diagnostics.get("after_trust", 0),
            "after_policy": diagnostics.get("after_policy", 0),
            "optimizer_candidate_count": len(candidates),
            "fixture_count": diagnostics.get("fixture_count", 0),
            "market_distribution": diagnostics.get("market_distribution_after_canonical_ranking", {}),
            "binding_constraints": binding,
            "max_legs": max_legs,
            "trust_rejection_reasons": dict(trust_rejections),
            "selection_diagnostics": diagnostics,
            "reason": (
                f"{description} reaches {odds:.2f}x. Lowering standards to reach "
                f"{target:g}x would not make it a better bet."
            ),
        }

    if odds > target * BAND_HIGH:
        logger.info(f"slip for {target}x overshot to {odds:.1f}x")

    # Calculate the full positive-payout distribution. Normal binary legs
    # have one positive branch; DNB legs can either win at their quoted odds
    # or push at 1.00x.
    payout_distribution = _positive_payout_distribution(legs)

    expected_return = sum(
        payout * probability for payout, probability in payout_distribution.items()
    )

    no_loss_probability = sum(payout_distribution.values())

    target_hit_probability = sum(
        probability
        for payout, probability in payout_distribution.items()
        if payout >= target
    )

    push_survival_probability = max(
        0.0,
        no_loss_probability - joint,
    )

    aggregate_credibility = _aggregate_credibility(
        legs, odds, expected_return, joint
    )

    return {
        "ok": True,
        "result_status": "TARGET_REACHED",
        "optimization_status": optimization_status,
        "target": target,
        "odds": round(odds, 2),
        "legs": len(legs),
        "hit_probability": round(joint, 5),
        "expected_return": round(expected_return, 4),
        "expected_return_basis": "model_estimate",
        "aggregate_credibility": aggregate_credibility,
        "target_hit_probability": round(
            target_hit_probability,
            5,
        ),
        "no_loss_probability": round(
            no_loss_probability,
            5,
        ),
        "push_survival_probability": round(
            push_survival_probability,
            5,
        ),
        "dnb_leg_count": sum(1 for p in legs if p.get("market") in DNB_MARKETS),
        "team_to_score_leg_count": sum(1 for p in legs if p.get("market") in {"home_over_0_5", "away_over_0_5"}),
        "under_leg_count": sum(1 for p in legs if str(p.get("market", "")).startswith("under_")),
        "fixture_rank_1_count": sum(1 for p in legs if p.get("fixture_rank") == 1),
        "fixture_rank_2_count": sum(1 for p in legs if p.get("fixture_rank") == 2),
        "fixture_rank_3_plus_count": sum(1 for p in legs if int(p.get("fixture_rank") or 99) >= 3),
        "avg_confidence": round(sum(p["confidence"] for p in legs) / len(legs), 4),
        "avg_evidence_probability": round(
            sum(p.get("evidence_adjusted_probability", p["confidence"]) for p in legs)
            / len(legs),
            4,
        ),
        "minimum_trust_score": min(p["trust"]["trust_score"] for p in legs),
        "average_trust_score": round(
            sum(p["trust"]["trust_score"] for p in legs) / len(legs), 1
        ),
        "lowest_trust_grade": max(p["trust"]["trust_grade"] for p in legs),
        "trust_rejection_reasons": dict(trust_rejections),
        "candidate_count_initial": diagnostics["candidate_count_initial"],
        "after_bookability": diagnostics.get("after_bookability", 0),
        "after_trust": diagnostics.get("after_trust", 0),
        "after_policy": diagnostics.get("after_policy", 0),
        "optimizer_candidate_count": len(candidates),
        "fixture_count": diagnostics.get("fixture_count", 0),
        "market_distribution": diagnostics.get("market_distribution_after_canonical_ranking", {}),
        "binding_constraints": diagnostics["binding_constraints"],
        "max_legs": max_legs,
        "selection_diagnostics": diagnostics,
        "bookable_legs": sum(1 for p in legs if p.get("bookable")),
        "picks": legs,
    }


def generate(
    target: float, horizon: str = DEFAULT_HORIZON, force: bool = False
) -> dict:
    """Build a slip for `target` and book it. The endpoint's whole job."""
    from leagues.picks import to_game
    from utils.runtime_metrics import log_runtime_memory

    try:
        target = float(target)
    except (TypeError, ValueError):
        return {"status": "error", "reason": "Target must be a number."}
    if not (MIN_TARGET <= target <= MAX_TARGET):
        return {
            "status": "error",
            "reason": f"Choose a target between {MIN_TARGET:g} and {MAX_TARGET:g}.",
        }

    if horizon not in HORIZONS:
        return {
            "status": "error",
            "reason": f"Horizon must be one of {sorted(HORIZONS)}.",
        }

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
            "reason": (
                "The prediction board could not be refreshed right "
                "now. Please try the build again shortly."
            ),
        }
    timings["candidate_retrieval"] = elapsed_ms(stage_started)
    log_runtime_memory(
        "builder_after_candidate_pipeline", target=target, horizon=horizon,
        candidate_count=len(qualified_pool),
    )
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
            if not snapshot_id or availability.get("board_snapshot_id") != snapshot_id:
                fixture = pick["_fixture"]
                availability = sportybet.availability_for(
                    board,
                    fixture["home"]["name"],
                    fixture["away"]["name"],
                    fixture.get("commence_time", ""),
                    fixture.get("league", ""),
                    pick["market"],
                )
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
    built = build_slip(
        target, pool=bookable_pool, horizon=horizon, require_bookable=True
    )
    timings["combination_search"] = elapsed_ms(stage_started)
    log_runtime_memory(
        "builder_after_optimization", target=target, horizon=horizon,
        result_status=built.get("result_status"),
        selected_legs=built.get("legs", 0),
    )
    # Target-odds scoring is the final, sub-millisecond portion of the bounded
    # combination search. Keep it explicit in operational output so a future
    # search change cannot hide an optimization regression.
    timings["target_odds_optimization"] = 0
    if not built.get("ok"):
        timings["total"] = elapsed_ms(timing_started)
        return {
            "status": "unavailable",
            "horizon": horizon,
            "timing_ms": timings,
            **built,
        }

    games = [to_game(p) for p in built["picks"]]
    kickoffs = sorted(g.get("kickoff") or "" for g in games if g.get("kickoff"))
    out = {
        "status": "success",
        "result_status": built.get("result_status", "TARGET_REACHED"),
        "optimization_status": built.get("optimization_status", "HEURISTIC"),
        "target": target,
        "horizon": horizon,
        # When the slip actually resolves, so a "today" pick is visibly today
        # and a week-long one is visibly not.
        "first_kickoff": kickoffs[0] if kickoffs else None,
        "last_kickoff": kickoffs[-1] if kickoffs else None,
        "odds": built["odds"],
        "legs": built["legs"],
        "hit_probability": built["hit_probability"],
        "target_hit_probability": built.get(
            "target_hit_probability",
            built["hit_probability"],
        ),
        "no_loss_probability": built.get(
            "no_loss_probability",
            built["hit_probability"],
        ),
        "push_survival_probability": built.get(
            "push_survival_probability",
            0.0,
        ),
        "dnb_leg_count": built.get("dnb_leg_count", 0),
        "expected_return": built["expected_return"],
        "expected_return_basis": built.get(
            "expected_return_basis",
            "model_estimate",
        ),
        "aggregate_credibility": built.get("aggregate_credibility"),
        "avg_confidence": built["avg_confidence"],
        "avg_evidence_probability": built.get(
            "avg_evidence_probability", built["avg_confidence"]
        ),
        "minimum_trust_score": built.get("minimum_trust_score"),
        "average_trust_score": built.get("average_trust_score"),
        "lowest_trust_grade": built.get("lowest_trust_grade"),
        "trust_rejection_reasons": built.get("trust_rejection_reasons", {}),
        "selection_diagnostics": built.get("selection_diagnostics", {}),
        **{key: built.get(key) for key in (
            "candidate_count_initial", "after_bookability", "after_trust",
            "after_policy", "optimizer_candidate_count", "fixture_count",
            "market_distribution", "binding_constraints", "max_legs",
        )},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "games": games,
    }

    # Book it. A slip nobody can place is only half the feature — but a failed
    # booking must not lose the slip, so this reports rather than raises.
    stage_started = monotonic_time.perf_counter()
    try:
        from leagues.booking import create_or_reuse_generated_booking

        out["booking"] = create_or_reuse_generated_booking(
            games, board, predicted_odds=built["odds"], force=force
        )
    except Exception as e:
        logger.warning(f"slip booking failed: {e}")
        out["booking"] = {
            "status": "failed",
            "share_code": None,
            "reason": f"Booking unavailable: {str(e)[:120]}",
        }
    timings["booking_total"] = elapsed_ms(stage_started)
    log_runtime_memory(
        "builder_after_booking", target=target, horizon=horizon,
        booking_status=(out.get("booking") or {}).get("booking_status")
        or (out.get("booking") or {}).get("status"),
    )
    booking_timings = (out.get("booking") or {}).get("timing_ms") or {}
    timings["booking_code_generation"] = booking_timings.get("code_generation", 0)
    timings["validation_readback"] = booking_timings.get("validation_readback", 0)
    timings["database_persistence"] = booking_timings.get("database_persistence", 0)
    timings["total"] = elapsed_ms(timing_started)
    out["timing_ms"] = timings
    logger.info("Builder timing target=%sx horizon=%s %s", target, horizon, timings)
    return out
