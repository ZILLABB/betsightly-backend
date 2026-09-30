
"""Runtime-compatible football-first challenger feature contract.

This is the bridge between offline Phase 7 evidence and future prospective
shadow inference.  It deliberately uses only features that BetSightly's live
HistoryIndex can reproduce with the same formulas.

Excluded for now:
- competition/base-rate features (runtime uses 45-day shrunk hierarchy)
- Elo (runtime uses a different goal-difference/context policy)
- venue features (fallback contract differs when venue history is absent)
- rest features (offline calendar-day normalization differs from runtime hours)

Nothing here changes live predictions.
"""
from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd

from leagues.football_first_challenger import (
    TARGET_COLUMNS,
)
from leagues.football_first_stability import (
    _evaluate_target_fold,
    temporal_folds,
)

RUNTIME_CORE_VERSION = "football-first-runtime-core-v1"

RUNTIME_FEATURE_COLUMNS = [
    "home_win_rate_5",
    "home_win_rate_10",
    "home_draw_rate_5",
    "home_goals_scored_5",
    "home_goals_conceded_5",
    "away_win_rate_5",
    "away_win_rate_10",
    "away_draw_rate_5",
    "away_goals_scored_5",
    "away_goals_conceded_5",
    "h2h_home_win_rate",
    "h2h_avg_goals",
    "h2h_btts_rate",
    "h2h_meetings",
    "national_team_match",
]

# Must match leagues.team_history.HistoryIndex.head_to_head() when no meetings
# exist.  The Phase-7A exploratory feature builder used slightly different
# neutral values; normalize those rows before runtime-core evaluation.
RUNTIME_NO_H2H = {
    "h2h_home_win_rate": 0.40,
    "h2h_avg_goals": 2.70,
    "h2h_btts_rate": 0.52,
    "h2h_meetings": 0.0,
}

MIN_TEAM_HISTORY = 5


def normalize_runtime_core_frame(features: pd.DataFrame) -> pd.DataFrame:
    """Return a copy whose retained feature semantics match live HistoryIndex."""
    frame = features.copy()

    if "h2h_meetings" not in frame:
        raise ValueError("h2h_meetings is required for runtime normalization")

    no_h2h = frame["h2h_meetings"].astype(float) <= 0
    for column, value in RUNTIME_NO_H2H.items():
        frame.loc[no_h2h, column] = value

    missing = [
        column
        for column in RUNTIME_FEATURE_COLUMNS
        if column not in frame.columns
    ]
    if missing:
        raise ValueError(
            "Missing runtime-core features: "
            + ", ".join(missing)
        )
    return frame


def runtime_feature_vector(fixture: dict, index) -> dict:
    """Build the exact runtime-core vector from the live HistoryIndex.

    Fail closed when either team lacks the five completed matches required by
    the offline challenger warm-up contract.
    """
    team_type = fixture.get("team_type") or "CLUB"
    home = (fixture.get("home") or {}).get("name") or ""
    away = (fixture.get("away") or {}).get("name") or ""

    home_rows = index.by_team.get((team_type, home)) or []
    away_rows = index.by_team.get((team_type, away)) or []

    if min(len(home_rows), len(away_rows)) < MIN_TEAM_HISTORY:
        return {
            "status": "INSUFFICIENT_HISTORY",
            "feature_version": RUNTIME_CORE_VERSION,
            "required_team_history": MIN_TEAM_HISTORY,
            "home_history": len(home_rows),
            "away_history": len(away_rows),
            "features": None,
            "vector": None,
        }

    home_form = index.team_form(
        home,
        "home",
        team_type,
    )
    away_form = index.team_form(
        away,
        "away",
        team_type,
    )
    h2h = index.head_to_head(
        home,
        away,
        10,
        team_type,
    )

    values = {
        "home_win_rate_5": home_form["win_rate_5"],
        "home_win_rate_10": home_form["win_rate_10"],
        "home_draw_rate_5": home_form["draw_rate_5"],
        "home_goals_scored_5": home_form["goals_scored_5"],
        "home_goals_conceded_5": home_form["goals_conceded_5"],
        "away_win_rate_5": away_form["win_rate_5"],
        "away_win_rate_10": away_form["win_rate_10"],
        "away_draw_rate_5": away_form["draw_rate_5"],
        "away_goals_scored_5": away_form["goals_scored_5"],
        "away_goals_conceded_5": away_form["goals_conceded_5"],
        "h2h_home_win_rate": h2h["home_win_rate"],
        "h2h_avg_goals": h2h["avg_goals"],
        "h2h_btts_rate": h2h["btts_rate"],
        "h2h_meetings": min(int(h2h["meetings"]), 10) / 10.0,
        "national_team_match": 1.0 if team_type == "NATIONAL" else 0.0,
    }

    return {
        "status": "READY",
        "feature_version": RUNTIME_CORE_VERSION,
        "required_team_history": MIN_TEAM_HISTORY,
        "home_history": len(home_rows),
        "away_history": len(away_rows),
        "features": values,
        "vector": [
            float(values[column])
            for column in RUNTIME_FEATURE_COLUMNS
        ],
    }


def evaluate_runtime_core_walk_forward(
    features: pd.DataFrame,
    *,
    n_folds: int = 4,
) -> dict:
    """Re-run walk-forward evidence using only reproducible runtime features."""
    frame = normalize_runtime_core_frame(features)
    folds = temporal_folds(
        frame,
        n_folds=n_folds,
    )
    X = frame[
        RUNTIME_FEATURE_COLUMNS
    ].astype(float).to_numpy()

    targets = {}

    for target, column in TARGET_COLUMNS.items():
        y = frame[column].to_numpy()
        fold_rows = []

        for fold in folds:
            result = _evaluate_target_fold(
                X,
                y,
                fold,
            )
            if result is None:
                continue

            fold_rows.append({
                "fold": int(fold["fold"]),
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
            })

        skills = [
            float(row["log_loss_skill_vs_prior"])
            for row in fold_rows
        ]
        positive = sum(
            value > 0
            for value in skills
        )
        median = (
            float(np.median(skills))
            if skills
            else None
        )
        minimum = (
            float(min(skills))
            if skills
            else None
        )

        targets[target] = {
            "status": (
                "EVALUATED"
                if skills
                else "NO_EVALUATED_FOLDS"
            ),
            "fold_count": len(fold_rows),
            "positive_skill_folds": positive,
            "family_selection_counts": dict(
                Counter(
                    row["selected_family"]
                    for row in fold_rows
                )
            ),
            "median_log_loss_skill_vs_prior": (
                round(median, 6)
                if median is not None
                else None
            ),
            "minimum_log_loss_skill_vs_prior": (
                round(minimum, 6)
                if minimum is not None
                else None
            ),
            "maximum_log_loss_skill_vs_prior": (
                round(float(max(skills)), 6)
                if skills
                else None
            ),
            "stable_positive_skill": bool(
                len(fold_rows) >= 3
                and positive >= len(fold_rows) - 1
                and median is not None
                and median > 0
            ),
            "folds": fold_rows,
        }

    return {
        "schema": 1,
        "experiment": "football_first_runtime_core_walk_forward_v1",
        "feature_version": RUNTIME_CORE_VERSION,
        "feature_columns": list(
            RUNTIME_FEATURE_COLUMNS
        ),
        "feature_count": len(
            RUNTIME_FEATURE_COLUMNS
        ),
        "excluded_training_features": [
            "competition_home_goals",
            "competition_away_goals",
            "competition_over_1_5_rate",
            "competition_over_2_5_rate",
            "competition_btts_rate",
            "elo_home_expectation",
            "elo_diff_scaled",
            "home_rest_days_scaled",
            "away_rest_days_scaled",
            "home_home_win_rate_5",
            "home_home_goals_5",
            "away_away_win_rate_5",
            "away_away_goals_5",
        ],
        "market_price_features_used": [],
        "targets": targets,
        "runtime_shadow_ready": all(
            result.get("stable_positive_skill") is True
            for target, result in targets.items()
            if target == "match_result"
        ),
        "automatic_promotion": False,
        "live_adjustment_allowed": False,
        "prospective_observation_started": False,
        "promotion_state": "OFFLINE_RUNTIME_PARITY_EVALUATION",
    }
