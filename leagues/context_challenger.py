"""Offline-only Match Context challenger evaluation.

This module never mutates live predictions. It learns a context-associated
calibration adjustment on an earlier chronological training window and judges
that adjustment on a later holdout window.

A successful result means only that the context adjustment deserves further
shadow/staging evaluation. It never authorizes production promotion.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any


TRAIN_FRACTION = 0.70
MIN_TRAIN_PER_GROUP = 75
MIN_HOLDOUT_PER_GROUP = 30

COMPARISON_RULES = {
    "lineups": {
        "exposed": ("confirmed",),
        "control": ("available_unconfirmed",),
    },
    "injuries": {
        "exposed": ("reported",),
        "control": ("none_reported",),
    },
    "suspensions": {
        "exposed": ("reported",),
        "control": ("none_reported",),
    },
    "rest": {
        "exposed": ("short_rest",),
        "control": ("normal_rest",),
    },
    "congestion": {
        "exposed": ("congested",),
        "control": ("not_congested",),
    },
    "weather": {
        "exposed": (
            "wet",
            "windy",
            "wet_and_windy",
        ),
        "control": ("other_known",),
    },
}


def _clamp_probability(value: float) -> float:
    return max(
        0.01,
        min(
            0.99,
            float(value),
        ),
    )


def _mean(values: list[float]) -> float | None:
    if not values:
        return None

    return sum(values) / len(values)


def _sample_variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0

    mean = sum(values) / len(values)

    return sum(
        (value - mean) ** 2
        for value in values
    ) / (len(values) - 1)


def _residuals(rows: list[dict]) -> list[float]:
    return [
        float(row["outcome"])
        - float(row["probability"])
        for row in rows
    ]


def _residual_difference(
    exposed: list[dict],
    control: list[dict],
) -> tuple[
    float | None,
    float | None,
    float | None,
]:
    if not exposed or not control:
        return None, None, None

    exposed_residuals = _residuals(
        exposed
    )

    control_residuals = _residuals(
        control
    )

    exposed_mean = _mean(
        exposed_residuals
    )

    control_mean = _mean(
        control_residuals
    )

    delta = (
        float(exposed_mean)
        - float(control_mean)
    )

    if (
        len(exposed_residuals) < 2
        or len(control_residuals) < 2
    ):
        return delta, None, None

    se = math.sqrt(
        _sample_variance(
            exposed_residuals
        ) / len(exposed_residuals)
        + _sample_variance(
            control_residuals
        ) / len(control_residuals)
    )

    return (
        delta,
        delta - 1.96 * se,
        delta + 1.96 * se,
    )


def _brier(
    rows: list[dict],
    probability_key: str = "probability",
) -> float | None:
    if not rows:
        return None

    return sum(
        (
            float(row[probability_key])
            - float(row["outcome"])
        ) ** 2
        for row in rows
    ) / len(rows)


def _bias(
    rows: list[dict],
    probability_key: str = "probability",
) -> float | None:
    if not rows:
        return None

    return sum(
        float(row[probability_key])
        - float(row["outcome"])
        for row in rows
    ) / len(rows)


def _time_split(
    observations: list[dict],
) -> tuple[
    list[dict],
    list[dict],
    str | None,
]:
    """Chronological split using whole dates so one day never leaks across."""
    dates = sorted({
        str(row.get("date") or "")[:10]
        for row in observations
        if str(row.get("date") or "")[:10]
    })

    if len(dates) < 2:
        return [], [], None

    split_index = int(
        len(dates) * TRAIN_FRACTION
    )

    split_index = max(
        1,
        min(
            len(dates) - 1,
            split_index,
        ),
    )

    train_dates = set(
        dates[:split_index]
    )

    holdout_dates = set(
        dates[split_index:]
    )

    split_date = dates[
        split_index
    ]

    training = [
        row
        for row in observations
        if str(
            row.get("date") or ""
        )[:10] in train_dates
    ]

    holdout = [
        row
        for row in observations
        if str(
            row.get("date") or ""
        )[:10] in holdout_dates
    ]

    return (
        training,
        holdout,
        split_date,
    )


def _dimension_rows(
    rows: list[dict],
    dimension: str,
    labels: tuple[str, ...],
) -> list[dict]:
    wanted = set(labels)

    return [
        row
        for row in rows
        if (
            (
                row.get("labels")
                or {}
            ).get(dimension)
            in wanted
        )
    ]


def _evaluate_one(
    training: list[dict],
    holdout: list[dict],
    *,
    market: str,
    dimension: str,
    exposed_labels: tuple[str, ...],
    control_labels: tuple[str, ...],
) -> dict:
    train_market = [
        row
        for row in training
        if row.get("market") == market
    ]

    holdout_market = [
        row
        for row in holdout
        if row.get("market") == market
    ]

    train_exposed = _dimension_rows(
        train_market,
        dimension,
        exposed_labels,
    )

    train_control = _dimension_rows(
        train_market,
        dimension,
        control_labels,
    )

    holdout_exposed = _dimension_rows(
        holdout_market,
        dimension,
        exposed_labels,
    )

    holdout_control = _dimension_rows(
        holdout_market,
        dimension,
        control_labels,
    )

    result = {
        "market": market,
        "dimension": dimension,
        "exposed_labels": list(
            exposed_labels
        ),
        "control_labels": list(
            control_labels
        ),
        "train_exposed_n": len(
            train_exposed
        ),
        "train_control_n": len(
            train_control
        ),
        "holdout_exposed_n": len(
            holdout_exposed
        ),
        "holdout_control_n": len(
            holdout_control
        ),
        "promotion_enabled": False,
        "live_adjustment_allowed": False,
        "selection_changed": False,
    }

    training_ready = (
        len(train_exposed)
        >= MIN_TRAIN_PER_GROUP
        and len(train_control)
        >= MIN_TRAIN_PER_GROUP
    )

    holdout_ready = (
        len(holdout_exposed)
        >= MIN_HOLDOUT_PER_GROUP
        and len(holdout_control)
        >= MIN_HOLDOUT_PER_GROUP
    )

    if not training_ready:
        result.update({
            "status": "insufficient_training_sample",
            "shadow_candidate": False,
        })

        return result

    if not holdout_ready:
        result.update({
            "status": "insufficient_holdout_sample",
            "shadow_candidate": False,
        })

        return result

    (
        adjustment,
        train_ci_low,
        train_ci_high,
    ) = _residual_difference(
        train_exposed,
        train_control,
    )

    adjustment = float(
        adjustment or 0.0
    )

    training_signal = bool(
        train_ci_low is not None
        and train_ci_high is not None
        and (
            train_ci_low > 0
            or train_ci_high < 0
        )
    )

    # The challenger changes probability only in this isolated copy of the
    # held-out observations. Original archived values remain untouched.
    challenger_exposed = [
        {
            **row,
            "challenger_probability": (
                _clamp_probability(
                    float(
                        row["probability"]
                    )
                    + adjustment
                )
            ),
        }
        for row in holdout_exposed
    ]

    challenger_control = [
        {
            **row,
            "challenger_probability": float(
                row["probability"]
            ),
        }
        for row in holdout_control
    ]

    combined_baseline = (
        holdout_exposed
        + holdout_control
    )

    combined_challenger = (
        challenger_exposed
        + challenger_control
    )

    baseline_brier = _brier(
        combined_baseline
    )

    challenger_brier = _brier(
        combined_challenger,
        "challenger_probability",
    )

    baseline_exposed_brier = _brier(
        holdout_exposed
    )

    challenger_exposed_brier = _brier(
        challenger_exposed,
        "challenger_probability",
    )

    baseline_exposed_bias = _bias(
        holdout_exposed
    )

    challenger_exposed_bias = _bias(
        challenger_exposed,
        "challenger_probability",
    )

    brier_improvement = (
        float(baseline_brier)
        - float(challenger_brier)
    )

    exposed_brier_improvement = (
        float(
            baseline_exposed_brier
        )
        - float(
            challenger_exposed_brier
        )
    )

    bias_improved = (
        abs(
            float(
                challenger_exposed_bias
            )
        )
        < abs(
            float(
                baseline_exposed_bias
            )
        )
    )

    holdout_confirmed = bool(
        training_signal
        and brier_improvement > 0
        and exposed_brier_improvement > 0
        and bias_improved
    )

    if not training_signal:
        status = "rejected_no_training_signal"

    elif holdout_confirmed:
        status = "shadow_candidate"

    else:
        status = "rejected_holdout"

    result.update({
        "status": status,
        "shadow_candidate": (
            holdout_confirmed
        ),
        "training_adjustment": round(
            adjustment,
            6,
        ),
        "training_adjustment_ci95": {
            "low": round(
                float(train_ci_low),
                6,
            ),
            "high": round(
                float(train_ci_high),
                6,
            ),
        },
        "holdout": {
            "baseline_brier": round(
                float(baseline_brier),
                6,
            ),
            "challenger_brier": round(
                float(challenger_brier),
                6,
            ),
            "brier_improvement": round(
                brier_improvement,
                6,
            ),
            "exposed_baseline_brier": round(
                float(
                    baseline_exposed_brier
                ),
                6,
            ),
            "exposed_challenger_brier": round(
                float(
                    challenger_exposed_brier
                ),
                6,
            ),
            "exposed_brier_improvement": round(
                exposed_brier_improvement,
                6,
            ),
            "exposed_baseline_bias": round(
                float(
                    baseline_exposed_bias
                ),
                6,
            ),
            "exposed_challenger_bias": round(
                float(
                    challenger_exposed_bias
                ),
                6,
            ),
        },
        "next_step": (
            "staging_shadow_replay"
            if holdout_confirmed
            else "keep_observing"
        ),
    })

    return result


def evaluate_context_challenger(
    observations: list[dict],
) -> dict:
    """Evaluate predefined context adjustments on a chronological holdout."""
    observations = [
        {
            **row,
            "date": str(
                row.get("date")
                or ""
            )[:10],
        }
        for row in observations
        if (
            row.get("market")
            and row.get("probability")
            is not None
            and row.get("outcome")
            is not None
            and row.get("labels")
        )
    ]

    (
        training,
        holdout,
        split_date,
    ) = _time_split(
        observations
    )

    if split_date is None:
        return {
            "status": "insufficient_time_span",
            "shadow_only": True,
            "promotion_enabled": False,
            "live_adjustment_allowed": False,
            "observation_count": len(
                observations
            ),
            "candidates": [],
        }

    markets = sorted({
        str(row["market"])
        for row in observations
    })

    evaluations = []

    for market in markets:
        for (
            dimension,
            rule,
        ) in COMPARISON_RULES.items():
            evaluations.append(
                _evaluate_one(
                    training,
                    holdout,
                    market=market,
                    dimension=dimension,
                    exposed_labels=rule[
                        "exposed"
                    ],
                    control_labels=rule[
                        "control"
                    ],
                )
            )

    candidates = [
        row
        for row in evaluations
        if row.get(
            "shadow_candidate"
        )
    ]

    statuses = Counter(
        row.get("status")
        for row in evaluations
    )

    return {
        "status": "success",
        "shadow_only": True,
        "promotion_enabled": False,
        "live_adjustment_allowed": False,
        "selection_changed": False,
        "train_fraction": TRAIN_FRACTION,
        "minimum_training_per_group": MIN_TRAIN_PER_GROUP,
        "minimum_holdout_per_group": MIN_HOLDOUT_PER_GROUP,
        "observation_count": len(
            observations
        ),
        "training_count": len(
            training
        ),
        "holdout_count": len(
            holdout
        ),
        "holdout_start_date": split_date,
        "evaluation_count": len(
            evaluations
        ),
        "status_counts": dict(
            statuses
        ),
        "candidate_count": len(
            candidates
        ),
        "candidates": candidates,
        "evaluations": evaluations,
        "decision_rule": (
            "training signal must be statistically separated and then improve "
            "Brier score plus exposed-group calibration on a later chronological "
            "holdout before it can become a staging shadow candidate"
        ),
        "production_rule": (
            "this report never promotes or mutates live prediction probabilities"
        ),
    }
