
"""Generate BetSightly's offline league × target evidence matrix."""
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
from leagues.football_first_league_policy import (
    derive_league_target_evidence,
)

DEFAULT_LEGACY = ROOT / "data" / "api-football" / "matches.csv"
DEFAULT_HISTORY = (
    ROOT / "data" / "football_history" / "openfootball_matches.csv"
)
DEFAULT_REPORT = (
    ROOT / "audit" / "football_first_league_target_policy.json"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy", type=Path, default=DEFAULT_LEGACY)
    parser.add_argument(
        "--football-history",
        type=Path,
        default=DEFAULT_HISTORY,
    )
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    legacy = pd.read_csv(args.legacy, low_memory=False)
    history = pd.read_csv(args.football_history, low_memory=False)
    combined, _ = combine_results(legacy, history)
    features, _ = build_feature_frame(combined)

    report = derive_league_target_evidence(
        features,
        n_folds=args.folds,
    )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print("FOOTBALL-FIRST LEAGUE × TARGET POLICY")
    for target, result in report["targets"].items():
        counts = result["state_counts"]
        global_result = result["global_walk_forward"]
        print(
            f"{target}: "
            f"global_stable={global_result['stable_positive_skill']} "
            f"robust={counts.get('ROBUST_OFFLINE_CANDIDATE', 0)} "
            f"promising={counts.get('PROMISING_OFFLINE', 0)} "
            f"mixed={counts.get('MIXED_OFFLINE_EVIDENCE', 0)} "
            f"insufficient={counts.get('INSUFFICIENT_OFFLINE_SAMPLE', 0)}"
        )

        robust = [
            row
            for row in result["league_evidence"]
            if row["state"] == "ROBUST_OFFLINE_CANDIDATE"
        ]
        robust.sort(
            key=lambda row: (
                -(row["aggregate_log_loss_skill_vs_prior"] or 0),
                -row["total_oos_n"],
            )
        )

        for row in robust[:12]:
            print(
                f"  ROBUST {row['league_id']} "
                f"{row['competition']}: "
                f"n={row['total_oos_n']} "
                f"skill="
                f"{row['aggregate_log_loss_skill_vs_prior'] * 100:.2f}% "
                f"folds={row['positive_skill_folds']}/"
                f"{row['evaluable_folds']}"
            )

    print("automatic_promotion: False")
    print("prospective_model_policy_credit: False")
    print(f"report: {args.report.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
