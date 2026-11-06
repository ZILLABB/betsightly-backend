"""Read-only investigation of prospective NBA winner misses and score errors.

Only pass rows that have already passed `research_prospective._read_cohort`.
No retraining, mutation, betting decisions, sportsbook prices or backfilling.
"""
from __future__ import annotations

import math

REVIEW_GATE = 100


def _round(x):
    return round(x, 4)


def _error_summary(errors: list[float]) -> dict:
    if not errors:
        return {
            "count": 0, "mae": None, "rmse": None, "signed_bias": None,
            "median_absolute_error": None, "p90_absolute_error": None,
            "within_5_points": None, "within_10_points": None,
            "overestimated": None, "underestimated": None,
        }
    n = len(errors)
    absolute = sorted(abs(e) for e in errors)
    middle = (absolute[n // 2] if n % 2 else
              (absolute[n // 2 - 1] + absolute[n // 2]) / 2)
    return {
        "count": n,
        "mae": _round(sum(absolute) / n),
        "rmse": _round(math.sqrt(sum(e * e for e in errors) / n)),
        "signed_bias": _round(sum(errors) / n),
        "median_absolute_error": _round(middle),
        "p90_absolute_error": _round(absolute[math.ceil(n * 0.9) - 1]),
        "within_5_points": _round(sum(abs(e) <= 5 for e in errors) / n),
        "within_10_points": _round(sum(abs(e) <= 10 for e in errors) / n),
        "overestimated": sum(e > 0 for e in errors),
        "underestimated": sum(e < 0 for e in errors),
    }


def _miss(row: dict) -> dict:
    p = float(row["p"])
    home = p >= 0.5
    output = {
        "game_id": str(row["game_id"]),
        "fixture_date": str(row["fixture_date"]),
        "away_team": row["away_team"],
        "home_team": row["home_team"],
        "predicted_winner": row["home_team"] if home else row["away_team"],
        "actual_winner": row["home_team"] if bool(row["y"]) else row["away_team"],
        "predicted_winner_confidence": _round(max(p, 1 - p)),
        "verified_away_score": row["away_score"],
        "verified_home_score": row["home_score"],
    }
    if row["predicted_total"] is not None:
        total = float(row["predicted_total"])
        margin = float(row["predicted_margin"])
        output["predicted_total_points"] = _round(total)
        output["actual_total_points"] = row["home_score"] + row["away_score"]
        output["total_points_signed_error"] = _round(
            total - output["actual_total_points"])
        output["predicted_home_margin"] = _round(margin)
        output["actual_home_margin"] = row["home_score"] - row["away_score"]
        output["home_margin_signed_error"] = _round(
            margin - output["actual_home_margin"])
    return output


def paper_quality_diagnostics(validated_rows: list[dict]) -> dict:
    """Review stored, settled forecasts without rescaling their probabilities.

    Positive score bias denotes systematic over-prediction, negative bias
    denotes under-prediction. No score error is a bet-market evaluation.
    """
    settled = [row for row in validated_rows if row["recorded_at"] is not None]
    total_errors = []
    margin_errors = []
    confidence_misses = []
    missing_score_projections = 0
    for row in settled:
        p = float(row["p"])
        y = row["y"]
        if not math.isfinite(p) or not 0 <= p <= 1 or y not in (0, 1):
            raise ValueError("Validated cohort has an invalid outcome")
        if row["home_score"] is None or row["away_score"] is None:
            raise ValueError("Validated cohort has no final score")
        home_predicted = p >= 0.5
        if home_predicted != bool(y):
            confidence_misses.append(_miss(row))
        predicted_total = row["predicted_total"]
        predicted_margin = row["predicted_margin"]
        if predicted_total is None and predicted_margin is None:
            missing_score_projections += 1
            continue
        if (predicted_total is None or predicted_margin is None or
                not math.isfinite(float(predicted_total)) or
                not math.isfinite(float(predicted_margin))):
            raise ValueError("Invalid stored score projection")
        total_errors.append(float(predicted_total) -
                            (row["home_score"] + row["away_score"]))
        margin_errors.append(float(predicted_margin) -
                             (row["home_score"] - row["away_score"]))
    confidence_misses.sort(
        key=lambda r: (-r["predicted_winner_confidence"], r["game_id"]))
    n = len(settled)
    home_wins = sum(int(row["y"]) for row in settled)
    return {
        "status": "descriptive_only" if n < REVIEW_GATE else "review_ready",
        "settled_count": n,
        "pending_excluded": len(validated_rows) - n,
        "sample_size_gate_met": n >= REVIEW_GATE,
        "minimum_review_settlements": REVIEW_GATE,
        "baseline_winner_accuracy": {
            "always_home": _round(home_wins / n) if n else None,
            "always_away": _round((n - home_wins) / n) if n else None,
            "constant_50_50_brier": 0.25 if n else None,
            "note": ("Always-home and always-away are retrospective accuracy "
                     "references, not tuned probabilities or betting strategies."),
        },
        "score_projections": {
            "settled_with_both_targets": len(total_errors),
            "settled_without_targets": missing_score_projections,
            "total_points": _error_summary(total_errors),
            "home_margin": _error_summary(margin_errors),
            "signed_error_definition": "model_prediction_minus_verified_final",
            "note": "No bookmaker totals/spreads or betting ROI were evaluated.",
        },
        "highest_confidence_misses": confidence_misses[:10],
        "miss_count": len(confidence_misses),
        "research_only": True,
        "no_writes": True,
        "bookmaker_odds_verified": False,
        "betting_roi": None,
        "model_modified": False,
    }
