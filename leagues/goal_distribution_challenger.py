"""Coherent full-time scoreline *challenger* for market expansion (offline only).

No trained parameters, no sportsbook quoting, no production inference changes.
The marginal last bucket absorbs rare high-goal outcomes so every derived
full-time market comes from one normalized joint probability distribution.
This is a baseline/target contract for the future Phase 11 challenger, not a
claim that independent Poisson is an adequate winning model.
"""
from __future__ import annotations

import math

MAX_EXPLICIT_GOALS = 10


def _poisson_buckets(mean: float, last: int) -> list[float]:
    if not math.isfinite(mean) or mean < 0:
        raise ValueError("expected goals must be finite and nonnegative")
    if last < 5:
        raise ValueError("last goal bucket must cover over/under 4.5")
    first = [math.exp(-mean)]
    for n in range(1, last):
        first.append(first[-1] * mean / n)
    # Bucket 'last' means last or more goals; never silently discard the tail.
    first.append(max(0.0, 1.0 - sum(first)))
    total = sum(first)
    return [value / total for value in first]


def score_grid(home_xg: float, away_xg: float,
               last: int = MAX_EXPLICIT_GOALS) -> list[list[float]]:
    """P(home=i, away=j) including tail buckets at index 'last'."""
    home = _poisson_buckets(home_xg, last)
    away = _poisson_buckets(away_xg, last)
    return [[h * a for a in away] for h in home]


def from_grid(grid: list[list[float]]) -> dict[str, float | None]:
    """All probability targets in one coherent, normalized joint FT market.

    DNB home/away here is P(win | non-draw). The separately reported draw
    probability is required when evaluating DNB odds with a push.
    """
    if not grid or not grid[0] or len(grid) != len(grid[0]):
        raise ValueError("score probability grid must be nonempty and square")
    if any(len(row) != len(grid) for row in grid):
        raise ValueError("score grid has ragged rows")
    if any(not math.isfinite(p) or p < 0 for row in grid for p in row):
        raise ValueError("score grid contains invalid probabilities")
    if abs(sum(map(sum, grid)) - 1.0) > 1e-7:
        raise ValueError("score grid probabilities do not sum to one")

    n = len(grid)
    def prob(condition) -> float:
        return sum(grid[h][a] for h in range(n) for a in range(n)
                   if condition(h, a))

    hwin = prob(lambda h, a: h > a)
    draw = prob(lambda h, a: h == a)
    awin = prob(lambda h, a: h < a)
    non_draw = hwin + awin
    p = {
        "home_win": hwin,
        "draw": draw,
        "away_win": awin,
        "home_or_draw": hwin + draw,
        "away_or_draw": awin + draw,
        "home_or_away": non_draw,
        "dnb_home": hwin / non_draw if non_draw > 1e-12 else None,
        "dnb_away": awin / non_draw if non_draw > 1e-12 else None,
        "over_0_5": prob(lambda h, a: h + a >= 1),
        "over_1_5": prob(lambda h, a: h + a >= 2),
        "over_2_5": prob(lambda h, a: h + a >= 3),
        "over_3_5": prob(lambda h, a: h + a >= 4),
        "over_4_5": prob(lambda h, a: h + a >= 5),
        "btts_yes": prob(lambda h, a: h >= 1 and a >= 1),
        "home_over_0_5": prob(lambda h, a: h >= 1),
        "home_over_1_5": prob(lambda h, a: h >= 2),
        "away_over_0_5": prob(lambda h, a: a >= 1),
        "away_over_1_5": prob(lambda h, a: a >= 2),
    }
    for threshold in ("0_5", "1_5", "2_5", "3_5", "4_5"):
        p[f"under_{threshold}"] = 1.0 - p[f"over_{threshold}"]
    for side in ("home", "away"):
        for threshold in ("0_5", "1_5"):
            p[f"{side}_under_{threshold}"] = 1.0 - p[f"{side}_over_{threshold}"]
    p["btts_no"] = 1.0 - p["btts_yes"]
    return p


def probabilities(home_xg: float, away_xg: float) -> dict[str, float | None]:
    """Derived FT probabilities for comparison against the production model."""
    return from_grid(score_grid(home_xg, away_xg))


def settlement_labels(home_goals: int, away_goals: int) -> dict[str, int | None]:
    """Settled outcome labels from authorized FT scores (no bookmaker data).

    None means a draw/push for Draw No Bet, NOT a losing outcome. This can be
    used only with data whose provenance and training rights are established.
    """
    if (type(home_goals) is not int or type(away_goals) is not int
            or home_goals < 0 or away_goals < 0):
        raise ValueError("settled full-time scores must be nonnegative integers")
    home, away = home_goals, away_goals
    total = home + away
    home_win = int(home > away)
    draw = int(home == away)
    away_win = int(home < away)
    labels: dict[str, int | None] = {
        "home_win": home_win,
        "draw": draw,
        "away_win": away_win,
        "home_or_draw": int(home >= away),
        "away_or_draw": int(away >= home),
        "home_or_away": int(home != away),
        "dnb_home": None if draw else home_win,
        "dnb_away": None if draw else away_win,
        "btts_yes": int(home >= 1 and away >= 1),
        "btts_no": int(not (home >= 1 and away >= 1)),
    }
    for threshold in range(5):
        name = f"{threshold}_5"
        labels[f"over_{name}"] = int(total >= threshold + 1)
        labels[f"under_{name}"] = int(total <= threshold)
    for side, goals in (("home", home), ("away", away)):
        for threshold in (0, 1):
            name = f"{side}_over_{threshold}_5"
            labels[name] = int(goals >= threshold + 1)
            labels[f"{side}_under_{threshold}_5"] = int(goals <= threshold)
    return labels
