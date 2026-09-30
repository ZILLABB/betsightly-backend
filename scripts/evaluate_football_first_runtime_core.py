
"""Evaluate the runtime-compatible football-first feature subset."""
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
from leagues.football_first_runtime_core import (
    evaluate_runtime_core_walk_forward,
)

DEFAULT_LEGACY = ROOT / "data" / "api-football" / "matches.csv"
DEFAULT_HISTORY = (
    ROOT / "data" / "football_history" / "openfootball_matches.csv"
)
DEFAULT_REPORT = (
    ROOT / "audit" / "football_first_runtime_core.json"
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

    legacy = pd.read_csv(
        args.legacy,
        low_memory=False,
    )
    history = pd.read_csv(
        args.football_history,
        low_memory=False,
    )
    combined, _ = combine_results(
        legacy,
        history,
    )
    features, feature_stats = (
        build_feature_frame(
            combined
        )
    )
    report = (
        evaluate_runtime_core_walk_forward(
            features,
            n_folds=args.folds,
        )
    )
    report["feature_build"] = (
        feature_stats
    )

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
        "FOOTBALL-FIRST RUNTIME CORE"
    )
    print(
        f"features: "
        f"{report['feature_count']} "
        f"({report['feature_version']})"
    )
    print(
        "market_price_features_used: []"
    )

    for target, result in report[
        "targets"
    ].items():
        print(
            f"{target}: "
            f"folds={result['fold_count']} "
            f"positive={result['positive_skill_folds']} "
            f"median_skill="
            f"{(result['median_log_loss_skill_vs_prior'] or 0) * 100:.2f}% "
            f"min_skill="
            f"{(result['minimum_log_loss_skill_vs_prior'] or 0) * 100:.2f}% "
            f"stable={result['stable_positive_skill']} "
            f"families={result['family_selection_counts']}"
        )

    print(
        "runtime_shadow_ready: "
        f"{report['runtime_shadow_ready']}"
    )
    print(
        "automatic_promotion: False"
    )
    print(
        "prospective_observation_started: False"
    )
    print(
        f"report: {args.report.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
