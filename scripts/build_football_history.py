\
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from leagues.openfootball_history import build_dataset

DEFAULT_DIR = ROOT / "data" / "football_history"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the isolated OpenFootball results-only history dataset."
    )
    parser.add_argument("--min-year", type=int, default=2012)
    parser.add_argument("--max-year", type=int, default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_DIR / "openfootball_matches.csv",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_DIR / "manifest.json",
    )
    args = parser.parse_args()

    manifest = build_dataset(
        output_csv=args.output.resolve(),
        manifest_json=args.manifest.resolve(),
        min_year=args.min_year,
        max_year=args.max_year,
    )

    print("FOOTBALL HISTORY INGESTION")
    print(f"provider: {manifest['provider']}")
    print(f"source_files: {manifest['source_file_count']}")
    print(
        "rows: "
        f"{manifest['deduplication']['unique_matches']:,} unique "
        f"({manifest['deduplication']['exact_duplicates_removed']:,} duplicates removed)"
    )
    print("coverage:")
    for item in manifest["coverage"]:
        print(
            f"  {item['league_id']} {item['competition']}: "
            f"{item['rows']:,} rows {item['min_date']}..{item['max_date']}"
        )
    print(f"csv: {args.output.resolve()}")
    print(f"manifest: {args.manifest.resolve()}")
    print("market_training_eligible: False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
