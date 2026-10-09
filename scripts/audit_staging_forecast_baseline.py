"""Read-only daily coverage comparison using the existing staging snapshot."""
import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from scripts.prepare_staging_board_once import preflight

WAT = timezone(timedelta(hours=1))


def preview(target_day):
    database = preflight()
    from leagues import sportybet
    from leagues.bookmaker_consensus_baseline import full_day_baseline
    today = datetime.now(WAT).date()
    target = date.fromisoformat(target_day)
    if target < today or target > today + timedelta(days=6):
        raise ValueError("Target outside current seven-day WAT horizon")
    cached = sportybet._db_get("sportybet_board") or {}
    metadata = cached.get("metadata") or {}
    if not metadata.get("is_complete") or not cached.get("fixtures"):
        raise RuntimeError("Complete source snapshot unavailable")
    result = full_day_baseline(
        sportybet._snapshot(cached["fixtures"], metadata),
        date_wat=target_day,
    )
    return {
        **result,
        "database": database,
        "snapshot_id": metadata.get("snapshot_id"),
        "cached_at": cached.get("fetched_at"),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    result = preview(args.date)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        result = {
            "output": str(path),
            "count": result["count"],
            "statuses": result["statuses"],
        }
    print(json.dumps(result, sort_keys=True))
