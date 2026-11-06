"""Descriptive calibration of the *predicted winner* in NBA paper forecasts.

This module operates solely on rows already integrity-checked by the
prospective reader. It never changes models, forecasts, ledgers or markets.
"""
from __future__ import annotations

import math

FAVORITE_BANDS = ((0.50, 0.60), (0.60, 0.70), (0.70, 0.80),
                  (0.80, 0.90), (0.90, 1.00))
MIN_OVERALL_REVIEW = 100
MIN_BAND_REVIEW = 20


def _wilson(wins: int, total: int) -> dict | None:
    if not total:
        return None
    z = 1.95996398454
    p = wins / total
    factor = 1 + z * z / total
    midpoint = (p + z * z / (2 * total)) / factor
    half_width = z * math.sqrt(p * (1 - p) / total +
                               z * z / (4 * total * total)) / factor
    return {"lower": round(max(0.0, midpoint - half_width), 4),
            "upper": round(min(1.0, midpoint + half_width), 4),
            "method": "Wilson 95% descriptive interval"}


def _summary(items: list[dict]) -> dict:
    n = len(items)
    if not n:
        return {"count": 0, "correct": 0, "average_confidence": None,
                "observed_win_rate": None, "calibration_gap": None,
                "win_rate_95pct_ci": None}
    correct = sum(item["correct"] for item in items)
    average = sum(item["confidence"] for item in items) / n
    observed = correct / n
    return {"count": n, "correct": correct,
            "average_confidence": round(average, 5),
            "observed_win_rate": round(observed, 5),
            "calibration_gap": round(observed - average, 5),
            "win_rate_95pct_ci": _wilson(correct, n)}


def favorite_confidence_report(validated_rows: list[dict]) -> dict:
    """Summarize confirmed winners only; never treat a pending game as a loss.

    `validated_rows` must come from `research_prospective._read_cohort`.
    A positive calibration gap means observed winner accuracy exceeded the
    declared confidence; a negative gap indicates possible overconfidence.
    These are descriptive diagnostics, NOT recalibrated probabilities.
    """
    observations = []
    for row in validated_rows:
        if row.get("recorded_at") is None:
            continue
        p = float(row["p"])
        y = int(row["y"])
        if not math.isfinite(p) or not 0 <= p <= 1 or y not in (0, 1):
            raise ValueError("invalid validated favorite outcome")
        predicted_home = p >= 0.5
        observations.append({
            "game_id": str(row["game_id"]),
            "confidence": p if predicted_home else 1 - p,
            "correct": int(predicted_home == bool(y)),
            "predicted_side": "home" if predicted_home else "away",
        })

    n = len(observations)
    bands = []
    weighted_absolute_gap = 0.0
    for i, (low, high) in enumerate(FAVORITE_BANDS):
        selected = [item for item in observations
                    if low <= item["confidence"] < high or
                    (i == len(FAVORITE_BANDS) - 1 and item["confidence"] == high)]
        stats = _summary(selected)
        if selected:
            weighted_absolute_gap += len(selected) / n * abs(stats["calibration_gap"])
        bands.append({"lower": low, "upper": high, **stats,
                      "descriptive_only": len(selected) < MIN_BAND_REVIEW})

    high = [item for item in observations if item["confidence"] >= 0.70]
    losses = sorted((item for item in observations if not item["correct"]),
                    key=lambda item: (-item["confidence"], item["game_id"]))
    return {
        "status": "descriptive_only" if n < MIN_OVERALL_REVIEW else "review_ready",
        "settled_forecasts_evaluated": n,
        "pending_excluded": len(validated_rows) - n,
        "overall_predicted_winner": _summary(observations),
        "high_confidence_70pct_plus": {**_summary(high),
                                      "descriptive_only": len(high) < MIN_BAND_REVIEW},
        "bands": bands,
        "largest_confidence_misses": [
            {"game_id": item["game_id"],
             "predicted_side": item["predicted_side"],
             "predicted_winner_confidence": round(item["confidence"], 5)}
            for item in losses[:5]
        ],
        "favorite_ece": (round(weighted_absolute_gap, 5)
                         if n >= MIN_OVERALL_REVIEW else None),
        "minimum_overall_review_games": MIN_OVERALL_REVIEW,
        "minimum_band_review_games": MIN_BAND_REVIEW,
        "sample_size_gate_met": n >= MIN_OVERALL_REVIEW,
        "confidence_changed": False,
        "bookmaker_odds_verified": False,
        "betting_roi": None,
        "research_only": True,
        "no_writes": True,
        "note": ("Positive calibration gaps indicate underconfidence, negative "
                 "gaps possible overconfidence. Small bands are descriptive only; "
                 "the 100-game gate is a review checkpoint, not proof of quality."),
    }
