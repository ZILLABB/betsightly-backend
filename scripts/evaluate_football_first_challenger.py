# Evaluate the isolated football-first challenger.
# No production model files are written.

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
    evaluate,
)

DEFAULT_LEGACY = ROOT / "data" / "api-football" / "matches.csv"
DEFAULT_HISTORY = (
    ROOT / "data" / "football_history" / "openfootball_matches.csv"
)
DEFAULT_REPORT = ROOT / "audit" / "football_first_challenger.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy", type=Path, default=DEFAULT_LEGACY)
    parser.add_argument(
        "--football-history",
        type=Path,
        default=DEFAULT_HISTORY,
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--features-out",
        type=Path,
        default=None,
    )
    args = parser.parse_args()

    for path in (args.legacy, args.football_history):
        if not path.exists():
            raise SystemExit(f"Input not found: {path}")

    legacy = pd.read_csv(args.legacy, low_memory=False)
    history = pd.read_csv(args.football_history, low_memory=False)
    combined, combine_stats = combine_results(legacy, history)
    features, feature_stats = build_feature_frame(combined)
    report = evaluate(features)
    report["inputs"] = {
        "legacy_csv": str(args.legacy.resolve()),
        "football_history_csv": str(args.football_history.resolve()),
    }
    report["combined_results"] = combine_stats
    report["feature_build"] = feature_stats

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    if args.features_out is not None:
        args.features_out.parent.mkdir(parents=True, exist_ok=True)
        features.to_csv(args.features_out, index=False)

    print("FOOTBALL-FIRST CHALLENGER")
    print(
        f"combined: {combine_stats['unique_rows']:,} unique results"
    )
    print(
        f"trainable: {feature_stats['trainable_samples']:,} "
        "football-only samples"
    )
    split = report["split"]
    print(
        f"split: train={split['train']:,} "
        f"calib={split['calib']:,} "
        f"test={split['test']:,}"
    )
    print("market_price_features_used: []")

    for target, result in report["targets"].items():
        if result.get("status") != "EVALUATED":
            print(f"{target}: {result.get('status')}")
            continue
        test = result["test"]
        baseline = result["baseline_test"]
        print(
            f"{target}: {result['selected_family']} "
            f"logloss={test['log_loss']:.4f} "
            f"baseline={baseline['log_loss']:.4f} "
            f"skill={result['log_loss_skill_vs_train_prior'] * 100:.2f}% "
            f"brier={test['brier_multiclass']:.4f} "
            f"ece={test['top_label_ece']:.4f}"
        )

    print("promotion_enabled: False")
    print(f"report: {args.report.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
