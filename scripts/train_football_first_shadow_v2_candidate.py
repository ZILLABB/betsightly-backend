"""Freeze the validated 32-feature Match Result V2 candidate.

This artifact is deliberately separate from the active V1 shadow.
It is not wired into engine, publishing, Builder, booking or settlement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
import sklearn

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from leagues.football_first_challenger import (
    build_feature_frame,
    combine_results,
)
from leagues.football_first_runtime_core import (
    normalize_runtime_core_frame,
)
from leagues.football_first_runtime_elo import (
    attach_historical_runtime_elo,
)
from leagues.football_first_runtime_v2 import (
    REST_COLUMNS,
    V2_CANDIDATE_FEATURE_COLUMNS,
    V2_CANDIDATE_VERSION,
    attach_historical_context,
)
from leagues.football_first_stability import (
    _evaluate_target_fold,
    _models,
    temporal_folds,
)


DEFAULT_LEGACY = (
    ROOT / "data" / "api-football" / "matches.csv"
)

DEFAULT_HISTORY = (
    ROOT
    / "data"
    / "football_history"
    / "openfootball_matches.csv"
)

DEFAULT_SUPPLEMENTAL = (
    ROOT
    / "data"
    / "football_history"
    / "espn_missing_target_matches.csv"
)

DEFAULT_POLICY = (
    ROOT
    / "audit"
    / "football_first_runtime_v2_league_policy.json"
)

DEFAULT_OUTPUT = (
    ROOT
    / "models"
    / "football_first_shadow_v2_candidate"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(
                chunk
            )

    return digest.hexdigest()


def repo_relative(path: Path) -> str:
    resolved = path.resolve()

    try:
        return resolved.relative_to(
            ROOT.resolve()
        ).as_posix()
    except ValueError:
        return resolved.name


def choose_family(
    frame: pd.DataFrame,
    *,
    n_folds: int,
) -> tuple[str, dict]:

    folds = temporal_folds(
        frame,
        n_folds=n_folds,
    )

    X = frame[
        V2_CANDIDATE_FEATURE_COLUMNS
    ].astype(float).to_numpy()

    y = frame[
        "target_match_result"
    ].to_numpy()

    selections = []
    rows = []

    for fold in folds:
        result = _evaluate_target_fold(
            X,
            y,
            fold,
        )

        if result is None:
            continue

        family = result[
            "selected_family"
        ]

        selections.append(
            family
        )

        rows.append({
            "fold":
                int(
                    fold[
                        "fold"
                    ]
                ),

            "selected_family":
                family,

            "test_start":
                fold[
                    "test_start"
                ],

            "test_end":
                fold[
                    "test_end"
                ],

            "log_loss_skill_vs_prior":
                result[
                    "log_loss_skill_vs_prior"
                ],
        })

    if not selections:
        raise RuntimeError(
            "No V2 walk-forward model family was selected"
        )

    counts = Counter(
        selections
    )

    selected = sorted(
        counts,
        key=lambda family: (
            -counts[
                family
            ],
            0
            if family == "logistic"
            else 1,
            family,
        ),
    )[0]

    return selected, {
        "selection_counts":
            dict(
                counts
            ),
        "folds":
            rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--legacy",
        type=Path,
        default=DEFAULT_LEGACY,
    )

    parser.add_argument(
        "--football-history",
        type=Path,
        default=DEFAULT_HISTORY,
    )

    parser.add_argument(
        "--supplemental",
        type=Path,
        default=DEFAULT_SUPPLEMENTAL,
    )

    parser.add_argument(
        "--policy",
        type=Path,
        default=DEFAULT_POLICY,
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
    )

    parser.add_argument(
        "--folds",
        type=int,
        default=4,
    )

    args = parser.parse_args()

    if not args.policy.exists():
        raise SystemExit(
            "V2 league policy report is required before artifact freeze"
        )

    policy = json.loads(
        args.policy.read_text(
            encoding="utf-8"
        )
    )

    eligible_leagues = [
        int(value)
        for value in policy.get(
            "prospective_shadow_league_ids",
            [],
        )
    ]

    if not eligible_leagues:
        raise SystemExit(
            "V2 policy produced no identity-safe robust MR leagues"
        )

    if (
        policy.get(
            "automatic_promotion"
        )
        is not False
    ):
        raise SystemExit(
            "V2 policy must remain non-promoting"
        )

    legacy = pd.read_csv(
        args.legacy,
        low_memory=False,
    )

    history = pd.read_csv(
        args.football_history,
        low_memory=False,
    )

    if args.supplemental.exists():
        supplemental = pd.read_csv(
            args.supplemental,
            low_memory=False,
        )

        history = pd.concat(
            [
                history,
                supplemental,
            ],
            ignore_index=True,
            sort=False,
        )

    combined, combine_stats = combine_results(
        legacy,
        history,
    )

    features, feature_stats = build_feature_frame(
        combined
    )

    with_elo, elo_stats = attach_historical_runtime_elo(
        combined,
        features,
    )

    expanded, context_stats = attach_historical_context(
        combined,
        with_elo,
    )

    frame = normalize_runtime_core_frame(
        expanded
    )

    selected_family, selection = choose_family(
        frame,
        n_folds=args.folds,
    )

    X = frame[
        V2_CANDIDATE_FEATURE_COLUMNS
    ].astype(float).to_numpy()

    y = frame[
        "target_match_result"
    ].to_numpy()

    model = _models()[
        selected_family
    ]

    model.fit(
        X,
        y,
    )

    cutoff = str(
        pd.to_datetime(
            frame[
                "date"
            ]
        )
        .max()
        .date()
    )

    version = (
        "football-first-match-result-"
        "runtime-v2-candidate-32-"
        + cutoff.replace(
            "-",
            "",
        )
    )

    output = args.output_dir.resolve()

    output.mkdir(
        parents=True,
        exist_ok=True,
    )

    model_path = (
        output
        / "match_result.joblib"
    )

    meta_path = (
        output
        / "meta.json"
    )

    joblib.dump(
        model,
        model_path,
        compress=3,
    )

    sources = {}

    for name, source_path in (
        (
            "legacy",
            args.legacy,
        ),
        (
            "football_history",
            args.football_history,
        ),
        (
            "supplemental",
            args.supplemental,
        ),
    ):
        if source_path.exists():
            sources[name] = {
                "path":
                    repo_relative(
                        source_path
                    ),
                "sha256":
                    sha256(
                        source_path
                    ),
            }

    meta = {
        "schema": 1,

        "model_version":
            version,

        "target":
            "match_result",

        "feature_version":
            V2_CANDIDATE_VERSION,

        "feature_count":
            len(
                V2_CANDIDATE_FEATURE_COLUMNS
            ),

        "feature_columns":
            list(
                V2_CANDIDATE_FEATURE_COLUMNS
            ),

        "rest_features_excluded":
            list(
                REST_COLUMNS
            ),

        "rest_exclusion_reason":
            (
                "The 32-feature Elo + base-rate + venue "
                "candidate outperformed the 38-feature "
                "rest variant on Match Result, Over 1.5 "
                "and Over 2.5 in Phase 8B.6."
            ),

        "selected_family":
            selected_family,

        "walk_forward_family_selection":
            selection,

        "training_cutoff":
            cutoff,

        "trained_samples":
            int(
                len(
                    frame
                )
            ),

        "eligible_league_ids":
            eligible_leagues,

        "league_policy": {
            "path":
                repo_relative(
                    args.policy
                ),

            "sha256":
                sha256(
                    args.policy
                ),

            "counts_as_prospective_evidence":
                False,
        },

        "class_mapping": {
            "0":
                "away_win",
            "1":
                "draw",
            "2":
                "home_win",
        },

        "combined_results":
            combine_stats,

        "raw_feature_build":
            feature_stats,

        "runtime_elo_build":
            elo_stats,

        "runtime_context_build":
            context_stats,

        "source_files":
            sources,

        "runtime": {
            "python":
                platform.python_version(),

            "scikit_learn":
                sklearn.__version__,

            "joblib":
                joblib.__version__,
        },

        "trained_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "prospective_observation_started_at":
            None,

        "candidate_only":
            True,

        "shadow_only":
            True,

        "engine_integration":
            False,

        "publishable":
            False,

        "live_adjustment_allowed":
            False,

        "automatic_promotion":
            False,

        "production_promotion_credit":
            False,

        "promotion_state":
            "FROZEN_OFFLINE_V2_CANDIDATE",

        "remaining_blockers": [
            "candidate_not_wired_to_runtime_shadow",
            "v2_prospective_evidence_not_started",
            "historical_base_rate_prior_universe_incomplete",
            "historical_tournament_neutral_context_not_available",
            "korea_saudi_historical_coverage_missing",
        ],
    }

    meta["artifact"] = {
        "path":
            repo_relative(
                model_path
            ),

        "sha256":
            sha256(
                model_path
            ),

        "bytes":
            model_path.stat().st_size,
    }

    meta_path.write_text(
        json.dumps(
            meta,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    print(
        "FOOTBALL-FIRST V2 CANDIDATE ARTIFACT"
    )

    print(
        f"model_version: "
        f"{version}"
    )

    print(
        f"selected_family: "
        f"{selected_family}"
    )

    print(
        "walk_forward_family_selection: "
        f"{selection['selection_counts']}"
    )

    print(
        f"training_cutoff: "
        f"{cutoff}"
    )

    print(
        f"trained_samples: "
        f"{len(frame):,}"
    )

    print(
        "feature_count: "
        f"{len(V2_CANDIDATE_FEATURE_COLUMNS)}"
    )

    print(
        "eligible_league_ids: "
        f"{eligible_leagues}"
    )

    print(
        "rest_features_included: False"
    )

    print(
        "candidate_only: True"
    )

    print(
        "engine_integration: False"
    )

    print(
        "automatic_promotion: False"
    )

    print(
        f"artifact_sha256: "
        f"{meta['artifact']['sha256']}"
    )

    print(
        f"model: "
        f"{model_path}"
    )

    print(
        f"meta: "
        f"{meta_path}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
