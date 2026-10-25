"""Independent NBA advanced-score retrospective test: possession efficiency.

This tests a DIFFERENT information set: past-team possessions/efficiency,
past-player rotation and past shooting, not another home-edge adjustment.
201? 2024 train -> 2025 tune -> 2026 retrospective evaluation. No external
blind test claim: 2026 has been investigated in previous BetSightly work.
No models or paper forecasts are saved. No betting prices or game picks.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from pathlib import Path

from basketball.research_advanced_features import (
    FEATURE_COLUMNS, VERSION as FEATURE_VERSION, from_home,
)
from basketball.research_features import FEATURE_COLUMNS as BASIC_FEATURES

MODEL = "nba-advanced-points-three-year-development-v1"
ALPHAS = (1.0, 10.0, 100.0, 1000.0)
MIN_TRAIN, MIN_TUNE, MIN_TEST = 200, 100, 100
TARGETS = ("total_points", "home_margin")
CLUSTER_DRAWS = 1200


def _metrics(rows, estimated_key, actual_key):
    n = len(rows)
    if not n:
        return {"games": 0, "mae": None, "rmse": None, "bias": None}
    errors = [float(row[estimated_key])-float(row[actual_key])
              for row in rows]
    return {
        "games": n,
        "mae": round(sum(abs(v) for v in errors)/n, 5),
        "rmse": round(math.sqrt(sum(v*v for v in errors)/n), 5),
        "bias": round(sum(errors)/n, 5),
    }


def _interval(rows, prediction_a, prediction_b, actual,
              *, draws=CLUSTER_DRAWS, seed=292):
    dates = defaultdict(list)
    for row in rows:
        # positive => basic model has greater MAE => advanced is better
        dates[row["date"]].append(
            abs(row[prediction_b]-row[actual])-
            abs(row[prediction_a]-row[actual]))
    if len(dates) < 6:
        return {"low": None, "high": None,
                "independent_days": len(dates),
                "status": "insufficient_independent_dates"}
    groups = list(dates.values())
    rng = random.Random(seed)
    outcome = []
    for _ in range(draws):
        chosen = [groups[rng.randrange(len(groups))]
                  for _ in range(len(groups))]
        err = [v for group in chosen for v in group]
        outcome.append(sum(err)/len(err))
    outcome.sort()
    low = outcome[int((draws-1)*.025)]
    high = outcome[int((draws-1)*.975)]
    return {
        "low": round(low, 5), "high": round(high, 5),
        "independent_days": len(groups),
        "method": "paired_calendar_day_bootstrap",
        "status": ("improvement_interval_positive" if low > 0 else
                   "no_robust_improvement_demonstrated"),
    }


def _validated_rows(rows):
    cols = len(FEATURE_COLUMNS)
    accepted = []
    distinct = set()
    for row in rows:
        if row.get("status") != "final" or row.get("season") not in (
            2024, 2025, 2026
        ):
            continue
        gid = (row["season"], str(row["game_id"]))
        if gid in distinct:
            raise ValueError("Duplicate NBA historical evaluation game")
        distinct.add(gid)
        f = row.get("features")
        if not isinstance(f, (list, tuple)) or len(f) != cols:
            raise ValueError("NBA advanced score features do not match schema")
        if not all(isinstance(v,(int,float)) and not isinstance(v,bool)
                   and math.isfinite(v) for v in f):
            raise ValueError("Missing or nonfinite NBA past-game features")
        for target in TARGETS:
            v = row.get(target)
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):
                raise ValueError("Missing genuine NBA historical scoring label")
        accepted.append(row)
    return sorted(accepted, key=lambda r:(r["season"],r["date"],str(r["game_id"])))


def compare_rows(rows):
    """Select ridge penalty on 2025 alone; evaluate paired 2026 fixtures."""
    ready = _validated_rows(rows)
    train = [r for r in ready if r["season"] == 2024]
    tune = [r for r in ready if r["season"] == 2025]
    test = [r for r in ready if r["season"] == 2026]
    result = {
        "status": "blocked",
        "version": MODEL, "feature_schema": FEATURE_VERSION,
        "training_season": 2024, "hyperparameter_selection_season": 2025,
        "retrospective_evaluation_season": 2026,
        "cohorts": {"train": len(train), "tune": len(tune), "test": len(test)},
        "required_cohorts": {
            "train": MIN_TRAIN, "tune": MIN_TUNE, "test": MIN_TEST,
        },
        "training_future_seasons_used": False,
        "2026_has_prior_experiment_exposure": True,
        "2026_not_a_blind_unseen_test": True,
        "verified_pregame_2027_settlements": 0,
        "no_writes": True, "research_only": True,
        "model_promoted": False, "bookmaker_odds_verified": False,
        "no_public_predictions": True,
    }
    if (len(train) < MIN_TRAIN or len(tune) < MIN_TUNE
        or len(test) < MIN_TEST):
        return {**result, "reason": "insufficient_exact_advanced_boxscore_cohorts"}
    import numpy as np
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    n_basic = len(BASIC_FEATURES)
    if len(FEATURE_COLUMNS) <= n_basic:
        raise ValueError("Advanced schema contains no additional real features")
    variants = {"basic_previous_games": n_basic,
                "advanced_pace_and_efficiency": len(FEATURE_COLUMNS)}
    targets = {}
    for target in TARGETS:
        actual = [r[target] for r in test]
        predictions = {}
        configurations = {}
        for name, count in variants.items():
            xtrain = np.asarray([r["features"][:count] for r in train],float)
            xtune = np.asarray([r["features"][:count] for r in tune],float)
            xtest = np.asarray([r["features"][:count] for r in test],float)
            ytrain = np.asarray([r[target] for r in train],float)
            ytune = np.asarray([r[target] for r in tune],float)
            trials = []
            for alpha in ALPHAS:
                pipeline = make_pipeline(StandardScaler(),
                                         Ridge(alpha=alpha))
                pipeline.fit(xtrain, ytrain)
                pred = pipeline.predict(xtune)
                error = float(np.mean(np.abs(pred-ytune)))
                trials.append((error, alpha, pipeline))
            selected = min(trials, key=lambda t:(t[0],t[1]))
            # No refit on 2026; tune 2025 does not supply training labels.
            predictions[name] = [float(v) for v in
                                 selected[2].predict(xtest)]
            configurations[name] = {
                "selected_alpha": selected[1],
                "tuning_2025_mae": round(selected[0], 5),
                "training_features": count,
            }
        records = [{
            "date": r["date"],
            "actual": float(value),
            "advanced": predictions["advanced_pace_and_efficiency"][i],
            "basic": predictions["basic_previous_games"][i],
            "train_mean": float(np.mean([v[target] for v in train])),
        } for i,(r,value) in enumerate(zip(test,actual))]
        advanced = _metrics(records,"advanced","actual")
        basic = _metrics(records,"basic","actual")
        naive = _metrics(records,"train_mean","actual")
        uncertainty = _interval(records,"advanced","basic","actual")
        targets[target] = {
            "advanced": advanced,
            "matched_basic": basic,
            "naive_training_season_mean": naive,
            "advanced_minus_basic_mae": round(
                advanced["mae"]-basic["mae"],5),
            "advanced_minus_naive_mae": round(
                advanced["mae"]-naive["mae"],5),
            "advanced_beats_matched_basic": advanced["mae"] < basic["mae"],
            "advanced_beats_naive_mean": advanced["mae"] < naive["mae"],
            "advanced_better_95pct_interval": (
                uncertainty["low"] > 0 if uncertainty["low"] is not None
                else None),
            "uncertainty": uncertainty,
            "train_tune_configuration": configurations,
        }
    # Team score estimates are strictly derived from two separately fitted
    # score targets, not separately trained with incompatible assumptions.
    return {
        **result, "status": "retrospective_diagnostic_only",
        "advanced_feature_columns": list(FEATURE_COLUMNS[n_basic:]),
        "analysis": targets,
        "score_targets": ["total_points", "home_margin"],
        "home_points_from": "(total_points+home_margin)/2",
        "away_points_from": "(total_points-home_margin)/2",
        "market_probabilities_calibrated": False,
        "promotion_gate": "blocked_until_independent_forward_results",
    }


def compare_home(home):
    rows, coverage = from_home(Path(home))
    if coverage.get("status") == "not_ready":
        return {"status": "blocked",
                "reason": coverage.get("reason"),
                "source_coverage": coverage,
                "research_only": True, "no_writes": True,
                "model_promoted": False}
    result = compare_rows(rows)
    return {**result, "source_coverage": coverage}
