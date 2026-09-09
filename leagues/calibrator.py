"""
Empirical confidence calibration.

Why this exists
---------------
The published confidences were running about 7 points hot: legs promised 73.3%
and landed 66.4% across 137 settled outcomes. The first suspicion was a broken
goals model, but that turned out not to be it — checking the Poisson against
655 real finished matches, it reproduces the measured league rates almost
exactly (Over 1.5 out by +0.9 points, Over 2.5 by -1.5, BTTS by +0.3).

So the model is close to unbiased *on the population of all fixtures*, while
being clearly over-confident *on the fixtures we choose to publish*. The two
statements are only compatible one way: the per-fixture estimates carry far
more uncertainty than the published number admits, and selection turns that
uncertainty into realised over-confidence. Per-league measured rates swing
±10-20 points on 10-80 match samples, and picking the highest-confidence
combination that reaches a target multiplier preferentially picks whichever
leagues currently *look* best — which is partly whichever estimates are
currently noisiest in our favour.

The measured damage is very uneven, which is the useful part:

    market_group   n    promised   actual    gap
    btts          17      58.9%    41.2%   +17.8
    goals         46      75.6%    69.6%    +6.1
    match_result  17      68.1%    70.6%    -2.5

Match result — the one anchored to real bookmaker prices — is fine, slightly
conservative even. The unpriced markets we extrapolate ourselves are where the
confidence is invented, and BTTS is worse than a coin flip against a 59% claim.

What it does
------------
Fits a shift in log-odds space, per market group, so that the confidences we
publish match the rate we actually hit. Two levels, because 137 legs is not
enough to trust any single group on its own:

- a global shift fitted across every settled leg,
- a per-group shift fitted on that group, then pulled back toward the global
  one by sample size (a group with SHRINK_K legs gets half its own effect).

Fitting on *settled published legs* is deliberate: that population already
carries the selection effect, so correcting against it removes model bias and
selection bias together, without having to model either separately.

The correction is applied before selection, not just before display, so it
changes which games get picked rather than only relabelling the same ones.

Bounds: a group can be pulled down hard but only nudged up (MAX_UP), because
inflating confidence on a thin winning streak is how a model talks itself into
a losing one. With no data the whole thing is the identity function.
"""

import json
import logging
import math
import time
from pathlib import Path

from leagues.policy_version import (
    POLICY_PRIOR_STRENGTH,
    PUBLISHED_SELECTION_POLICY_VERSION,
    policy_weight,
    sample_readiness,
)

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).parent / "data" / "calibration_fit.json"
REFIT_TTL = 6 * 3600

# A group with this many settled legs is weighted 50/50 against the global fit.
SHRINK_K = 40
# Likewise for the global fit against "no correction at all".
GLOBAL_K = 60

# Asymmetric on purpose — see module docstring. The upward bound is a backstop
# only; _regularised keeps a winning streak from reaching for it.
MAX_DOWN = -1.30
MAX_UP = 0.25

# Below this many legs a group has nothing to say and just inherits the global.
MIN_GROUP_N = 6

_MEM: dict = {"fit": None, "ts": 0.0}


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _solve_shift(legs: list[tuple[float, bool]]) -> float:
    """Shift b in log-odds space that makes predicted volume match reality.

    Solves sum(sigmoid(logit(p_i) + b)) == sum(y_i). For a fixed slope this is
    also the maximum-likelihood intercept, so the cheap moment-matching
    solution and the principled one coincide. The sum is strictly increasing
    in b, so bisection cannot miss.
    """
    if not legs:
        return 0.0
    target = sum(1 for _, won in legs if won)
    logits = [_logit(p) for p, _ in legs]

    def predicted(b: float) -> float:
        return sum(_sigmoid(l + b) for l in logits)

    lo, hi = -6.0, 6.0
    # All-won or all-lost samples run to the rails; the clamp handles it.
    if predicted(hi) < target:
        return hi
    if predicted(lo) > target:
        return lo
    for _ in range(60):
        mid = (lo + hi) / 2
        if predicted(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _regularised(sub: list[tuple[float, bool]]) -> list[tuple[float, bool]]:
    """Add one won and one lost pseudo-leg at the group's mean prediction.

    A group that has won every leg does not identify a shift — the likelihood
    increases without bound and the solver simply runs to the rail, leaving
    the clamp to invent a number. Double chance did exactly this at 16 from
    16, which asks for the largest upward correction allowed on a run that a
    genuine 85% market produces 7% of the time anyway.

    One win and one loss at the group's own mean keeps the fit finite and
    honest: a perfect record still pulls upward, but like 17 from 18 rather
    than like certainty.
    """
    if not sub:
        return sub
    mean_p = sum(p for p, _ in sub) / len(sub)
    return list(sub) + [(mean_p, True), (mean_p, False)]


def _collect_observations() -> list[dict]:
    """Unique fixture-market forecasts across public tiers and Rollover."""
    try:
        from leagues.forecast_observations import collect_forecast_observations
        return collect_forecast_observations(limit_days=365)
    except Exception as exc:
        logger.debug(f"calibration observations unavailable ({exc})")
        return []


def _collect_legs() -> list[tuple[float, bool, str]]:
    """Compatibility view of the deduplicated observations."""
    return [
        (row["raw_probability"], row["won"], _group_of(row.get("market")))
        for row in _collect_observations()
    ]


def _raw_conf(leg: dict) -> float | None:
    """The probability the correction was applied *to*, for this leg.

    Legs published before calibration existed have no `raw_confidence`, and
    for those the stored confidence is itself uncorrected — so falling back to
    it is exactly right, and old and new legs can be pooled in one fit.
    """
    v = leg.get("raw_confidence")
    if v is None:
        v = leg.get("confidence")
    return float(v) if v is not None else None


def _calibration_group(leg: dict) -> str:
    """Which calibration cell a settled leg belongs to.

    Derived from the leg's own market rather than the stored `market_group`,
    because that field records the *diversity* grouping, which deliberately
    lumps overs and unders together. Calibration needs them apart — see
    CALIBRATION_GROUP in picks.py.
    """
    # Rollover stores the market *group* under "market" and the specific
    # market under "market_key", so prefer the latter where it exists. Without
    # it a rollover goals leg lands in a cell named "goals", which matches no
    # calibration group at all and quietly drops out of every fit.
    market = leg.get("market_key") or leg.get("market")
    if market:
        try:
            from leagues.picks import CALIBRATION_GROUP
            if market in CALIBRATION_GROUP:
                return CALIBRATION_GROUP[market]
        except Exception:
            pass
    return leg.get("market_group") or _group_of(market)


def _group_of(market: str | None) -> str:
    if not market:
        return "unknown"
    try:
        from leagues.picks import CALIBRATION_GROUP
        return CALIBRATION_GROUP.get(market, market)
    except Exception:
        return market


def fit_calibration(force: bool = False) -> dict:
    """Fit and cache the correction. Cheap enough to run on a timer."""
    now = time.time()
    if not force and _MEM["fit"] is not None and (now - _MEM["ts"]) < REFIT_TTL:
        return _MEM["fit"]

    if not force and CACHE_PATH.exists():
        try:
            blob = json.loads(CACHE_PATH.read_text())
            if now - blob.get("ts", 0) < REFIT_TTL:
                _MEM.update({"fit": blob["fit"], "ts": now})
                return blob["fit"]
        except Exception:
            pass

    observations = _collect_observations()
    fit = _fit_observations(observations, now)

    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps({"ts": now, "fit": fit}, indent=2))
    except Exception:
        pass

    _MEM.update({"fit": fit, "ts": now})
    logger.info(
        f"Calibration fitted on {fit['n']} unique forecasts: "
        f"global={fit['global']:+.3f}, removed={fit.get('duplicates_removed', 0)}, "
        + ", ".join(f"{g}={v['shift']:+.3f}(n={v['n']})"
                    for g, v in fit.get("groups", {}).items())
    )
    return fit


def _cohort_stats(rows: list[dict]) -> dict:
    n = len(rows)
    return {
        "n": n,
        "promised": (sum(row["raw_probability"] for row in rows) / n
                     if n else None),
        "actual": (sum(bool(row["won"]) for row in rows) / n if n else None),
    }


def _fit_observations(observations: list[dict], fitted_at: float = 0.0) -> dict:
    """Hierarchical fit with continuously increasing current-policy weight."""
    total = len(observations)
    current = [row for row in observations if row.get("policy_version")
               == PUBLISHED_SELECTION_POLICY_VERSION]
    historical = [row for row in observations if row.get("policy_version")
                  != PUBLISHED_SELECTION_POLICY_VERSION]
    current_weight = policy_weight(len(current))
    current_categories: dict[str, int] = {}
    for row in current:
        for category in row.get("categories") or [row.get("category", "unknown")]:
            current_categories[category] = current_categories.get(category, 0) + 1
    policy = {
        "version": PUBLISHED_SELECTION_POLICY_VERSION,
        "settled_unique_forecasts": len(current),
        "historical_unique_forecasts": len(historical),
        "weight": round(current_weight, 4),
        "prior_strength": POLICY_PRIOR_STRENGTH,
        "category_forecast_samples": current_categories,
        **sample_readiness(len(current)),
    }

    if total < 20:
        # Not enough to correct anything without inventing a trend.
        fit = {"global": 0.0, "groups": {}, "n": total,
               "fitted_at": fitted_at,
               "note": "insufficient data — no correction applied",
               "policy": policy,
               "raw_observations": sum(row.get("duplicate_count", 1)
                                       for row in observations),
               "duplicates_removed": sum(row.get("duplicate_count", 1)
                                         for row in observations) - total}
        return fit

    historical_legs = [(row["raw_probability"], row["won"])
                       for row in historical]
    current_legs = [(row["raw_probability"], row["won"])
                    for row in current]
    historical_raw = _solve_shift(_regularised(historical_legs))
    historical_weight = len(historical) / (len(historical) + GLOBAL_K)
    historical_shift = historical_raw * historical_weight
    current_raw = (_solve_shift(_regularised(current_legs))
                   if current_legs else historical_shift)
    global_shift = _clamp(
        (1 - current_weight) * historical_shift
        + current_weight * current_raw
    )

    by_group: dict[str, list[dict]] = {}
    for row in observations:
        by_group.setdefault(_group_of(row.get("market")), []).append(row)

    groups: dict[str, dict] = {}
    for grp, rows in by_group.items():
        sub = [(row["raw_probability"], row["won"]) for row in rows]
        n = len(sub)
        if n < MIN_GROUP_N:
            continue
        historical_rows = [row for row in rows if row.get("policy_version")
                           != PUBLISHED_SELECTION_POLICY_VERSION]
        current_rows = [row for row in rows if row.get("policy_version")
                        == PUBLISHED_SELECTION_POLICY_VERSION]
        historical_sub = [(row["raw_probability"], row["won"])
                          for row in historical_rows]
        current_sub = [(row["raw_probability"], row["won"])
                       for row in current_rows]
        historical_group_raw = (_solve_shift(_regularised(historical_sub))
                                if historical_sub else historical_shift)
        group_history_weight = len(historical_sub) / (
            len(historical_sub) + SHRINK_K
        )
        historical_group_shift = (
            group_history_weight * historical_group_raw
            + (1 - group_history_weight) * historical_shift
        )
        current_group_raw = (_solve_shift(_regularised(current_sub))
                             if current_sub else historical_group_shift)
        group_current_weight = policy_weight(len(current_sub))
        shift = _clamp(
            group_current_weight * current_group_raw
            + (1 - group_current_weight) * historical_group_shift
        )
        promised = sum(p for p, _ in sub) / n
        actual = sum(1 for _, won in sub if won) / n
        hist_stats = _cohort_stats(historical_rows)
        current_stats = _cohort_stats(current_rows)
        prior_reliability = (hist_stats["actual"] if hist_stats["actual"] is not None
                             else promised)
        current_reliability = (current_stats["actual"]
                               if current_stats["actual"] is not None
                               else prior_reliability)
        blended_reliability = (
            (1 - group_current_weight) * prior_reliability
            + group_current_weight * current_reliability
        )
        groups[grp] = {
            "shift": round(shift, 4),
            "raw_shift": round(current_group_raw, 4),
            "n": n,
            "weight": round(group_current_weight, 3),
            "promised": round(promised, 4),
            "actual": round(actual, 4),
            "historical_sample": hist_stats["n"],
            "current_policy_sample": current_stats["n"],
            "historical_reliability_estimate": round(prior_reliability, 4),
            "current_policy_promised": (round(current_stats["promised"], 4)
                                          if current_stats["promised"] is not None else None),
            "current_policy_actual": (round(current_stats["actual"], 4)
                                       if current_stats["actual"] is not None else None),
            "blended_reliability_estimate": round(blended_reliability, 4),
            "current_policy_weight": round(group_current_weight, 4),
        }

    all_stats = _cohort_stats(observations)
    historical_stats = _cohort_stats(historical)
    current_stats = _cohort_stats(current)
    fit = {
        "global": round(global_shift, 4),
        "raw_global": round(current_raw, 4),
        "groups": groups,
        "n": total,
        "fitted_at": fitted_at,
        "note": None,
        "policy": policy,
        "all_policy": all_stats,
        "historical": historical_stats,
        "current_policy": current_stats,
        "raw_observations": sum(row.get("duplicate_count", 1)
                                for row in observations),
        "duplicates_removed": sum(row.get("duplicate_count", 1)
                                  for row in observations) - total,
    }
    return fit


def _clamp(shift: float) -> float:
    return max(MAX_DOWN, min(MAX_UP, shift))


def calibrate(prob: float, market_group: str, fit: dict | None = None) -> float:
    """Published probability for a raw model probability.

    A group with no settled legs is corrected by nothing at all.

    It used to inherit the global shift, which sounds cautious and is not. The
    global figure is an average over the markets that *do* have records, and
    those records currently say over_1_5 and match_result have been
    under-promising — so the global shift is a positive boost. Handing it to a
    market that has never settled a leg asserts, on no evidence, that it is
    under-promising too.

    That is not hypothetical. Under 4.5 on Real Madrid v Real Sociedad came out
    of the Poisson at 0.7553, was lifted to 0.7754 by a +0.1122 global shift
    earned entirely by other markets, and went onto the card at 78% — against
    a bookmaker quoting 1.37, which implies about 69%. We had no record for
    that line at all and were publishing a number above the market's on the
    strength of corrections fitted elsewhere.

    Zero is the honest default. It can under-state a new market that really is
    under-promising, which costs picks; the alternative over-states one, which
    costs money. MIN_EVIDENCE_LEGS then lets each group earn its own
    correction from its own results.
    """
    if prob <= 0 or prob >= 1:
        return prob
    if fit is None:
        fit = fit_calibration()
    grp = (fit.get("groups") or {}).get(market_group)
    shift = grp["shift"] if grp else 0.0
    if not shift:
        return prob
    return _sigmoid(_logit(prob) + shift)


def status() -> dict:
    """Current correction, for the diagnostics endpoint."""
    fit = fit_calibration()
    return {
        "n_legs": fit.get("n", 0),
        "raw_observations": fit.get("raw_observations", fit.get("n", 0)),
        "duplicates_removed": fit.get("duplicates_removed", 0),
        "global_shift": fit.get("global", 0.0),
        "note": fit.get("note"),
        "policy": fit.get("policy", {}),
        "groups": fit.get("groups", {}),
        # What the correction does to a few reference probabilities, which is
        # far easier to sanity-check than a log-odds shift.
        "examples": {
            grp: {
                f"{int(p * 100)}%": f"{calibrate(p, grp, fit) * 100:.1f}%"
                for p in (0.55, 0.65, 0.75, 0.85)
            }
            for grp in list((fit.get("groups") or {}).keys()) + ["match_result"]
            if grp
        },
    }
