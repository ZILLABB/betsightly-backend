from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )

from leagues.football_first_challenger import (
    build_feature_frame,
    combine_results,
)

from leagues.football_first_runtime_elo import (
    attach_historical_runtime_elo,
)

from leagues.football_first_runtime_v2 import (
    attach_historical_context,
    evaluate_runtime_v2,
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

DEFAULT_SUPPLEMENTAL = (
    ROOT
    / "data"
    / "football_history"
    / "espn_missing_target_matches.csv"
)

DEFAULT_REPORT = (
    ROOT
    / "audit"
    / "football_first_runtime_v2.json"
)


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
        "--folds",
        type=int,
        default=4,
    )

    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
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

    with_elo, elo_stats = (
        attach_historical_runtime_elo(
            combined,
            features,
        )
    )

    expanded, context_stats = (
        attach_historical_context(
            combined,
            with_elo,
        )
    )

    report = evaluate_runtime_v2(
        expanded,
        n_folds=args.folds,
    )

    report[
        "combined_results"
    ] = combine_stats

    report[
        "feature_build"
    ] = feature_stats

    report[
        "runtime_elo_build"
    ] = elo_stats

    report[
        "runtime_context_build"
    ] = context_stats

    args.report.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args.report.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    print(
        "PHASE 8B.3-8B.6 RUNTIME V2"
    )

    print(
        f"results="
        f"{combine_stats['unique_rows']:,} "
        f"trainable="
        f"{feature_stats['trainable_samples']:,}"
    )

    print(
        f"base availability: "
        f"{context_stats['base_available']:,}/"
        f"{context_stats['samples']:,} "
        f"("
        f"{context_stats['base_availability_rate'] * 100:.2f}"
        f"%)"
    )

    print(
        "historical base prior universe complete: "
        f"{context_stats['base_rate_prior_universe_complete']}"
    )

    order = [
        "runtime_core_v1",
        "runtime_core_plus_elo",
        "runtime_core_plus_elo_base",
        "runtime_core_plus_elo_base_venue",
        "runtime_v2_full",
    ]

    for (
        target,
        variants,
    ) in report[
        "targets"
    ].items():

        print(
            target
            + ":"
        )

        for name in order:

            row = variants[
                name
            ]

            skill = (
                row[
                    "median_skill"
                ]
                or 0
            ) * 100

            delta = (
                row[
                    "delta_vs_core"
                ]
                or 0
            ) * 100

            print(
                f"  {name}: "
                f"skill={skill:.2f}% "
                f"delta_vs_core="
                f"{delta:+.2f}pp "
                f"positive="
                f"{row['positive_skill_folds']}/"
                f"{row['fold_count']} "
                f"features="
                f"{row['feature_count']}"
            )

    print(
        "runtime artifact ready: False"
    )

    print(
        "automatic_promotion: False"
    )

    print(
        f"report: "
        f"{args.report.resolve()}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
