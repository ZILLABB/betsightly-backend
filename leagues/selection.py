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

Honesty rule: a slip is only published when it clears an expected-value floor —
payout multiplied by the chance it lands. This used to be a floor on the joint
probability alone, which cannot tell a good slip from a bad one because it
never looks at the price: 6% on a 20x slip is excellent and 6% on an 8x slip
is dreadful, and a joint floor treats them identically.

Expected value is also the honest number to gate on once confidences are
calibrated. Every extra leg multiplies in another slice of the bookmaker's
margin, so a long slip is worse than a short one at the same payout, and an EV
floor sees that automatically where a joint floor had to be hand-tuned per
tier — and was tuned, originally, against confidences we now know were about
seven points hot.
"""

import itertools
import logging
import math

logger = logging.getLogger(__name__)

# Below this, a price is not worth a slot — you would need twenty legs to
# reach a useful multiplier and every one is another chance to lose.
MIN_USEFUL_ODDS = 1.12

# Max legs from the same market group. Every leg is on a different fixture
# (enforced separately), so two Over 1.5 picks in different matches are close
# to independent — the cap is about not betting the whole slip on one market
# being right, not about correlation between the legs themselves.
#
# It was 2, which turned out to be the binding constraint on ordinary days.
# Fixtures with no bookmaker odds fall back to league base rates, and those
# give a home win around 47%, under the confidence floor — so an unpriced slate
# produces goals picks and almost nothing else. On 12 August, 31 of 37
# available picks were goals, and a cap of 2 held every possible slip to 3.87x
# against a 5x band starting at 4.25x. The tier reported "not enough matches"
# on a day with 35 of them.
MARKET_CAP = 3


def _cost(pick: dict) -> float:
    """Risk paid per unit of multiplier gained. Lower is better."""
    p = max(1e-6, min(0.999, pick["confidence"]))
    o = max(1.0001, pick["odds"])
    return -math.log(p) / math.log(o)


# Price bands the candidate list is drawn from, so the search always has legs
# long enough to reach a high target. Open-ended at the top.
_PRICE_BANDS = [(1.12, 1.30), (1.30, 1.50), (1.50, 1.80), (1.80, 2.40), (2.40, 99.0)]
# Raised from 5. A 65% confidence floor caps every estimated price at 1.45
# (the price is 1/confidence plus margin), so the bands above 1.50 are empty
# and a long slip has to be built from many short legs rather than a few long
# ones. Taking only five per band left the search ten candidates to reach 10x
# from, topping out at 8.25x, while 69 usable picks sat unexamined in the
# 1.30-1.50 band.
_PER_BAND = 9
# No group may take a whole band, so a slip is never one market end to end.
_PER_BAND_GROUP = 4


def _stratify(candidates: list[dict]) -> list[dict]:
    """Best few candidates per price band, keeping the bands market-diverse.

    Cost favours short prices, so drawing a flat top-N produced a list of
    nothing but cheap goals legs. Banding by price restores the long legs a
    high target needs; capping each group within a band stops one market from
    filling the list and running into MARKET_CAP.
    """
    out: list[dict] = []
    for lo, hi in _PRICE_BANDS:
        band = sorted((p for p in candidates if lo <= p["odds"] < hi), key=_cost)
        taken: dict[str, int] = {}
        picked = 0
        for p in band:
            if picked >= _PER_BAND:
                break
            g = p["market_group"]
            if taken.get(g, 0) >= _PER_BAND_GROUP:
                continue
            taken[g] = taken.get(g, 0) + 1
            out.append(p)
            picked += 1
    return sorted(out, key=_cost)


def select_accumulator(
    picks: list[dict],
    target_odds: float,
    max_picks: int = 5,
    min_confidence: float = 0.50,
    min_ev: float = 0.0,
    prefer_real_odds: bool = True,
) -> tuple[list[dict], float, float]:
    """Pick the best slip that reaches `target_odds`.

    "Best" is expected value — payout times the chance it lands — rather than
    the chance alone, so a cheap long shot cannot beat a fairly priced short
    one just by having more legs.

    Returns (picks, combined_odds, joint_probability). Empty when the day
    cannot support the target honestly.
    """
    pool = [
        p for p in picks
        if p["confidence"] >= min_confidence and p["odds"] >= MIN_USEFUL_ODDS
    ]
    if not pool:
        return [], 0.0, 0.0

    # Keep the best pick per fixture *per market group*. Collapsing to a single
    # pick per fixture — which is what this used to do — silently destroyed the
    # search: goals picks always carry the lowest cost, so every fixture
    # contributed its Over 1.5 leg and nothing else, leaving a candidate list
    # that was 100% goals. With MARKET_CAP allowing two legs per group that
    # capped any slip at two legs and about 2.9x, so the 5x and 10x tiers came
    # back empty no matter how the gates were tuned. One leg per fixture is
    # still enforced, but during the combination search below, where it can be
    # satisfied without throwing away the market diversity first.
    best_by_fixture_group: dict[tuple[str, str], dict] = {}
    for p in sorted(pool, key=_cost):
        key = (p["match_id"], p["market_group"])
        if key not in best_by_fixture_group:
            best_by_fixture_group[key] = p
    candidates = sorted(best_by_fixture_group.values(), key=_cost)

    # Search combinations outright rather than building greedily. Greedy adds
    # whole legs and overshoots — it would return 2.59x landing 33% of the
    # time when 1.80x landing 47% is available and is the better product at a
    # "2 odds" target. The candidate list is one pick per fixture and capped
    # below, so the search space stays small enough to enumerate exactly.
    #
    # The cap is applied within price bands rather than to one list sorted by
    # cost. Cost favours short prices by construction, so a flat top-N was
    # returning eighteen legs priced around 1.2 and no combination of them
    # could reach 5x or 10x at all — those tiers came back empty however the
    # gates were set. Banding guarantees the search can actually buy the
    # multiplier it is being asked for.
    candidates = _stratify(candidates)

    # Widened from 0.85. With every leg capped at 1.45, the multiplier a slip
    # can reach moves in coarse steps — seven legs reached 8.25x against a
    # lower bound of 8.5x, so a perfectly good slip was discarded for landing
    # 3% short of a round number. Undershooting the target slightly is a far
    # better outcome than publishing nothing, and the expected-value floor
    # still decides whether the slip is worth staking at all.
    lo_band = target_odds * 0.80
    hi_band = target_odds * 1.45

    best: tuple[list[dict], float, float] | None = None
    best_ev = -1.0
    fallback: tuple[list[dict], float, float] | None = None
    fallback_ev = -1.0

    for size in range(1, min(max_picks, len(candidates)) + 1):
        for combo in itertools.combinations(candidates, size):
            groups: dict[str, int] = {}
            fixtures_used: set[str] = set()
            ok = True
            for p in combo:
                # Two legs off the same match are correlated, not independent —
                # multiplying their probabilities would overstate the slip.
                if p["match_id"] in fixtures_used:
                    ok = False
                    break
                fixtures_used.add(p["match_id"])
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

            ev = combined * joint
            if ev < min_ev:
                continue

            if lo_band <= combined <= hi_band:
                if ev > best_ev:
                    best_ev = ev
                    best = (list(combo), combined, joint)
            elif combined > hi_band and ev > fallback_ev:
                # Overshoots the band but still valid — keep as a backup
                fallback_ev = ev
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


def select_banker(picks: list[dict], max_picks: int = 1,
                  min_confidence: float = 0.72,
                  min_price: float = MIN_USEFUL_ODDS) -> tuple[list[dict], float, float]:
    """The single most reliable pick of the day.

    One pick, not two. Two legs multiply: on 14 August the best pair came out
    at 79% and 80%, which is a 63% chance of the tier landing — lower than the
    2 Odds slip that day and well under what a tier called "Most Reliable"
    implies. Combining picks is what every other tier already does; the point
    of this one is the number on it being the number that happens.

    Built for consistency rather than payout: a 2x accumulator lands about half
    the time by construction, where a single 80% pick lands four times in five.
    This tier exists so the site has something whose stated confidence and
    actual hit rate are the same number.

    The old rule asked for confidence >= 78% *and* a price >= 1.25, and those
    two can never both hold. An estimated price is (1/p) plus margin, so it
    falls as confidence rises: the price drops below 1.25 once confidence
    passes 75.8%, which is *below* the 78% the tier demanded. The conditions
    described a number and its opposite, so the pool was empty on any day
    without a real quote — and a real quote at 78% is priced near 1.19 too, so
    it was empty on those days as well. The tier had simply stopped existing.

    A price floor also does nothing for value here, which was the reasoning
    behind it. Where the price is derived from our own probability, expected
    value is fixed at 1/margin regardless of what the probability is: an 80%
    shot at 1.18 and a 75% shot at 1.25 both return about 0.94. The floor was
    buying nothing and excluding exactly the safe picks the tier is for.

    So confidence leads and the price floor only rules out prices too short to
    be worth staking at all. Real quotes break ties, since only a real price
    can be genuinely mispriced in our favour.
    """
    pool = [
        p for p in picks
        if p["confidence"] >= min_confidence and p["odds"] >= min_price
    ]
    if not pool:
        # Nothing clears the bar at full strength — widen a little rather than
        # publishing nothing, but never below a stakeable price.
        pool = [p for p in picks
                if p["confidence"] >= 0.68 and p["odds"] >= min_price]
    if not pool:
        return [], 0.0, 0.0

    best_per_fixture: dict[str, dict] = {}
    for p in sorted(pool, key=lambda x: -x["confidence"]):
        best_per_fixture.setdefault(p["match_id"], p)

    # Safest first — this tier is about landing, not edge. A real quote wins a
    # tie because it is the only kind of price that can carry true value.
    ranked = sorted(
        best_per_fixture.values(),
        key=lambda p: (-p["confidence"], not p["odds_are_real"], -p["expected_value"]),
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


def select_rollover_day(picks: list[dict], target_odds: float = 2.0,
                        max_picks: int = 3) -> tuple[list[dict], float, float]:
    """One rollover day, aiming at `target_odds` with the best hit rate.

    Odds and probability are inverses, so a daily target is a choice about how
    long the chain can be, not just about payout. With the 65% floor a leg is
    priced at most 1.45, which means roughly:

        1.13x/day  84% a day   10 days completes 17%    pays  3.4x
        2.00x/day  45% a day   10 days completes 0.03%  pays 1024x
        2.00x/day  45% a day    3 days completes 9.1%   pays  8.0x

    A ten-day chain at 2x is not a hard challenge, it is a rounding error — the
    previous version aimed at 1.9x over ten days and went 0 for 4 with every
    loss caused by the second leg. Two odds a day is a perfectly good target;
    it just has to be paired with a chain short enough to finish, which is why
    TARGET_DAYS came down with it.
    """
    return select_accumulator(
        picks,
        target_odds=target_odds,
        max_picks=max_picks,
        min_confidence=0.65,
        # Two legs give up about 11% to the margin; below this the day is not
        # worth staking however good the multiplier looks.
        min_ev=0.85,
    )
