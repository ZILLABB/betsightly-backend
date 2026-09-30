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
from leagues.football_first_coverage import historical_coverage_report
from services.apifootball_service import TARGET_LEAGUE_IDS

DEFAULT_LEGACY = ROOT / "data" / "api-football" / "matches.csv"
DEFAULT_HISTORY = ROOT / "data" / "football_history" / "openfootball_matches.csv"
DEFAULT_REPORT = ROOT / "audit" / "phase8_historical_coverage.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy", type=Path, default=DEFAULT_LEGACY)
    parser.add_argument("--football-history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    legacy = pd.read_csv(args.legacy, low_memory=False)
    history = pd.read_csv(args.football_history, low_memory=False)
    combined, combine_stats = combine_results(legacy, history)
    features, feature_stats = build_feature_frame(combined)
    report = historical_coverage_report(
        combined,
        features,
        target_league_ids=set(TARGET_LEAGUE_IDS),
    )
    report["combined_results"] = combine_stats
    report["feature_build"] = feature_stats

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    overview = report["overview"]
    print("PHASE 8A.1 HISTORICAL COVERAGE")
    print(f"results: {overview['unique_results']:,}")
    print(f"trainable: {overview['trainable_samples']:,}")
    print(f"leagues: {overview['league_count']}")
    print(f"dates: {overview['min_date']} -> {overview['max_date']}")
    print(f"target_missing: {report['target_leagues_missing']}")
    print(f"thin_or_very_thin: {report['thin_or_very_thin']}")
    print("\nLOWEST TRAINABLE COVERAGE")
    for row in sorted(
        report["leagues"],
        key=lambda value: (value["trainable"], value["league_id"]),
    )[:12]:
        print(
            f"{row['league_id']:>4} {row['competition']}: "
            f"results={row['results']:,} "
            f"trainable={row['trainable']:,} "
            f"tier={row['coverage_tier']} "
            f"{row['min_date']}..{row['max_date']}"
        )
    print(f"\nreport: {args.report.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
