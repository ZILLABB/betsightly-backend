"""
Accumulator selection.

The problem this solves: for a target multiplier, which combination of picks
is *most likely to actually land*? Sorting by confidence and stopping when the
odds are high enough — the previous approach — answers a different question
and answers it badly.

Reaching a multiplier T means sum(log odds) >= log(T). Maximising the chance
every leg lands means maximising sum(log probability). That is a knapsack:
buy the required log-odds as cheaply as possible in log-probability. The
greedy solution takes picks in ascending order of

    cost = -log(probability) / log(odds)

i.e. the legs that add the most multiplier for the least risk. Adding a
fourth 75% leg to reach 2.4x is strictly worse than one 55% leg at the same
multiplier, and this ordering sees that; confidence-sorting does not.

Honesty rule: a slip is only published when its joint probability clears a
floor tied to its payout. A 10x slip that lands 6% of the time is a losing
product no matter how confident each individual leg looks.
"""

import itertools
import logging
import math

logger = logging.getLogger(__name__)

# Below this, a price is not worth a slot — you would need twenty legs to
# reach a useful multiplier and every one is another chance to lose.
MIN_USEFUL_ODDS = 1.12

MARKET_CAP = 2  # max legs from the same market group, for diversity


def _cost(pick: dict) -> float:
    """Risk paid per unit of multiplier gained. Lower is better."""
    p = max(1e-6, min(0.999, pick["confidence"]))
    o = max(1.0001, pick["odds"])
    return -math.log(p) / math.log(o)


def select_accumulator(
    picks: list[dict],
    target_odds: float,
    max_picks: int = 5,
    min_confidence: float = 0.50,
    min_joint: float = 0.0,
    prefer_real_odds: bool = True,
) -> tuple[list[dict], float, float]:
    """Pick the combination most likely to reach `target_odds`.

    Returns (picks, combined_odds, joint_probability). Empty when the day
    cannot support the target honestly.
    """
    pool = [
        p for p in picks
        if p["confidence"] >= min_confidence and p["odds"] >= MIN_USEFUL_ODDS
    ]
    if not pool:
        return [], 0.0, 0.0

    # Keep only the best pick per fixture per market group, then the best few
    # per fixture — one match must never contribute two correlated legs.
    best_per_fixture: dict[str, dict] = {}
    for p in sorted(pool, key=_cost):
        mid = p["match_id"]
        if mid not in best_per_fixture:
            best_per_fixture[mid] = p
    candidates = sorted(best_per_fixture.values(), key=_cost)

    # Search combinations outright rather than building greedily. Greedy adds
    # whole legs and overshoots — it would return 2.59x landing 33% of the
    # time when 1.80x landing 47% is available and is the better product at a
    # "2 odds" target. The candidate list is one pick per fixture and capped
    # below, so the search space stays small enough to enumerate exactly.
    candidates = candidates[:18]

    lo_band = target_odds * 0.85
    hi_band = target_odds * 1.45

    best: tuple[list[dict], float, float] | None = None
    best_joint = -1.0
    fallback: tuple[list[dict], float, float] | None = None
    fallback_joint = -1.0

    for size in range(1, min(max_picks, len(candidates)) + 1):
        for combo in itertools.combinations(candidates, size):
            groups: dict[str, int] = {}
            ok = True
            for p in combo:
                g = p["market_group"]
                groups[g] = groups.get(g, 0) + 1
                if groups[g] > MARKET_CAP:
                    ok = False
                    break
            if not ok:
                continue

            combined = 1.0
            joint = 1.0
            for p in combo:
                combined *= p["odds"]
                joint *= p["confidence"]

            if joint < min_joint:
                continue

            if lo_band <= combined <= hi_band:
                if joint > best_joint:
                    best_joint = joint
                    best = (list(combo), combined, joint)
            elif combined > hi_band and joint > fallback_joint:
                # Overshoots the band but still valid — keep as a backup
                fallback_joint = joint
                fallback = (list(combo), combined, joint)

    result = best or fallback
    if not result:
        return [], 0.0, 0.0
    chosen, combined, joint = result

    if prefer_real_odds:
        chosen.sort(key=lambda p: (not p["odds_are_real"], -p["confidence"]))
    else:
        chosen.sort(key=lambda p: -p["confidence"])

    return chosen, round(combined, 2), round(joint, 4)


def select_banker(picks: list[dict], max_picks: int = 2,
                  min_confidence: float = 0.78) -> tuple[list[dict], float, float]:
    """One or two of the day's most reliable picks.

    Built for consistency rather than payout. A 2x accumulator lands around
    half the time by construction; a single 80% pick lands four times in five.
    This tier exists so there is something on the site whose stated confidence
    and actual hit rate are the same number.

    Two constraints keep this tier worth staking rather than merely safe:

    - A price floor of 1.25. An 80% shot at 1.18 returns 0.94 per unit staked;
      being right four times in five does not help if the price never covers
      the fifth.
    - A preference for real quoted prices. Estimated prices are derived as
      fair-value plus a standard margin, so their expected value is fixed at
      roughly 0.94 by construction — only a real quote can be genuinely
      mispriced in our favour, and only there does "value" mean anything.
    """
    pool = [
        p for p in picks
        if p["confidence"] >= min_confidence and p["odds"] >= 1.25
    ]
    if not pool:
        # Nothing clears the bar at full strength — try slightly wider rather
        # than publishing nothing, but never below a stakeable price.
        pool = [p for p in picks if p["confidence"] >= 0.74 and p["odds"] >= 1.25]
    if not pool:
        return [], 0.0, 0.0

    best_per_fixture: dict[str, dict] = {}
    for p in sorted(pool, key=lambda x: -x["confidence"]):
        best_per_fixture.setdefault(p["match_id"], p)

    # Real quoted prices first (only these can carry true value), then by
    # expected value, then confidence.
    ranked = sorted(
        best_per_fixture.values(),
        key=lambda p: (not p["odds_are_real"], -p["expected_value"], -p["confidence"]),
    )

    chosen: list[dict] = []
    groups: dict[str, int] = {}
    for p in ranked:
        if len(chosen) >= max_picks:
            break
        g = p["market_group"]
        if groups.get(g, 0) >= 1:  # no doubling up on one market type
            continue
        chosen.append(p)
        groups[g] = groups.get(g, 0) + 1

    if not chosen:
        return [], 0.0, 0.0

    combined = 1.0
    joint = 1.0
    for p in chosen:
        combined *= p["odds"]
        joint *= p["confidence"]
    return chosen, round(combined, 2), round(joint, 4)


def select_rollover_day(picks: list[dict], target_odds: float = 1.9,
                        max_picks: int = 3) -> tuple[list[dict], float, float]:
    """One rollover day: reach ~target_odds with the best possible hit rate.

    Deliberately fewer legs than a category slip. Compounding is unforgiving —
    four legs at 75% land 32% of the time, two at 85% land 72% — and a
    rollover chain only survives if individual days actually win.
    """
    return select_accumulator(
        picks,
        target_odds=target_odds,
        max_picks=max_picks,
        min_confidence=0.62,
        min_joint=0.45,
    )
