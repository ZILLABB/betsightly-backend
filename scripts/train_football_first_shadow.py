
"""Train and freeze the first runtime-compatible football-first shadow model.

This command writes ONLY a Match Result shadow artifact.  It does not modify
the deployed API-Football ensemble and does not wire the artifact into engine.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from leagues.football_first_challenger import (
    build_feature_frame,
    combine_results,
)
from leagues.football_first_runtime_core import (
    RUNTIME_CORE_VERSION,
    RUNTIME_FEATURE_COLUMNS,
    normalize_runtime_core_frame,
)
from leagues.football_first_stability import (
    _evaluate_target_fold,
    _models,
    temporal_folds,
)

DEFAULT_LEGACY = (
    ROOT
    / "data"
    / "api-football"
    / "matches.csv"
)
DEFAULT_HISTORY = (
    ROOT
    / "data"
    / "football_history"
    / "openfootball_matches.csv"
)
DEFAULT_OUTPUT = (
    ROOT
    / "models"
    / "football_first_shadow"
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
    frame,
    *,
    n_folds: int = 4,
) -> tuple[str, dict]:
    folds = temporal_folds(
        frame,
        n_folds=n_folds,
    )
    X = frame[
        RUNTIME_FEATURE_COLUMNS
    ].astype(float).to_numpy()
    y = frame[
        "target_match_result"
    ].to_numpy()

    selections = []
    fold_rows = []

    for fold in folds:
        result = (
            _evaluate_target_fold(
                X,
                y,
                fold,
            )
        )
        if result is None:
            continue

        family = result[
            "selected_family"
        ]
        selections.append(
            family
        )
        fold_rows.append({
            "fold": int(
                fold["fold"]
            ),
            "selected_family": (
                family
            ),
            "test_start": (
                fold["test_start"]
            ),
            "test_end": (
                fold["test_end"]
            ),
            "log_loss_skill_vs_prior": (
                result[
                    "log_loss_skill_vs_prior"
                ]
            ),
        })

    if not selections:
        raise RuntimeError(
            "No walk-forward family selection was produced"
        )

    counts = Counter(
        selections
    )
    # Highest walk-forward selection count wins.  A tie is deliberately
    # resolved toward logistic because it is simpler, smaller and the Phase
    # 7D evaluation already showed it competitive under this feature contract.
    ordered = sorted(
        counts,
        key=lambda family: (
            -counts[family],
            0
            if family == "logistic"
            else 1,
            family,
        ),
    )
    selected = ordered[0]

    return selected, {
        "selection_counts": dict(
            counts
        ),
        "folds": fold_rows,
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

    legacy = pd.read_csv(
        args.legacy,
        low_memory=False,
    )
    history = pd.read_csv(
        args.football_history,
        low_memory=False,
    )

    combined, combine_stats = (
        combine_results(
            legacy,
            history,
        )
    )
    features, feature_stats = (
        build_feature_frame(
            combined
        )
    )
    frame = (
        normalize_runtime_core_frame(
            features
        )
    )

    selected_family, selection = (
        choose_family(
            frame,
            n_folds=args.folds,
        )
    )

    X = frame[
        RUNTIME_FEATURE_COLUMNS
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

    training_cutoff = str(
        pd.to_datetime(
            frame["date"]
        ).max().date()
    )

    model_version = (
        "football-first-match-result-"
        "runtime-core-v1-"
        + training_cutoff.replace(
            "-",
            "",
        )
    )

    output = (
        args.output_dir.resolve()
    )
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

    import platform
    import sklearn
    import joblib as joblib_package

    meta = {
        "schema": 2,
        "model_version": (
            model_version
        ),
        "target": (
            "match_result"
        ),
        "feature_version": (
            RUNTIME_CORE_VERSION
        ),
        "runtime_core": {
            "feature_count": len(
                RUNTIME_FEATURE_COLUMNS
            ),
            "feature_columns": list(
                RUNTIME_FEATURE_COLUMNS
            ),
        },
        "feature_columns": list(
            RUNTIME_FEATURE_COLUMNS
        ),
        "selected_family": (
            selected_family
        ),
        "walk_forward_family_selection": (
            selection
        ),
        "training_cutoff": (
            training_cutoff
        ),
        "trained_samples": int(
            len(frame)
        ),
        "class_mapping": {
            "0": "away_win",
            "1": "draw",
            "2": "home_win",
        },
        "combined_results": (
            combine_stats
        ),
        "raw_feature_build": (
            feature_stats
        ),
        "source_files": {
            "legacy": {
                "path": repo_relative(
                    args.legacy
                ),
                "sha256": sha256(
                    args.legacy
                ),
            },
            "football_history": {
                "path": repo_relative(
                    args.football_history
                ),
                "sha256": sha256(
                    args.football_history
                ),
            },
        },
        "runtime": {
            "python": platform.python_version(),
            "scikit_learn": sklearn.__version__,
            "joblib": joblib_package.__version__,
        },
        "trained_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
        "prospective_observation_started_at": None,
        "shadow_only": True,
        "publishable": False,
        "live_adjustment_allowed": False,
        "automatic_promotion": False,
    }

    meta["artifact"] = {
        "path": repo_relative(
            model_path
        ),
        "sha256": sha256(
            model_path
        ),
        "bytes": model_path.stat().st_size,
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
        "FOOTBALL-FIRST SHADOW ARTIFACT"
    )
    print(
        f"model_version: "
        f"{model_version}"
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
        f"{training_cutoff}"
    )
    print(
        f"trained_samples: "
        f"{len(frame):,}"
    )
    print(
        f"feature_count: "
        f"{len(RUNTIME_FEATURE_COLUMNS)}"
    )
    print(
        "shadow_only: True"
    )
    print(
        "engine_integration: False"
    )
    print(
        f"model: {model_path}"
    )
    print(
        f"meta: {meta_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
