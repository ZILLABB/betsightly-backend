from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from leagues.football_first_challenger import (
    build_feature_frame,
    combine_results,
)
from leagues.football_first_runtime_elo import (
    attach_historical_runtime_elo,
)
from leagues.football_first_runtime_v2 import (
    attach_historical_context,
)
from leagues.football_first_runtime_v2_policy import (
    ROBUST,
    derive_runtime_v2_league_target_evidence,
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

DEFAULT_REPORT = (
    ROOT
    / "audit"
    / "football_first_runtime_v2_league_policy.json"
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

    report = derive_runtime_v2_league_target_evidence(
        expanded,
        n_folds=args.folds,
    )

    report["combined_results"] = combine_stats
    report["feature_build"] = feature_stats
    report["runtime_elo_build"] = elo_stats
    report["runtime_context_build"] = context_stats

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
        "PHASE 8 FINAL V2 LEAGUE POLICY"
    )

    print(
        f"candidate: "
        f"{report['candidate_version']}"
    )

    print(
        f"features: "
        f"{report['candidate_feature_count']}"
    )

    for target, result in report[
        "targets"
    ].items():

        counts = result[
            "state_counts"
        ]

        global_result = result[
            "global_walk_forward"
        ]

        print(
            f"{target}: "
            f"global_stable="
            f"{global_result['stable_positive_skill']} "
            f"robust="
            f"{counts.get(ROBUST, 0)} "
            f"promising="
            f"{counts.get('PROMISING_RUNTIME_CANDIDATE', 0)} "
            f"mixed="
            f"{counts.get('MIXED_RUNTIME_EVIDENCE', 0)} "
            f"insufficient="
            f"{counts.get('INSUFFICIENT_RUNTIME_SAMPLE', 0)}"
        )

        robust = [
            row
            for row in result[
                "league_evidence"
            ]
            if row["state"] == ROBUST
        ]

        robust.sort(
            key=lambda row: (
                -(
                    row[
                        "aggregate_log_loss_skill_vs_prior"
                    ]
                    or 0
                ),
                -row[
                    "total_oos_n"
                ],
            )
        )

        for row in robust:
            print(
                f"  ROBUST "
                f"{row['league_id']} "
                f"{row['competition']}: "
                f"n={row['total_oos_n']} "
                f"skill="
                f"{row['aggregate_log_loss_skill_vs_prior'] * 100:.2f}% "
                f"folds="
                f"{row['positive_skill_folds']}/"
                f"{row['evaluable_folds']}"
            )

    print(
        "MR robust leagues: "
        f"{report['match_result_robust_league_ids']}"
    )

    print(
        "MR identity-safe prospective leagues: "
        f"{report['prospective_shadow_league_ids']}"
    )

    print(
        "automatic_promotion: False"
    )

    print(
        "prospective_model_policy_credit: False"
    )

    print(
        f"report: {args.report.resolve()}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
