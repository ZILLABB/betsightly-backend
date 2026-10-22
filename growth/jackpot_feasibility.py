"""Exact, read-only ceiling for distinct fixtures with valid model reliability."""
from math import exp, isfinite, log


def model_ceiling(candidates: list[dict], max_legs: int) -> dict:
    from growth.jackpot_optimizer import _probability, _unique_fixtures

    groups = _unique_fixtures(candidates)
    best = []
    omitted = 0
    for rows in groups.values():
        eligible = [row for row in rows if _probability(row) is not None]
        if not eligible:
            omitted += 1
            continue
        row = max(eligible, key=lambda r: (
            float(r["odds"]), _probability(r), str(r["selection_id"])
        ))
        best.append(row)
    best.sort(key=lambda r: (-float(r["odds"]), str(r["selection_id"])))
    chosen = best[:max_legs]
    summed_odds = sum(log(float(row["odds"])) for row in chosen)
    # Clamping avoids inf in JSON; targets never exceed 100000x.
    ceiling = exp(min(summed_odds, log(1e12)))
    probabilities = [_probability(row) for row in chosen]
    return {
        "odds": ceiling,
        "ids": [str(row["selection_id"]) for row in chosen],
        "log_probability": sum(log(p) for p in probabilities),
        "eligible_fixtures": len(best),
        "omitted_fixtures": omitted,
    }
