"""Bounded, read-only, model-confidence-first multiple-choice jackpot optimizer.

Only approved candidates supplied by BetSightly may enter. At most one market
per fixture, at most 50 games. A state denotes (leg count, odds bucket); the
highest conservative hit probability at each state survives. The objective is
to find a *plausible best candidate among those evaluated*, not certify a
globally optimal or profitable 100,000x bet.
"""
from __future__ import annotations

from collections import defaultdict
from math import exp, floor, isfinite, log, prod
from typing import Any

MAX_LEGS = 50
MAX_OPTIMIZATION_FIXTURES = 300
BUCKET_STEP = .12  # bounded approximation; actual odds checked before return


def _probability(row: dict) -> float | None:
    try:
        p = float(row.get("selection_probability"))
        lower = row.get("lower_reliability_bound")
        if lower is not None:
            p = min(p, float(lower))
        if not isfinite(p) or not 0 < p < 1:
            return None
        return p
    except (TypeError, ValueError, OverflowError):
        return None


def _unique_fixtures(candidates: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for candidate in candidates:
        key = str(candidate.get("match_id") or "")
        odds = float(candidate.get("odds") or 0)
        if not key or not isfinite(odds) or odds <= 1:
            continue
        if (str(candidate.get("market") or "").startswith("under_") or
                "_under_" in str(candidate.get("market") or "")):
            continue
        if not candidate.get("selection_id"):
            continue
        grouped[key].append(candidate)
    return dict(grouped)


def capacity(candidates: list[dict], limit: int = MAX_LEGS) -> dict:
    """Upper bound if only one highest-priced outcome per fixture can be used.

    It intentionally does NOT optimize win probability, represent a recommended
    slip, or pretend that future bookmaker readback will honour these quotes.
    """
    groups = _unique_fixtures(candidates)
    maximums = sorted((max(float(r["odds"]) for r in rows) for rows in groups.values()), reverse=True)
    chosen = maximums[:limit]
    # Avoid non-finite reference ceilings in JSON for unusually large boards.
    ceiling_log = sum(log(value) for value in chosen)
    ceiling = round(exp(ceiling_log), 3) if ceiling_log < log(1e12) else 1e12
    return {
        "distinct_fixture_count": len(groups),
        "maximum_legs_available": min(len(groups), limit),
        "maximum_reference_odds": ceiling if chosen else 1,
        "upper_bound_explanation": (
            "Mathematical upper bound from highest listed price per fixture "
            "(max 50 legs); NOT a verified or probability-optimized booking."
        ),
    }


def _frontier(rows: list[dict]) -> list[tuple[float, float, str]]:
    """Remove outcomes dominated by another market for the *same* fixture."""
    choices: list[tuple[float, float, str]] = []
    for row in rows:
        p = _probability(row)
        if p is None:
            continue
        odds = float(row["odds"])
        choices.append((odds, p, str(row["selection_id"])))
    # Deduplicate by ID. More odds and more reliability strictly dominate.
    best_by_id = {key: (odds, p, key) for odds, p, key in choices}
    choices = list(best_by_id.values())
    return [
        (log(odds), log(p), key)
        for odds, p, key in choices
        if not any(
            (o >= odds and pp >= p and (o > odds or pp > p))
            for o, pp, _ in choices
        )
    ]


def optimize(candidates: list[dict], target: float, limit: int = MAX_LEGS) -> dict:
    if not isfinite(target) or target < 2 or target > 100_000:
        raise ValueError("Target odds must be between 2x and 100,000x.")
    if limit < 1 or limit > MAX_LEGS:
        raise ValueError("Maximum leg count must be from 1 to 50.")
    bounds = capacity(candidates, limit)
    overview = {
        "target_odds": target,
        "candidate_count": len(candidates),
        **bounds,
        "booking_code_created": False,
        "optimization_method": "bounded_odds_frontier",
        "probability_assumption": "approximate_independence",
    }
    if bounds["maximum_reference_odds"] < target:
        return {
            **overview,
            "status": "UNREACHABLE",
            "reason": (
                "Even the highest listed market for each distinct fixture "
                "cannot reach this target. Try a wider date window, B trust, "
                "or lower the target. No selections or booking code generated."
            ),
            "selection_ids": [],
        }

    from growth.jackpot_feasibility import model_ceiling
    actual_ceiling = model_ceiling(candidates, limit)
    overview["maximum_model_eligible_reference_odds"] = round(actual_ceiling["odds"], 3)
    overview["model_eligible_fixture_count"] = actual_ceiling["eligible_fixtures"]
    overview["fixtures_without_valid_probability"] = actual_ceiling["omitted_fixtures"]
    if log(max(actual_ceiling["odds"], 1)) + 1e-10 < log(target):
        return {
            **overview,
            "status": "INSUFFICIENT_MODEL_EVIDENCE",
            "reason": (
                "Raw prices reach the target, but the model-eligible "
                "markets do not. No code was requested."
            ),
            "selection_ids": [],
        }

    groups = _unique_fixtures(candidates)
    # The diagnostic ceiling above uses the whole board. The following
    # approximation examines a bounded, explicitly reported 300 fixtures.
    prepared = [(key, _frontier(rows)) for key, rows in groups.items()]
    prepared = [(key, opts) for key, opts in prepared if opts]
    prepared.sort(key=lambda item: max(p[0] for p in item[1]), reverse=True)
    count_all = len(prepared)
    prepared = prepared[:MAX_OPTIMIZATION_FIXTURES]
    target_log = log(target)
    cap_bin = int(target_log / BUCKET_STEP) + 1
    # (count, log-odds bucket) -> (log(hit_probability), real log(odds), ids)
    states: dict[tuple[int, int], tuple[float, float, tuple[str, ...]]] = {
        (0, 0): (0.0, 0.0, ())
    }
    for _, options in prepared:
        updated = dict(states)  # skipping this fixture is always allowed
        for (count, _), (log_hit, log_odds, path) in states.items():
            if count == limit:
                continue
            for option_odds, option_p, selection_id in options:
                new_odds = log_odds + option_odds
                new_hit = log_hit + option_p
                slot = (count + 1, min(cap_bin, floor(new_odds / BUCKET_STEP)))
                old = updated.get(slot)
                if old is None or new_hit > old[0] + 1e-12 or (
                    abs(new_hit - old[0]) <= 1e-12 and new_odds > old[1]
                ):
                    updated[slot] = (new_hit, new_odds, path + (selection_id,))
        states = updated

    feasible = [
        state for (count, _), state in states.items()
        if 1 <= count <= limit and state[1] + 1e-10 >= target_log
    ]
    if not feasible:
        # An odds-bucket may suppress a near-ceiling path. Construct the
        # actual highest-priced model-eligible combination as a last resort.
        return {
            **overview,
            "status": "PROPOSED_NOT_BOOKED",
            "portfolio_type": "HIGH_RISK_CEILING_EXPERIMENT",
            "optimization_method": "exact_model_eligible_ceiling",
            "selection_ids": actual_ceiling["ids"],
            "legs": len(actual_ceiling["ids"]),
            "indicative_odds": round(actual_ceiling["odds"], 3),
            "estimated_conservative_hit_probability": round(
                exp(actual_ceiling["log_probability"]), 12
            ),
            "fixtures_evaluated": len(prepared),
            "fixtures_with_model_probability": count_all,
            "reason": (
                "The bounded confidence search missed this narrow target. "
                "This highest-price combination is a high-risk experiment, "
                "not a reliability recommendation. Exact bookmaker verification "
                "is still required."
            ),
        }
    best = max(feasible, key=lambda item: (item[0], -len(item[2]), -item[1]))
    proposed = exp(best[1])
    return {
        **overview,
        "status": "PROPOSED_NOT_BOOKED",
        "selection_ids": list(best[2]),
        "legs": len(best[2]),
        "indicative_odds": round(proposed, 3),
        "estimated_conservative_hit_probability": round(exp(best[0]), 12),
        "fixtures_evaluated": len(prepared),
        "fixtures_with_model_probability": count_all,
        "reason": (
            "This is a bounded probability-weighted suggestion from already "
            "approved bookmaker-reference prices. Review every leg, then "
            "request a separate exact SportyBet code and live readback."
        ),
    }
