from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from leagues.football_first_challenger import build_feature_frame, combine_results
from leagues.football_first_runtime_elo import (
    attach_historical_runtime_elo,
    evaluate_runtime_elo_comparison,
)

DEFAULT_LEGACY = ROOT / "data" / "api-football" / "matches.csv"
DEFAULT_HISTORY = ROOT / "data" / "football_history" / "openfootball_matches.csv"
DEFAULT_REPORT = ROOT / "audit" / "football_first_runtime_elo.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy", type=Path, default=DEFAULT_LEGACY)
    parser.add_argument("--football-history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    legacy = pd.read_csv(args.legacy, low_memory=False)
    history = pd.read_csv(args.football_history, low_memory=False)
    combined, combine_stats = combine_results(legacy, history)
    features, feature_stats = build_feature_frame(combined)
    expanded, elo_stats = attach_historical_runtime_elo(combined, features)
    report = evaluate_runtime_elo_comparison(expanded, n_folds=args.folds)
    report["combined_results"] = combine_stats
    report["feature_build"] = feature_stats
    report["runtime_elo_build"] = elo_stats

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print("PHASE 8B.1 RUNTIME ELO")
    print("runtime artifact ready: False")
    print(
        f"elo availability: {elo_stats['available']:,}/"
        f"{elo_stats['samples']:,} "
        f"({elo_stats['availability_rate'] * 100:.2f}%)"
    )
    print("provider identity parity: False")
    for target, result in report["targets"].items():
        base = result["runtime_core_v1"]
        elo = result["runtime_core_plus_elo"]
        print(
            f"{target}: "
            f"base={((base['median_skill'] or 0) * 100):.2f}% "
            f"+elo={((elo['median_skill'] or 0) * 100):.2f}% "
            f"delta={((result['median_skill_delta'] or 0) * 100):+.2f}pp "
            f"elo_positive={elo['positive_skill_folds']}/{elo['fold_count']}"
        )
    print("automatic_promotion: False")
    print(f"report: {args.report.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
