"""Re-run Phase 8A coverage with the verified ESPN supplemental backfill."""
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
DEFAULT_HISTORY = (
    ROOT / "data" / "football_history" / "openfootball_matches.csv"
)
DEFAULT_SUPPLEMENTAL = (
    ROOT / "data" / "football_history" / "espn_missing_target_matches.csv"
)
DEFAULT_REPORT = (
    ROOT / "audit" / "phase8_historical_coverage_supplemented.json"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy", type=Path, default=DEFAULT_LEGACY)
    parser.add_argument("--football-history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--supplemental-espn", type=Path, default=DEFAULT_SUPPLEMENTAL)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    if not args.supplemental_espn.exists():
        raise SystemExit(
            f"Supplemental ESPN history not found: {args.supplemental_espn}"
        )

    legacy = pd.read_csv(args.legacy, low_memory=False)
    history = pd.read_csv(args.football_history, low_memory=False)
    supplemental = pd.read_csv(args.supplemental_espn, low_memory=False)

    # combine_results accepts the standard result columns. Concatenating here
    # keeps the original baseline files untouched and lets duplicate/conflict
    # guards run over the enlarged result corpus.
    combined_history = pd.concat(
        [history, supplemental],
        ignore_index=True,
        sort=False,
    )
    combined, combine_stats = combine_results(legacy, combined_history)
    features, feature_stats = build_feature_frame(combined)
    report = historical_coverage_report(
        combined,
        features,
        target_league_ids=set(TARGET_LEAGUE_IDS),
    )
    report["combined_results"] = combine_stats
    report["feature_build"] = feature_stats
    report["supplemental_espn"] = {
        "path": str(args.supplemental_espn.resolve()),
        "rows": len(supplemental),
        "league_ids": sorted(
            int(value)
            for value in supplemental["league_id"].dropna().unique().tolist()
        ),
    }

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print("PHASE 8A.2 SUPPLEMENTED HISTORICAL COVERAGE")
    print(f"results: {report['overview']['unique_results']:,}")
    print(f"trainable: {report['overview']['trainable_samples']:,}")
    print(f"leagues: {report['overview']['league_count']}")
    print(f"target_missing: {report['target_leagues_missing']}")
    for league_id in (265, 292, 307):
        row = next(
            (
                item for item in report["leagues"]
                if item["league_id"] == league_id
            ),
            None,
        )
        if row is None:
            print(f"{league_id}: STILL_MISSING")
        else:
            print(
                f"{league_id} {row['competition']}: "
                f"results={row['results']:,} "
                f"trainable={row['trainable']:,} "
                f"tier={row['coverage_tier']}"
            )
    print(f"report: {args.report.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
