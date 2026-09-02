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

# Home-team and away-team goal markets are separate calibration groups, but
# to a bettor they are the same exposure: "this team scores". Counting the
# two groups separately allowed as many as six of those legs on one ticket.
TEAM_TO_SCORE_GROUPS = {"team_goals_home", "team_goals_away"}
TEAM_TO_SCORE_CAP = 3


def exposure_group(market_group: str) -> str:
    """Group markets by the risk pattern a bettor is actually taking."""
    if market_group in TEAM_TO_SCORE_GROUPS:
        return "team_to_score"
    return market_group

# How close two slips have to score before the bookmaker's margin decides
# between them. Expected value already moves with price — a tighter market
# quotes a longer price for the same probability, so it scores higher without
# any help. What it cannot do is separate slips whose prices are *estimated*,
# because an estimated price is our own probability plus a flat margin and
# every such slip returns exactly 1/ESTIMATE_MARGIN. On a board that mixes
# real and estimated quotes the EV ranking is therefore partly blind, and this
# band lets the observed margin break the ties it cannot see.
_SCORE_TIE_BAND = 0.01


def _mean_margin(combo) -> float:
    """Average book cut across a slip's legs. Lower is better."""
    from leagues.picks import ESTIMATE_MARGIN
    total = 0.0
    for p in combo:
        m = p.get("market_margin")
        total += (ESTIMATE_MARGIN - 1.0) if m is None else m
    return total / len(combo) if combo else 0.0


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

# Exact enumeration grows combinatorially (45 choose 8 is 215 million). A
# live SportyBet board can fill every price band, so leaving all stratified
# candidates in the search pinned a worker for minutes and pushed the process
# close to a 2 GB container limit. Eighteen candidates still cover every band
# and allow an eight-leg slip, while bounding the full search below 107k
# combinations. Small pools remain completely exact.
_MAX_SEARCH_CANDIDATES = 18


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


def _bound_search_space(candidates: list[dict]) -> list[dict]:
    """Keep a diverse, bounded candidate set for exact combination search.

    Round-robin selection across price bands avoids recreating the old bug
    where a flat top-N list contained only short-priced goals markets and
    could not reach the requested multiplier.
    """
    if len(candidates) <= _MAX_SEARCH_CANDIDATES:
        return candidates

    buckets = [
        sorted(
            (p for p in candidates if lo <= p["odds"] < hi),
            key=_cost,
        )
        for lo, hi in _PRICE_BANDS
    ]
    bounded: list[dict] = []
    index = 0
    while len(bounded) < _MAX_SEARCH_CANDIDATES:
        progressed = False
        for bucket in buckets:
            if index < len(bucket):
                bounded.append(bucket[index])
                progressed = True
                if len(bounded) >= _MAX_SEARCH_CANDIDATES:
                    break
        if not progressed:
            break
        index += 1
    return sorted(bounded, key=_cost)


def select_accumulator(
    picks: list[dict],
    target_odds: float,
    max_picks: int = 5,
    min_confidence: float = 0.50,
    min_ev: float = 0.0,
    max_leg_ev: float = 1.04,
    prefer_real_odds: bool = True,
    prefer: str = "ev",
    band_low: float = 0.80,
    band_high: float = 1.45,
) -> tuple[list[dict], float, float]:
    """Pick the best slip that reaches `target_odds`.

    `prefer` chooses what "best" means.

    "ev" — payout times the chance it lands. Right for a standalone slip: a
    cheap long shot cannot beat a fairly priced short one just by having more
    legs.

    "joint" — the chance it lands, ignoring payout beyond the target band.
    Right for a link in a chain, where every day has to come in and a day that
    misses ends the run. Maximising value there quietly prefers the riskier
    day: inside a 2x band a slip paying 2.33x and landing 44% scores a higher
    EV than one paying 1.30x and landing 69%, so the chain kept being built
    from the least likely days available.

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
    candidates = _bound_search_space(_stratify(candidates))

    # Widened from 0.85. With every leg capped at 1.45, the multiplier a slip
    # can reach moves in coarse steps — seven legs reached 8.25x against a
    # lower bound of 8.5x, so a perfectly good slip was discarded for landing
    # 3% short of a round number. Undershooting the target slightly is a far
    # better outcome than publishing nothing, and the expected-value floor
    # still decides whether the slip is worth staking at all.
    lo_band = target_odds * band_low
    hi_band = target_odds * band_high

    best: tuple[list[dict], float, float] | None = None
    best_key: tuple | None = None
    fallback: tuple[list[dict], float, float] | None = None
    fallback_key: tuple | None = None

    for size in range(1, min(max_picks, len(candidates)) + 1):
        for combo in itertools.combinations(candidates, size):
            groups: dict[str, int] = {}
            exposures: dict[str, int] = {}
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
                exposure = exposure_group(g)
                exposures[exposure] = exposures.get(exposure, 0) + 1
                if (exposure == "team_to_score"
                        and exposures[exposure] > TEAM_TO_SCORE_CAP):
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
            # A ceiling as well as a floor, because this search maximises
            # expected value and will therefore stack whichever legs the model
            # most disagrees with the bookmaker about. A slip claiming to beat
            # the market by a quarter is not a find, it is several correlated
            # mistakes multiplied together, and the search reaches for exactly
            # that combination by construction.
            #
            # Applied per leg rather than to the slip, because expected value
            # compounds: eight legs each a credible 3% above the market make
            # 1.27 together, and a flat slip-level cap refused every one of
            # them. That emptied the 10 odds tier on the richest day of the
            # week — 794 qualifying picks and no slip published — while
            # letting a two-leg slip through at the same per-leg optimism.
            #
            # The geometric mean asks the question that actually matters: how
            # far above the market is the *typical* leg? Three percent is
            # generous for a model measured at roughly five percent skill on
            # one market and none on goals; seven, which is what the
            # unconstrained search reached for, is not.
            if ev ** (1.0 / size) > max_leg_ev:
                continue
            score = joint if prefer == "joint" else ev
            # Score first, banded; the cheaper slip wins ties. Comparing the
            # raw score alone would leave margin unused, because two slips
            # never score identically to full float precision even when they
            # are the same product for staking purposes.
            # Score first, banded; then how much of the slip can actually be
            # booked; then the cheaper price. Bookability sits above margin
            # because a tier where one leg has no SportyBet counterpart gets
            # no code at all — partial slips are refused — so an unbookable
            # leg costs far more than a point of margin ever saves.
            bookable = sum(1 for p in combo if p.get("bookable"))
            key = (round(score / _SCORE_TIE_BAND),
                   bookable == len(combo),
                   bookable,
                   -_mean_margin(combo))

            if lo_band <= combined <= hi_band:
                if best_key is None or key > best_key:
                    best_key = key
                    best = (list(combo), combined, joint)
            elif combined > hi_band:
                # Overshoots the band but still valid — keep as a backup
                if fallback_key is None or key > fallback_key:
                    fallback_key = key
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
        # Confidence banded, then the cheaper market, then a real quote, then
        # value. Banding matters here for the same reason it does on Over 1.5:
        # this tier stakes a single pick, so it pays the margin exactly once
        # and a point saved is a point kept.
        key=lambda p: (-round(p["confidence"] / _SCORE_TIE_BAND / 2),
                       _mean_margin([p]),
                       not p["odds_are_real"],
                       -p["expected_value"]),
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
                        max_picks: int = 6) -> tuple[list[dict], float, float]:
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
        # The chain needs every day to land, so the safest day that reaches the
        # target wins — not the most valuable one. Optimising value here was
        # picking a 44% day over a 69% day because it paid more, which is how
        # you build a chain out of its least likely links.
        prefer="joint",
        # The product promises a 2x–3x daily slot. Two strong legs normally
        # win, but up to six shorter, safer prices are allowed when they have
        # a higher joint chance. The ceiling is permission, not a quota.
        band_low=1.0,
        band_high=1.5,
    )
