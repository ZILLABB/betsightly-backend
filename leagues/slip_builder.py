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

*The search is greedy on cost, not exhaustive.* `select_accumulator`
enumerates combinations, which is right for a five-leg tier and impossible at
thirteen. Ordering by

    cost = -log(probability) / log(odds)

buys the required log-odds as cheaply as possible in log-probability, which is
the same objective the card's selector optimises, reached in n log n instead
of combinatorially.

What it does not do is create an edge. Measured across 393 settled legs,
nothing selection can key on predicts a leg beating its own stated confidence
— so this reaches a number honestly, and says what that number is worth.
"""

import collections
import logging
import math
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Targets the UI offers. Capped at 100 deliberately: past that the leg count
# climbs fast and every leg is another slice of the bookmaker's margin, so the
# product stops being a bet and becomes a lottery ticket. 100 already needs
# fifteen legs and returns about 42 in every 100 staked.
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
# The week is twice as likely to come in and made of better picks, because 526
# fixtures simply contain more good ones than 31 do. What it costs is time: it
# settles over seven days rather than tonight. Someone who wants a result this
# evening is not making a mistake by choosing the worse odds, so both are
# offered and the difference is stated.
HORIZONS = {"today": 1, "week": POOL_DAYS}
DEFAULT_HORIZON = "week"

# Reached within this fraction of the target and it counts as a hit. Prices
# move in coarse steps, so insisting on exactly 50.0 would reject a 48.6x slip
# that is the best thing on the board.
BAND_LOW = 0.90
BAND_HIGH = 1.45


# How close two picks must be on cost before the bookmaker's cut decides
# between them. Sorting on cost alone drifted into the dearest markets on the
# board — double chance runs about two points above 1X2 — and a twelve-leg
# slip multiplies that twelve times: the week horizon returned N39 per N100
# against today's N57 largely on margin, not on merit.
_COST_TIE_BAND = 0.02


def _cost(pick: dict) -> float:
    p = max(1e-6, min(0.999, pick["confidence"]))
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
    days = HORIZONS.get(horizon, POOL_DAYS)
    # Inclusive of the last day: a "today" slip may use anything kicking off
    # before midnight, not only the next few hours.
    until = (now_dt + timedelta(days=days)).strftime("%Y-%m-%d") + "T23:59:59Z"

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


def _best_per_fixture_group(pool: list) -> list:
    best: dict = {}
    for p in sorted(pool, key=_order_key):
        key = (p["match_id"], p["market_group"])
        if key not in best:
            best[key] = p
    return sorted(best.values(), key=_order_key)


def build_slip(target: float, pool: list | None = None,
               max_legs: int = MAX_LEGS, market_cap: int | None = None,
               horizon: str = DEFAULT_HORIZON) -> dict:
    """The slip most likely to land at `target`, or an honest refusal."""
    from leagues.selection import MARKET_CAP
    cap = MARKET_CAP if market_cap is None else market_cap

    if pool is None:
        pool = _pool(horizon)
    if not pool:
        return {"ok": False, "reason": "No qualifying picks are available right now."}

    candidates = _best_per_fixture_group(pool)

    seen_fixtures: set = set()
    groups: collections.Counter = collections.Counter()
    odds, joint, legs = 1.0, 1.0, []

    for p in candidates:
        if len(legs) >= max_legs:
            break
        if p["match_id"] in seen_fixtures or groups[p["market_group"]] >= cap:
            continue
        seen_fixtures.add(p["match_id"])
        groups[p["market_group"]] += 1
        odds *= p["odds"]
        joint *= p["confidence"]
        legs.append(p)
        if odds >= target * BAND_LOW:
            break

    if odds < target * BAND_LOW:
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
            "reason": (f"The best qualifying slip right now reaches "
                       f"{odds:.1f}x — {limit}. Lowering standards to reach "
                       f"{target:g}x would not make it a better bet."),
        }

    if odds > target * BAND_HIGH:
        logger.info(f"slip for {target}x overshot to {odds:.1f}x")

    from leagues.picks import ESTIMATE_MARGIN
    # Expected return per unit staked. Every leg multiplies in another slice of
    # the book's cut, so this falls as the slip lengthens — which is the single
    # most important number on the screen and the one nobody else shows.
    ev = 1.0
    for p in legs:
        m = p.get("market_margin")
        ev *= 1.0 / (1.0 + ((ESTIMATE_MARGIN - 1.0) if m is None else m))

    return {
        "ok": True,
        "target": target,
        "odds": round(odds, 2),
        "legs": len(legs),
        "hit_probability": round(joint, 5),
        "expected_return": round(ev, 4),
        "avg_confidence": round(sum(p["confidence"] for p in legs) / len(legs), 4),
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

    built = build_slip(target, pool=_pool(horizon, force=force),
                       horizon=horizon)
    if not built.get("ok"):
        return {"status": "unavailable", "horizon": horizon, **built}

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
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "games": games,
    }

    # Book it. A slip nobody can place is only half the feature — but a failed
    # booking must not lose the slip, so this reports rather than raises.
    try:
        from leagues import sportybet
        from leagues.booking import create_booking
        out["booking"] = create_booking(games, sportybet.fetch_board())
    except Exception as e:
        logger.warning(f"slip booking failed: {e}")
        out["booking"] = {"status": "failed", "share_code": None,
                          "reason": f"Booking unavailable: {str(e)[:120]}"}
    return out
