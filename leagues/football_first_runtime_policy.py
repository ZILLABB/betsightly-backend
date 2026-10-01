
"""League × target policy for the runtime-compatible football-first core.

This repeats Phase 7C's league evidence rules using ONLY the exact feature
contract that Phase 7D proved can be reproduced by live HistoryIndex.

It is still historical/offline evidence.  It cannot promote a live model and
does not count toward model_policy.py's prospective observation threshold.
"""
from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from leagues.football_first_challenger import (
    TARGET_COLUMNS,
    _probability_metrics,
)
from leagues.football_first_runtime_core import (
    RUNTIME_CORE_VERSION,
    RUNTIME_FEATURE_COLUMNS,
    normalize_runtime_core_frame,
)
from leagues.football_first_stability import (
    _evaluate_target_fold,
    temporal_folds,
)

MIN_FOLD_SEGMENT_SAMPLES = 30
MIN_EVALUABLE_FOLDS = 2
PROMISING_MIN_TOTAL_OOS = 100
ROBUST_MIN_TOTAL_OOS = 200

ROBUST = "ROBUST_RUNTIME_CANDIDATE"
PROMISING = "PROMISING_RUNTIME_CANDIDATE"
MIXED = "MIXED_RUNTIME_EVIDENCE"
INSUFFICIENT = "INSUFFICIENT_RUNTIME_SAMPLE"


def _skill(model_metrics: dict, baseline_metrics: dict) -> float:
    baseline = float(baseline_metrics["log_loss"])
    model = float(model_metrics["log_loss"])
    if baseline <= 0:
        return 0.0
    return (baseline - model) / baseline


def _competition_name(frame: pd.DataFrame) -> str:
    values = frame["competition"].dropna().astype(str)
    if values.empty:
        return "unknown"
    mode = values.mode()
    return str(mode.iloc[0] if not mode.empty else values.iloc[0])


def derive_runtime_league_target_evidence(
    features: pd.DataFrame,
    *,
    n_folds: int = 4,
) -> dict:
    frame = normalize_runtime_core_frame(features)
    folds = temporal_folds(frame, n_folds=n_folds)
    X = frame[
        RUNTIME_FEATURE_COLUMNS
    ].astype(float).to_numpy()

    targets = {}

    for target, column in TARGET_COLUMNS.items():
        y = frame[column].to_numpy()

        league_fold_rows: dict[int, list[dict]] = defaultdict(list)
        target_fold_skills: list[float] = []
        target_families: Counter[str] = Counter()

        pooled_indices: list[int] = []
        pooled_probabilities: list[np.ndarray] = []
        pooled_baselines: list[np.ndarray] = []
        pooled_classes: tuple | None = None

        for fold in folds:
            result = _evaluate_target_fold(
                X,
                y,
                fold,
            )
            if result is None:
                continue

            target_fold_skills.append(
                float(
                    result[
                        "log_loss_skill_vs_prior"
                    ]
                )
            )
            target_families[
                result["selected_family"]
            ] += 1

            classes = tuple(
                result["classes"]
            )
            if pooled_classes is None:
                pooled_classes = classes
            elif classes != pooled_classes:
                continue

            test_indices = np.asarray(
                result["test_indices"],
                dtype=int,
            )
            probabilities = np.asarray(
                result[
                    "test_probabilities"
                ],
                dtype=float,
            )
            baselines = np.asarray(
                result[
                    "baseline_probabilities"
                ],
                dtype=float,
            )
            test_frame = frame.iloc[
                test_indices
            ].reset_index(drop=True)
            test_y = y[test_indices]

            pooled_indices.extend(
                test_indices.tolist()
            )
            pooled_probabilities.append(
                probabilities
            )
            pooled_baselines.append(
                baselines
            )

            for (
                league_id,
                local_frame,
            ) in test_frame.groupby(
                "league_id"
            ):
                local_index = (
                    local_frame.index.to_numpy()
                )
                if (
                    len(local_index)
                    < MIN_FOLD_SEGMENT_SAMPLES
                ):
                    continue

                model_metrics = (
                    _probability_metrics(
                        test_y[local_index],
                        probabilities[
                            local_index
                        ],
                        classes,
                    )
                )
                baseline_metrics = (
                    _probability_metrics(
                        test_y[local_index],
                        baselines[
                            local_index
                        ],
                        classes,
                    )
                )

                league_fold_rows[
                    int(league_id)
                ].append({
                    "fold": int(
                        fold["fold"]
                    ),
                    "test_start": (
                        fold["test_start"]
                    ),
                    "test_end": (
                        fold["test_end"]
                    ),
                    "n": int(
                        len(local_index)
                    ),
                    "competition": (
                        _competition_name(
                            local_frame
                        )
                    ),
                    "selected_family": (
                        result[
                            "selected_family"
                        ]
                    ),
                    "test": model_metrics,
                    "baseline_test": (
                        baseline_metrics
                    ),
                    "log_loss_skill_vs_prior": round(
                        float(
                            _skill(
                                model_metrics,
                                baseline_metrics,
                            )
                        ),
                        6,
                    ),
                })

        overall_stable = bool(
            len(target_fold_skills) >= 3
            and sum(
                value > 0
                for value
                in target_fold_skills
            )
            >= len(target_fold_skills) - 1
            and float(
                np.median(
                    target_fold_skills
                )
            )
            > 0
        )

        pooled_by_league = {}

        if (
            pooled_probabilities
            and pooled_classes is not None
        ):
            indices = np.asarray(
                pooled_indices,
                dtype=int,
            )
            probabilities = np.vstack(
                pooled_probabilities
            )
            baselines = np.vstack(
                pooled_baselines
            )
            pooled_frame = frame.iloc[
                indices
            ].reset_index(drop=True)
            pooled_y = y[indices]
            classes = list(
                pooled_classes
            )

            for (
                league_id,
                local_frame,
            ) in pooled_frame.groupby(
                "league_id"
            ):
                local_index = (
                    local_frame.index.to_numpy()
                )
                if (
                    len(local_index)
                    < PROMISING_MIN_TOTAL_OOS
                ):
                    continue

                model_metrics = (
                    _probability_metrics(
                        pooled_y[
                            local_index
                        ],
                        probabilities[
                            local_index
                        ],
                        classes,
                    )
                )
                baseline_metrics = (
                    _probability_metrics(
                        pooled_y[
                            local_index
                        ],
                        baselines[
                            local_index
                        ],
                        classes,
                    )
                )

                pooled_by_league[
                    int(league_id)
                ] = {
                    "league_id": int(
                        league_id
                    ),
                    "competition": (
                        _competition_name(
                            local_frame
                        )
                    ),
                    "n": int(
                        len(local_index)
                    ),
                    "test": model_metrics,
                    "baseline_test": (
                        baseline_metrics
                    ),
                    "log_loss_skill_vs_prior": round(
                        float(
                            _skill(
                                model_metrics,
                                baseline_metrics,
                            )
                        ),
                        6,
                    ),
                }

        league_ids = sorted(
            set(pooled_by_league)
            | set(league_fold_rows)
        )
        evidence_rows = []

        for league_id in league_ids:
            pooled = pooled_by_league.get(
                league_id
            )
            fold_rows = (
                league_fold_rows.get(
                    league_id,
                    [],
                )
            )

            total_n = (
                int(pooled["n"])
                if pooled
                else sum(
                    int(row["n"])
                    for row in fold_rows
                )
            )
            aggregate_skill = (
                float(
                    pooled[
                        "log_loss_skill_vs_prior"
                    ]
                )
                if pooled
                else None
            )
            fold_skills = [
                float(
                    row[
                        "log_loss_skill_vs_prior"
                    ]
                )
                for row in fold_rows
            ]
            positive_folds = sum(
                value > 0
                for value in fold_skills
            )
            evaluable_folds = len(
                fold_skills
            )
            median_skill = (
                float(
                    np.median(
                        fold_skills
                    )
                )
                if fold_skills
                else None
            )
            minimum_skill = (
                float(
                    min(
                        fold_skills
                    )
                )
                if fold_skills
                else None
            )

            robust = bool(
                overall_stable
                and total_n
                >= ROBUST_MIN_TOTAL_OOS
                and evaluable_folds >= 3
                and positive_folds
                >= evaluable_folds - 1
                and median_skill is not None
                and median_skill > 0
                and aggregate_skill is not None
                and aggregate_skill > 0
            )

            promising = bool(
                overall_stable
                and total_n
                >= PROMISING_MIN_TOTAL_OOS
                and evaluable_folds
                >= MIN_EVALUABLE_FOLDS
                and positive_folds
                >= max(
                    1,
                    evaluable_folds - 1,
                )
                and aggregate_skill
                is not None
                and aggregate_skill > 0
            )

            if robust:
                state = ROBUST
            elif promising:
                state = PROMISING
            elif (
                total_n
                >= PROMISING_MIN_TOTAL_OOS
            ):
                state = MIXED
            else:
                state = INSUFFICIENT

            competition = (
                pooled["competition"]
                if pooled
                else (
                    fold_rows[0][
                        "competition"
                    ]
                    if fold_rows
                    else "unknown"
                )
            )

            evidence_rows.append({
                "league_id": (
                    league_id
                ),
                "competition": (
                    competition
                ),
                "target": target,
                "state": state,
                "total_oos_n": (
                    total_n
                ),
                "aggregate_log_loss_skill_vs_prior": (
                    round(
                        aggregate_skill,
                        6,
                    )
                    if aggregate_skill
                    is not None
                    else None
                ),
                "evaluable_folds": (
                    evaluable_folds
                ),
                "positive_skill_folds": (
                    positive_folds
                ),
                "median_fold_skill": (
                    round(
                        median_skill,
                        6,
                    )
                    if median_skill
                    is not None
                    else None
                ),
                "minimum_fold_skill": (
                    round(
                        minimum_skill,
                        6,
                    )
                    if minimum_skill
                    is not None
                    else None
                ),
                "folds": fold_rows,
                "runtime_feature_version": (
                    RUNTIME_CORE_VERSION
                ),
                "offline_only": True,
                "production_promotion_credit": False,
            })

        counts = Counter(
            row["state"]
            for row in evidence_rows
        )
        targets[target] = {
            "global_walk_forward": {
                "fold_count": len(
                    target_fold_skills
                ),
                "positive_skill_folds": sum(
                    value > 0
                    for value
                    in target_fold_skills
                ),
                "median_skill": (
                    round(
                        float(
                            np.median(
                                target_fold_skills
                            )
                        ),
                        6,
                    )
                    if target_fold_skills
                    else None
                ),
                "minimum_skill": (
                    round(
                        float(
                            min(
                                target_fold_skills
                            )
                        ),
                        6,
                    )
                    if target_fold_skills
                    else None
                ),
                "stable_positive_skill": (
                    overall_stable
                ),
                "family_selection_counts": dict(
                    target_families
                ),
            },
            "state_counts": dict(
                counts
            ),
            "league_evidence": (
                evidence_rows
            ),
        }

    return {
        "schema": 1,
        "experiment": (
            "football_first_runtime_league_target_policy_v1"
        ),
        "runtime_feature_version": (
            RUNTIME_CORE_VERSION
        ),
        "runtime_feature_columns": list(
            RUNTIME_FEATURE_COLUMNS
        ),
        "thresholds": {
            "min_fold_segment_samples": (
                MIN_FOLD_SEGMENT_SAMPLES
            ),
            "min_evaluable_folds": (
                MIN_EVALUABLE_FOLDS
            ),
            "promising_min_total_oos": (
                PROMISING_MIN_TOTAL_OOS
            ),
            "robust_min_total_oos": (
                ROBUST_MIN_TOTAL_OOS
            ),
        },
        "targets": targets,
        "automatic_promotion": False,
        "live_adjustment_allowed": False,
        "counts_as_prospective_model_policy_evidence": False,
        "prospective_shadow_allowlist_ready": bool(
            targets.get(
                "match_result",
                {},
            )
            .get(
                "state_counts",
                {},
            )
            .get(
                ROBUST,
                0,
            )
            > 0
        ),
        "next_step": (
            "Use only ROBUST_RUNTIME_CANDIDATE cells to seed "
            "prospective shadow collection. Historical evidence itself "
            "does not count toward live promotion."
        ),
    }
