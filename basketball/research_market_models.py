"""Private NBA total-points and point-margin research benchmarks.

These regress game scores and *not* sportsbook O/U or handicap markets.
Without price/line timestamps they produce no betting recommendations.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from basketball.research_features import FEATURE_COLUMNS, SCHEMA_VERSION, make_rows
from basketball.research_model import chronological_split

VERSION = "nba-point-distribution-research-v1"


def _imports():
    import joblib
    import numpy as np
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return joblib, np, Ridge, make_pipeline, StandardScaler


def _evaluate(actual, predicted, np) -> dict:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    return {
        "games": int(len(actual)),
        "mae": round(float(np.mean(np.abs(actual - predicted))), 4),
        "rmse": round(float(np.sqrt(np.mean((actual - predicted) ** 2))), 4),
        "bias": round(float(np.mean(predicted - actual)), 4),
    }


def train_score_baselines(games: list[dict], artifact_path: str | Path) -> dict:
    """Chronological score-model experiment, with no bookmaker return claims."""
    joblib, np, Ridge, pipeline, scaler = _imports()
    rows = make_rows(games)
    training, validation, test = chronological_split(rows)
    features = lambda subset: np.asarray([r["features"] for r in subset],
                                           dtype=float)
    result = {
        "model_version": VERSION, "feature_schema": SCHEMA_VERSION,
        "research_only": True, "bookmaker_odds_present": False,
        "betting_roi_computed": False,
        "historical_test_period": {
            "first": test[0]["date"], "last": test[-1]["date"],
            "games": len(test),
        },
        "targets": {},
    }
    prospective = {}
    for target in ("total_points", "home_margin"):
        y_train = np.asarray([r[target] for r in training], dtype=float)
        y_valid = np.asarray([r[target] for r in validation], dtype=float)
        y_test = np.asarray([r[target] for r in test], dtype=float)
        candidates = []
        for alpha in (0.1, 1., 10., 100.):
            model = pipeline(scaler(), Ridge(alpha=alpha))
            model.fit(features(training), y_train)
            pred = model.predict(features(validation))
            candidates.append((float(np.mean(np.abs(pred - y_valid))),
                               alpha, model))
        _, alpha, model = min(candidates, key=lambda x: (x[0], x[1]))
        validation_est = model.predict(features(validation))
        test_est = model.predict(features(test))
        baseline = np.full(len(test), float(np.mean(y_train)))
        result["targets"][target] = {
            "selected_alpha": alpha,
            "validation": _evaluate(y_valid, validation_est, np),
            "test": _evaluate(y_test, test_est, np),
            "constant_mean_baseline": _evaluate(y_test, baseline, np),
            "eligible_for_bookmaker_publication": False,
        }
        completed = sorted([r for r in rows if r["status"] == "final"],
                           key=lambda r: (r["date"], r["game_id"]))
        updated = pipeline(scaler(), Ridge(alpha=alpha))
        updated.fit(features(completed),
                    np.asarray([r[target] for r in completed], dtype=float))
        prospective[target] = updated
    result["prospective_training_cutoff"] = completed[-1]["date"]
    result["prospective_training_games"] = len(completed)
    target_path = Path(artifact_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "version": VERSION, "schema": SCHEMA_VERSION,
        "feature_columns": FEATURE_COLUMNS,
        "research_only": True, "trained_through": completed[-1]["date"],
        "models": prospective, "report": result,
    }
    staged = target_path.with_name(target_path.name + ".tmp")
    try:
        joblib.dump(bundle, staged)
        os.replace(staged, target_path)
    finally:
        if staged.exists():
            staged.unlink()
    return result


def private_score_estimates(games: list[dict], artifact_path: str | Path,
                            on_date: str) -> list[dict]:
    """Projected means only. No sportsbook line, no staking or pick outcome."""
    joblib, np, _, _, _ = _imports()
    bundle = joblib.load(artifact_path)  # trusted local-only artifact
    if (bundle.get("version") != VERSION or not bundle.get("research_only")
            or bundle.get("schema") != SCHEMA_VERSION
            or tuple(bundle.get("feature_columns", ())) != FEATURE_COLUMNS):
        raise ValueError("Incompatible research score model")
    if on_date <= bundle["trained_through"]:
        raise ValueError("Future dates only; model saw historical labels")
    predictions = [r for r in make_rows(games)
                   if r["status"] == "scheduled" and r["date"] == on_date]
    if not predictions:
        return []
    x = np.asarray([r["features"] for r in predictions], dtype=float)
    total = bundle["models"]["total_points"].predict(x)
    margin = bundle["models"]["home_margin"].predict(x)
    return [
        {"game_id": r["game_id"], "date": r["date"],
         "home_team": r["home_name"], "away_team": r["away_name"],
         "expected_total_points": round(float(t), 2),
         "expected_home_margin": round(float(m), 2),
         "research_only": True, "not_a_betting_market": True,
         "bookmaker_line": None, "booking_code": None}
        for r, t, m in zip(predictions, total, margin)
    ]
