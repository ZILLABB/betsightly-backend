# Evaluate walk-forward stability for the football-first challenger.

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
from leagues.football_first_stability import evaluate_walk_forward

DEFAULT_LEGACY = ROOT / "data" / "api-football" / "matches.csv"
DEFAULT_HISTORY = (
    ROOT / "data" / "football_history" / "openfootball_matches.csv"
)
DEFAULT_REPORT = (
    ROOT / "audit" / "football_first_walk_forward.json"
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
    report = evaluate_walk_forward(
        features,
        n_folds=args.folds,
    )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print("FOOTBALL-FIRST WALK-FORWARD")
    for target, result in report["targets"].items():
        if result.get("status") != "EVALUATED":
            print(f"{target}: {result.get('status')}")
            continue
        print(
            f"{target}: folds={result['fold_count']} "
            f"positive={result['positive_skill_folds']} "
            f"median_skill="
            f"{result['median_log_loss_skill_vs_prior'] * 100:.2f}% "
            f"min_skill="
            f"{result['minimum_log_loss_skill_vs_prior'] * 100:.2f}% "
            f"stable={result['stable_positive_skill']} "
            f"families={result['family_selection_counts']}"
        )
        strong = [
            row
            for row in result["league_segments_min_100"]
            if row["log_loss_skill_vs_prior"] > 0
        ]
        weak = [
            row
            for row in result["league_segments_min_100"]
            if row["log_loss_skill_vs_prior"] <= 0
        ]
        print(
            f"  league segments >=100: "
            f"positive={len(strong)} nonpositive={len(weak)}"
        )

    print("promotion_enabled: False")
    print(f"report: {args.report.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
