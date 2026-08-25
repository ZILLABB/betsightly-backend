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


def _collect_legs() -> list[tuple[float, bool, str]]:
    """(confidence, won, market_group) for every settled published leg."""
    legs: list[tuple[float, bool, str]] = []

    try:
        from leagues.picks_db import get_history
        for slip in get_history(limit_days=365):
            for leg in slip.get("picks", []):
                conf, status = _raw_conf(leg), leg.get("status")
                if conf is None or status not in ("won", "lost"):
                    continue
                legs.append((conf, status == "won", _calibration_group(leg)))
    except Exception as e:
        logger.debug(f"calibration: archive unavailable ({e})")

    # Rollover legs are settled the same way and carry the same confidences.
    # They store the market *group* under the "market" key, so no lookup.
    try:
        from leagues.rollover_db import RolloverDay
        from database import SessionLocal
        db = SessionLocal()
        try:
            for row in db.query(RolloverDay).all():
                for leg in json.loads(row.picks or "[]"):
                    conf, status = _raw_conf(leg), leg.get("status")
                    if conf is None or status not in ("won", "lost"):
                        continue
                    legs.append((conf, status == "won", _calibration_group(leg)))
        finally:
            db.close()
    except Exception as e:
        logger.debug(f"calibration: rollover unavailable ({e})")

    return legs


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
    market = leg.get("market")
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

    legs = _collect_legs()
    total = len(legs)

    if total < 20:
        # Not enough to correct anything without inventing a trend.
        fit = {"global": 0.0, "groups": {}, "n": total, "fitted_at": now,
               "note": "insufficient data — no correction applied"}
        _MEM.update({"fit": fit, "ts": now})
        return fit

    raw_global = _solve_shift([(p, w) for p, w, _ in legs])
    # Pull the global fit itself toward zero until the sample earns it.
    g_weight = total / (total + GLOBAL_K)
    global_shift = _clamp(raw_global * g_weight)

    by_group: dict[str, list[tuple[float, bool]]] = {}
    for p, w, grp in legs:
        by_group.setdefault(grp, []).append((p, w))

    groups: dict[str, dict] = {}
    for grp, sub in by_group.items():
        n = len(sub)
        if n < MIN_GROUP_N:
            continue
        raw = _solve_shift(_regularised(sub))
        w = n / (n + SHRINK_K)
        # Shrink the group's own effect toward the global correction.
        shift = _clamp(w * raw + (1 - w) * global_shift)
        promised = sum(p for p, _ in sub) / n
        actual = sum(1 for _, won in sub if won) / n
        groups[grp] = {
            "shift": round(shift, 4),
            "raw_shift": round(raw, 4),
            "n": n,
            "weight": round(w, 3),
            "promised": round(promised, 4),
            "actual": round(actual, 4),
        }

    fit = {
        "global": round(global_shift, 4),
        "raw_global": round(raw_global, 4),
        "groups": groups,
        "n": total,
        "fitted_at": now,
        "note": None,
    }

    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps({"ts": now, "fit": fit}, indent=2))
    except Exception:
        pass

    _MEM.update({"fit": fit, "ts": now})
    logger.info(
        f"Calibration fitted on {total} legs: global={global_shift:+.3f}, "
        + ", ".join(f"{g}={v['shift']:+.3f}(n={v['n']})" for g, v in groups.items())
    )
    return fit


def _clamp(shift: float) -> float:
    return max(MAX_DOWN, min(MAX_UP, shift))


def calibrate(prob: float, market_group: str, fit: dict | None = None) -> float:
    """Published probability for a raw model probability."""
    if prob <= 0 or prob >= 1:
        return prob
    if fit is None:
        fit = fit_calibration()
    grp = (fit.get("groups") or {}).get(market_group)
    shift = grp["shift"] if grp else fit.get("global", 0.0)
    if not shift:
        return prob
    return _sigmoid(_logit(prob) + shift)


def status() -> dict:
    """Current correction, for the diagnostics endpoint."""
    fit = fit_calibration()
    return {
        "n_legs": fit.get("n", 0),
        "global_shift": fit.get("global", 0.0),
        "note": fit.get("note"),
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
