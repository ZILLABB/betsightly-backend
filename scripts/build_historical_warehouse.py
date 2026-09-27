"""Build a provenance-first normalized historical warehouse.

By default this writes under data/historical/, which is separate from the
legacy runtime CSV and is excluded from the production Docker image.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from leagues.historical_warehouse import (
    build_manifest,
    build_rows,
    write_warehouse,
)

DEFAULT_INPUT = ROOT / "data" / "api-football" / "matches.csv"
DEFAULT_OUTPUT = ROOT / "data" / "historical" / "normalized" / "matches.csv"
DEFAULT_QUARANTINE = (
    ROOT / "data" / "historical" / "normalized" / "quarantine.csv"
)
DEFAULT_MANIFEST = (
    ROOT / "data" / "historical" / "normalized" / "manifest.json"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--quarantine", type=Path, default=DEFAULT_QUARANTINE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Audit/normalize in memory without writing warehouse files.",
    )
    args = parser.parse_args()

    input_path = args.input.resolve()
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    frame = pd.read_csv(input_path, low_memory=False)
    rows, quarantine, stats = build_rows(frame, input_path=input_path)
    manifest = build_manifest(
        rows,
        quarantine,
        stats,
        input_path=input_path,
    )

    print("HISTORICAL WAREHOUSE BUILD")
    print(f"input rows: {stats.input_rows:,}")
    print(f"normalized rows: {stats.normalized_rows:,}")
    print(f"output rows: {stats.output_rows:,}")
    print(f"rejected rows: {stats.rejected_rows:,}")
    print(
        f"duplicates: {stats.duplicate_keys} keys / "
        f"{stats.duplicate_rows} rows"
    )
    print(
        f"conflicts: {stats.conflicting_keys} keys / "
        f"{stats.quarantined_rows} quarantined rows"
    )
    print(
        "provenance: "
        f"exact={stats.exact_provenance_rows:,} "
        f"inferred={stats.inferred_provenance_rows:,}"
    )
    print(
        "odds coverage: "
        f"1X2={manifest['odds_coverage']['complete_1x2_pct']:.2f}% "
        f"OU2.5={manifest['odds_coverage']['complete_ou25_pct']:.2f}%"
    )

    if args.report_only:
        print("report-only: no warehouse files written")
        return 0

    write_warehouse(
        rows,
        quarantine,
        manifest,
        output_csv=args.output.resolve(),
        quarantine_csv=args.quarantine.resolve(),
        manifest_json=args.manifest.resolve(),
    )
    print(f"output: {args.output.resolve()}")
    print(f"manifest: {args.manifest.resolve()}")
    if quarantine:
        print(f"quarantine: {args.quarantine.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
