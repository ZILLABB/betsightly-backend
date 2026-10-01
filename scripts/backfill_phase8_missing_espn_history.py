"""Backfill missing Phase-8 target leagues from ESPN month by month.

Successful months are retained. Unsupported/unavailable months are reported
explicitly and never treated as complete coverage.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from leagues.competition_registry import competition_for
from leagues.espn_history_fetch import HistoryMonthUnavailable
from leagues.history_months import finished_matches

MISSING_TARGETS = {
    265: "chi.1",
    292: "kor.1",
    307: "sau.1",
}

DEFAULT_OUTPUT = (
    ROOT / "data" / "football_history" / "espn_missing_target_matches.csv"
)
DEFAULT_REPORT = (
    ROOT / "audit" / "phase8_missing_target_backfill.json"
)

COLUMNS = [
    "date",
    "league_id",
    "league_name",
    "competition",
    "home_team",
    "away_team",
    "home_score",
    "away_score",
    "source_dataset",
    "source_class",
    "provider",
    "provider_event_id",
]


def _month_windows(start: date, end: date):
    current = start.replace(day=1)
    while current <= end:
        next_month = (
            current.replace(day=28)
            + timedelta(days=4)
        ).replace(day=1)
        month_start = max(start, current)
        month_end = min(
            end,
            next_month - timedelta(days=1),
        )
        yield (
            current.strftime("%Y%m"),
            month_start,
            month_end,
        )
        current = next_month


def fetch_rows(
    league_ids: list[int],
    start: str,
    end: str,
) -> tuple[list[dict], dict]:
    start_date = datetime.strptime(
        start,
        "%Y-%m-%d",
    ).date()
    end_date = datetime.strptime(
        end,
        "%Y-%m-%d",
    ).date()

    rows = []
    seen = set()
    league_reports = []

    for league_id in league_ids:
        slug = MISSING_TARGETS[int(league_id)]
        meta = competition_for(slug)
        if meta is None:
            raise RuntimeError(
                f"competition registry missing {slug}"
            )

        successful_months = []
        unavailable_months = []

        for month_key, month_start, month_end in _month_windows(
            start_date,
            end_date,
        ):
            try:
                matches = finished_matches(
                    slug,
                    month_start.strftime("%Y%m%d"),
                    month_end.strftime("%Y%m%d"),
                )
            except HistoryMonthUnavailable as exc:
                unavailable_months.append({
                    "month": month_key,
                    "error": str(exc),
                })
                continue

            successful_months.append(month_key)

            for match in matches:
                event_id = str(
                    match.get("id")
                    or ""
                )
                key = (
                    slug,
                    event_id,
                )
                if (
                    not event_id
                    or key in seen
                ):
                    continue

                seen.add(key)
                rows.append({
                    "date": str(
                        match.get("date")
                        or ""
                    )[:10],
                    "league_id": int(
                        league_id
                    ),
                    "league_name": meta.display_name,
                    "competition": meta.display_name,
                    "home_team": (
                        match.get("home")
                        or ""
                    ),
                    "away_team": (
                        match.get("away")
                        or ""
                    ),
                    "home_score": int(
                        match.get("hs")
                        or 0
                    ),
                    "away_score": int(
                        match.get("as")
                        or 0
                    ),
                    "source_dataset": (
                        "espn_runtime_history"
                    ),
                    "source_class": (
                        "RESULTS_ONLY_ESPN"
                    ),
                    "provider": "ESPN",
                    "provider_event_id": event_id,
                })

        league_rows = [
            row
            for row in rows
            if row["league_id"] == league_id
        ]

        league_reports.append({
            "league_id": league_id,
            "league_slug": slug,
            "competition": meta.display_name,
            "rows": len(league_rows),
            "successful_months": len(
                successful_months
            ),
            "unavailable_months": unavailable_months,
            "unavailable_month_count": len(
                unavailable_months
            ),
            "complete": (
                len(unavailable_months) == 0
            ),
        })

    rows.sort(
        key=lambda row: (
            row["date"],
            row["league_id"],
            row["home_team"],
            row["away_team"],
        )
    )

    report = {
        "schema": 1,
        "experiment": (
            "phase8_missing_target_espn_backfill_v2"
        ),
        "window": {
            "start": start,
            "end": end,
        },
        "league_ids": league_ids,
        "rows": len(rows),
        "complete": all(
            item["complete"]
            for item in league_reports
        ),
        "leagues": league_reports,
    }
    return rows, report


def write_rows(
    path: Path,
    rows: list[dict],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=COLUMNS,
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--start",
        default="2019-01-01",
    )
    parser.add_argument(
        "--end",
        default="2026-06-01",
    )
    parser.add_argument(
        "--league-id",
        type=int,
        action="append",
        choices=sorted(MISSING_TARGETS),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
    )
    args = parser.parse_args()

    ids = (
        args.league_id
        or sorted(MISSING_TARGETS)
    )

    rows, report = fetch_rows(
        ids,
        args.start,
        args.end,
    )
    write_rows(
        args.output,
        rows,
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
        "PHASE 8A.2 ESPN "
        "MISSING-LEAGUE BACKFILL"
    )
    print(
        f"window: "
        f"{args.start} -> {args.end}"
    )
    print(
        f"rows: {len(rows):,}"
    )
    print(
        f"complete: "
        f"{report['complete']}"
    )

    for item in report["leagues"]:
        print(
            f"{item['league_id']} "
            f"{item['league_slug']}: "
            f"{item['rows']:,} results, "
            f"unavailable_months="
            f"{item['unavailable_month_count']}"
        )
        for gap in item[
            "unavailable_months"
        ][:10]:
            print(
                f"  gap "
                f"{gap['month']}: "
                f"{gap['error']}"
            )

    print(
        f"output: "
        f"{args.output.resolve()}"
    )
    print(
        f"report: "
        f"{args.report.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
