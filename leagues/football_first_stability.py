# Walk-forward stability evaluation for the football-first challenger.
#
# This remains offline-only.  Each fold selects a challenger family using
# only data before the fold, refits on that past data, then scores the next
# untouched chronological block.

from __future__ import annotations

from collections import Counter
import math

import numpy as np
import pandas as pd

from leagues.football_first_challenger import (
    FEATURE_COLUMNS,
    TARGET_COLUMNS,
    _aligned_predict_proba,
    _baseline_probabilities,
    _probability_metrics,
)

MIN_SEGMENT_SAMPLES = 100


def _models():
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    return {
        "logistic": Pipeline([
            ("scale", StandardScaler()),
            (
                "model",
                LogisticRegression(
                    max_iter=1200,
                    random_state=42,
                ),
            ),
        ]),
        "hist_gradient_boosting": HistGradientBoostingClassifier(
            learning_rate=0.05,
            max_iter=120,
            max_leaf_nodes=31,
            l2_regularization=0.1,
            random_state=42,
        ),
    }


def temporal_folds(
    features: pd.DataFrame,
    *,
    n_folds: int = 4,
    initial_date_fraction: float = 0.60,
) -> list[dict]:
    if n_folds < 2:
        raise ValueError("n_folds must be at least 2")
    if not 0.40 <= initial_date_fraction <= 0.80:
        raise ValueError(
            "initial_date_fraction must be between 0.40 and 0.80"
        )

    dates = pd.to_datetime(features["date"], errors="raise").dt.date.astype(str)
    unique_dates = sorted(set(dates.tolist()))
    if len(unique_dates) < max(20, n_folds * 4):
        raise ValueError("Not enough distinct dates for walk-forward evaluation")

    first_test = max(
        3,
        int(len(unique_dates) * initial_date_fraction),
    )
    remaining_dates = unique_dates[first_test:]
    blocks = [
        block.tolist()
        for block in np.array_split(
            np.asarray(remaining_dates, dtype=object),
            n_folds,
        )
        if len(block)
    ]

    folds = []
    for fold_number, block in enumerate(blocks, start=1):
        test_start = str(block[0])
        test_end = str(block[-1])

        pre_mask = dates < test_start
        test_mask = (dates >= test_start) & (dates <= test_end)

        pre_indices = np.flatnonzero(pre_mask.to_numpy())
        test_indices = np.flatnonzero(test_mask.to_numpy())

        pre_dates = dates.iloc[pre_indices]
        distinct_pre_dates = sorted(set(pre_dates.tolist()))
        if len(distinct_pre_dates) < 3:
            continue

        calib_date_index = max(
            1,
            int(len(distinct_pre_dates) * 0.85),
        )
        calib_start = distinct_pre_dates[
            min(
                calib_date_index,
                len(distinct_pre_dates) - 1,
            )
        ]

        train_indices = pre_indices[
            (
                dates.iloc[pre_indices]
                < calib_start
            ).to_numpy()
        ]
        calib_indices = pre_indices[
            (
                dates.iloc[pre_indices]
                >= calib_start
            ).to_numpy()
        ]

        if (
            len(train_indices) == 0
            or len(calib_indices) == 0
            or len(test_indices) == 0
        ):
            continue

        folds.append({
            "fold": fold_number,
            "train_indices": train_indices,
            "calib_indices": calib_indices,
            "pre_indices": pre_indices,
            "test_indices": test_indices,
            "train_start": str(dates.iloc[train_indices[0]]),
            "train_end": str(dates.iloc[train_indices[-1]]),
            "calib_start": str(dates.iloc[calib_indices[0]]),
            "calib_end": str(dates.iloc[calib_indices[-1]]),
            "test_start": test_start,
            "test_end": test_end,
        })

    if len(folds) < 2:
        raise ValueError("Walk-forward plan produced fewer than two folds")
    return folds


def _evaluate_target_fold(
    X: np.ndarray,
    y: np.ndarray,
    fold: dict,
) -> dict | None:
    train_index = fold["train_indices"]
    calib_index = fold["calib_indices"]
    pre_index = fold["pre_indices"]
    test_index = fold["test_indices"]

    classes = sorted(np.unique(y[train_index]).tolist())
    if len(classes) < 2:
        return None

    calibration_scores = {}
    for name, model in _models().items():
        model.fit(X[train_index], y[train_index])
        probability = _aligned_predict_proba(
            model,
            X[calib_index],
            classes,
        )
        calibration_scores[name] = _probability_metrics(
            y[calib_index],
            probability,
            classes,
        )

    selected = min(
        calibration_scores,
        key=lambda name: (
            calibration_scores[name]["log_loss"],
            calibration_scores[name]["brier_multiclass"],
        ),
    )

    # Family selection used only the past calibration slice.  Refit the
    # selected family on all data available before the untouched test block.
    final_model = _models()[selected]
    final_model.fit(X[pre_index], y[pre_index])

    test_probability = _aligned_predict_proba(
        final_model,
        X[test_index],
        classes,
    )
    test_metrics = _probability_metrics(
        y[test_index],
        test_probability,
        classes,
    )

    baseline_probability = _baseline_probabilities(
        y[pre_index],
        len(test_index),
        classes,
    )
    baseline_metrics = _probability_metrics(
        y[test_index],
        baseline_probability,
        classes,
    )

    baseline_loss = baseline_metrics["log_loss"]
    challenger_loss = test_metrics["log_loss"]
    skill = (
        (baseline_loss - challenger_loss) / baseline_loss
        if baseline_loss > 0 else 0.0
    )

    return {
        "selected_family": selected,
        "classes": classes,
        "calibration_selection": calibration_scores,
        "test": test_metrics,
        "baseline_test": baseline_metrics,
        "log_loss_skill_vs_prior": round(float(skill), 6),
        "test_probabilities": test_probability,
        "baseline_probabilities": baseline_probability,
        "test_indices": test_index,
    }


def evaluate_walk_forward(
    features: pd.DataFrame,
    *,
    n_folds: int = 4,
) -> dict:
    if features.empty:
        raise ValueError("No football-first features are available")

    folds = temporal_folds(features, n_folds=n_folds)
    X = features[FEATURE_COLUMNS].astype(float).to_numpy()

    target_reports = {}

    for target, column in TARGET_COLUMNS.items():
        y = features[column].to_numpy()
        fold_reports = []
        all_test_indices = []
        all_probabilities = []
        all_baselines = []
        all_classes = []

        for fold in folds:
            result = _evaluate_target_fold(X, y, fold)
            if result is None:
                continue

            public = {
                "fold": fold["fold"],
                "train_start": fold["train_start"],
                "train_end": fold["train_end"],
                "calib_start": fold["calib_start"],
                "calib_end": fold["calib_end"],
                "test_start": fold["test_start"],
                "test_end": fold["test_end"],
                "train_n": len(fold["train_indices"]),
                "calib_n": len(fold["calib_indices"]),
                "test_n": len(fold["test_indices"]),
                "selected_family": result["selected_family"],
                "test": result["test"],
                "baseline_test": result["baseline_test"],
                "log_loss_skill_vs_prior": result[
                    "log_loss_skill_vs_prior"
                ],
            }
            fold_reports.append(public)

            # Segment aggregation needs a common class layout.  All current
            # targets should have stable classes; fail closed if not.
            classes = tuple(result["classes"])
            if all_classes and classes != all_classes[0]:
                continue
            if not all_classes:
                all_classes.append(classes)

            all_test_indices.extend(result["test_indices"].tolist())
            all_probabilities.append(result["test_probabilities"])
            all_baselines.append(result["baseline_probabilities"])

        skills = [
            row["log_loss_skill_vs_prior"]
            for row in fold_reports
        ]
        if not skills:
            target_reports[target] = {
                "status": "NO_EVALUATED_FOLDS",
            }
            continue

        segment_rows = []
        if all_probabilities and all_classes:
            classes = list(all_classes[0])
            test_indices = np.asarray(all_test_indices, dtype=int)
            probabilities = np.vstack(all_probabilities)
            baselines = np.vstack(all_baselines)
            test_frame = features.iloc[test_indices].reset_index(drop=True)
            test_y = y[test_indices]

            for league_id, local_frame in test_frame.groupby("league_id"):
                local_index = local_frame.index.to_numpy()
                if len(local_index) < MIN_SEGMENT_SAMPLES:
                    continue

                challenger_metrics = _probability_metrics(
                    test_y[local_index],
                    probabilities[local_index],
                    classes,
                )
                baseline_metrics = _probability_metrics(
                    test_y[local_index],
                    baselines[local_index],
                    classes,
                )
                base_loss = baseline_metrics["log_loss"]
                model_loss = challenger_metrics["log_loss"]
                segment_skill = (
                    (base_loss - model_loss) / base_loss
                    if base_loss > 0 else 0.0
                )
                segment_rows.append({
                    "league_id": int(league_id),
                    "competition": str(
                        local_frame["competition"].mode().iloc[0]
                    ),
                    "n": int(len(local_index)),
                    "test": challenger_metrics,
                    "baseline_test": baseline_metrics,
                    "log_loss_skill_vs_prior": round(
                        float(segment_skill),
                        6,
                    ),
                })

        segment_rows.sort(
            key=lambda item: (
                -item["n"],
                item["league_id"],
            )
        )

        median_skill = float(np.median(skills))
        minimum_skill = float(min(skills))
        positive_folds = sum(skill > 0 for skill in skills)

        target_reports[target] = {
            "status": "EVALUATED",
            "fold_count": len(fold_reports),
            "positive_skill_folds": positive_folds,
            "family_selection_counts": dict(
                Counter(
                    row["selected_family"]
                    for row in fold_reports
                )
            ),
            "median_log_loss_skill_vs_prior": round(
                median_skill,
                6,
            ),
            "minimum_log_loss_skill_vs_prior": round(
                minimum_skill,
                6,
            ),
            "maximum_log_loss_skill_vs_prior": round(
                float(max(skills)),
                6,
            ),
            "stable_positive_skill": (
                len(fold_reports) >= 3
                and positive_folds >= len(fold_reports) - 1
                and median_skill > 0
            ),
            "folds": fold_reports,
            "league_segments_min_100": segment_rows,
        }

    return {
        "schema": 1,
        "experiment": "football_first_walk_forward_v1",
        "fold_plan": [
            {
                key: value
                for key, value in fold.items()
                if not key.endswith("_indices")
            }
            for fold in folds
        ],
        "targets": target_reports,
        "minimum_segment_samples": MIN_SEGMENT_SAMPLES,
        "promotion_enabled": False,
        "live_adjustment_allowed": False,
        "promotion_state": "OFFLINE_ONLY",
        "next_stage_rule": (
            "A target is only a candidate for deeper shadow study when "
            "walk-forward skill is positive in all but at most one fold "
            "and median skill remains positive. This does not promote it."
        ),
    }
