"""Builder-only fusion of replay and current live calibration evidence."""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent / "data" / "replay"

PROMOTED = {
    "over_1_5",
    "under_3_5",
    "under_4_5",
    "home_or_draw",
    "away_or_draw",
    "home_or_away",
    "dnb_home",
    "dnb_away",
}

RESTRICTED = {
    "btts_yes",
    "btts_no",
    "home_win",
    "draw",
    "away_win",
}

# Two hundred observations gives useful binomial resolution, while uncertainty
# below still widens automatically.
#
# Historical replay influence on the fused mean is deliberately capped so
# hundreds of thousands of correlated/bookmaker-anchored replay rows cannot
# overwhelm current live production evidence.
MIN_CELL_N = 200
PRIOR_TRIAL_CAP = 25
MIN_LIVE_CONFLICT_N = 15


@lru_cache(maxsize=1)
def _evidence():
    def load(name):
        return json.loads((ROOT / name).read_text())

    return (
        load("market_summary.json"),
        load("calibration_buckets.json"),
        load("league_market_summary.json"),
        load("recency_market_summary.json"),
    )


def _bucket(probability):
    edges = (
        (0, 0.50),
        (0.50, 0.55),
        (0.55, 0.60),
        (0.60, 0.65),
        (0.65, 0.70),
        (0.70, 0.75),
        (0.75, 0.80),
        (0.80, 0.85),
        (0.85, 0.90),
        (0.90, 1.00001),
    )

    return next(
        f"{int(lo * 100)}-{int(min(hi, 1) * 100)}"
        for lo, hi in edges
        if lo <= probability < hi
    )


def _wilson_lower(rate, n, z=1.96):
    if not n:
        return 0.0

    denominator = 1 + z * z / n
    centre = (rate + z * z / (2 * n)) / denominator
    margin = (
        z
        * math.sqrt(
            rate * (1 - rate) / n
            + z * z / (4 * n * n)
        )
        / denominator
    )

    return max(0.0, centre - margin)


def _fidelity_weight(label):
    label = str(label or "")

    if "FULL_REPLAY" in label:
        return 1.0

    if "MARKET_REPLAY" in label and "DERIVED_REPLAY" not in label:
        return 0.85

    if "MARKET_REPLAY" in label:
        return 0.72

    return 0.55


def _partial_pool(global_cell, bucket_cell, league_cell):
    """Estimate a conservative league × confidence-bucket intersection.

    Phase 2A stores league and confidence-bucket margins independently rather
    than a raw cross-tab. When both have enough observations, shrink both
    toward the market-wide rate and combine them conservatively.

    The smaller marginal sample controls the synthetic cell's sample strength.
    """

    global_rate = float(global_cell.get("actual") or 0)
    estimates = []

    for cell in (league_cell, bucket_cell):
        n = int(cell.get("n") or 0)

        if n < MIN_CELL_N:
            return None

        weight = n / (n + MIN_CELL_N)

        estimates.append(
            global_rate
            + weight * (float(cell["actual"]) - global_rate)
        )

    n = min(
        int(league_cell["n"]),
        int(bucket_cell["n"]),
    )

    rate = sum(estimates) / len(estimates)

    predicted = (
        float(league_cell.get("predicted") or rate)
        + float(bucket_cell.get("predicted") or rate)
    ) / 2

    return {
        "n": n,
        "actual": rate,
        "predicted": predicted,
        "calibration_error": predicted - rate,
    }


def fused_market_evidence(
    market: str,
    probability: float,
    league: str | None,
    live: dict | None = None,
) -> dict:
    summary, buckets, leagues, recency = _evidence()

    global_cell = summary.get(market) or {}

    bucket_cell = (
        (buckets.get(market) or {})
        .get(_bucket(probability))
        or {}
    )

    league_key = " ".join(
        str(league or "").lower().split()
    )

    league_cell = (
        (leagues.get(market) or {})
        .get(league_key)
        or {}
    )

    joint_cell = _partial_pool(
        global_cell,
        bucket_cell,
        league_cell,
    )

    if joint_cell:
        cell = joint_cell
        level = "market_league_confidence_bucket_partial_pool"

    elif int(bucket_cell.get("n") or 0) >= MIN_CELL_N:
        cell = bucket_cell
        level = "market_confidence_bucket"

    elif int(league_cell.get("n") or 0) >= MIN_CELL_N:
        cell = league_cell
        level = "market_league"

    else:
        cell = global_cell
        level = "market_global"

    hist_n = int(cell.get("n") or 0)
    hist_rate = float(
        cell.get("actual") or probability
    )

    hist_error = abs(
        float(cell.get("calibration_error") or 0)
    )

    recent = (
        (recency.get(market) or {})
        .get("last_2_seasons")
        or {}
    )

    recent_n = int(recent.get("n") or 0)
    recent_rate = recent.get("actual")

    fidelity = global_cell.get("fidelity")
    fidelity_weight = _fidelity_weight(fidelity)

    recency_weight = min(
        1.0,
        recent_n / MIN_CELL_N,
    )

    evidence_strength = (
        fidelity_weight
        * (0.65 + 0.35 * recency_weight)
    )

    # Recent historical evidence nudges the estimate without replacing the
    # narrower league/confidence evidence chosen above.
    if (
        recent_n >= MIN_CELL_N
        and recent_rate is not None
    ):
        hist_rate = (
            0.80 * hist_rate
            + 0.20 * float(recent_rate)
        )

    # Historical evidence acts as a bounded prior for the fused mean.
    # Huge replay volume therefore cannot overwhelm live production evidence.
    prior_n = (
        min(PRIOR_TRIAL_CAP, hist_n)
        * evidence_strength
    )

    alpha = hist_rate * prior_n
    beta = (1 - hist_rate) * prior_n

    live = live or {}

    live_n = int(live.get("n") or 0)
    live_rate = live.get("actual")

    if live_n and live_rate is not None:
        alpha += float(live_rate) * live_n
        beta += (1 - float(live_rate)) * live_n

    effective_n = alpha + beta

    estimate = (
        alpha / effective_n
        if effective_n
        else probability
    )

    # Mean fusion stays intentionally bounded, but statistical uncertainty
    # should still acknowledge that hundreds/thousands of validated replay
    # observations exist.
    #
    # The replay contribution is capped at 1,000 observations and discounted
    # by fidelity/recency strength so historical evidence still cannot create
    # unrealistic certainty.
    uncertainty_n = max(
        effective_n,
        min(hist_n, 1000) * evidence_strength
        + live_n,
    )

    lower = _wilson_lower(
        estimate,
        uncertainty_n,
    )

    # Detect meaningful disagreement between current production evidence and
    # historical reliability. Small live samples receive a wider tolerance.
    live_se = math.sqrt(
        max(
            0.0001,
            estimate * (1 - estimate),
        )
        / max(1, live_n)
    )

    conflict_gap = max(
        0.10,
        1.96 * live_se,
    )

    live_conflict = bool(
        live_n >= MIN_LIVE_CONFLICT_N
        and live_rate is not None
        and abs(float(live_rate) - hist_rate)
        > conflict_gap
    )

    # Calibration tolerance becomes tighter as historical evidence grows,
    # bounded between 3pp and 6pp.
    calibration_limit = max(
        0.03,
        min(
            0.06,
            1.96
            * math.sqrt(
                max(
                    0.0001,
                    hist_rate * (1 - hist_rate),
                )
                / max(1, hist_n)
            ),
        ),
    )

    reliable = (
        hist_n >= MIN_CELL_N
        and hist_error <= calibration_limit
        and evidence_strength >= 0.60
    )

    if market in RESTRICTED:
        state = "SHADOW"

    elif (
        market in PROMOTED
        and reliable
        and not live_conflict
    ):
        state = "SUPPORTED"

    elif reliable:
        state = "PROVISIONAL"

    else:
        state = "REJECTED"

    # Do not allow evidence fusion to make the model aggressively more
    # confident. Negative evidence adjusts downward fully; positive evidence
    # only nudges upward.
    if estimate < probability:
        adjusted = estimate
    else:
        adjusted = (
            probability
            + 0.25 * (estimate - probability)
        )

    if live_conflict and live_rate is not None:
        adjusted = min(
            adjusted,
            float(live_rate),
        )

    # Uncertainty now materially affects Builder ranking instead of merely
    # being reported as metadata.
    adjusted = (
        0.75 * adjusted
        + 0.25 * lower
    )

    return {
        "state": state,
        "hierarchy_level": level,
        "historical_n": hist_n,
        "recent_historical_n": recent_n,
        "historical_reliability_estimate": round(
            hist_rate,
            4,
        ),
        "live_n": live_n,
        "live_reliability_estimate": live_rate,
        "live_conflict": live_conflict,
        "evidence_adjusted_probability": round(
            max(
                0.01,
                min(0.99, adjusted),
            ),
            4,
        ),
        "lower_reliability_bound": round(
            lower,
            4,
        ),
        "replay_fidelity": fidelity,
        "evidence_strength": round(
            evidence_strength,
            4,
        ),
        "historical_calibration_error": round(
            hist_error,
            4,
        ),
        "calibration_error_limit": round(
            calibration_limit,
            4,
        ),
    }