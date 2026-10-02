"""Bounded archive-only CLV entry backfill; defaults to a read-only plan.

Example: python -m scripts.backfill_odds_entry_prices --start 2026-10-01 --end 2026-10-08
"""
import argparse
import json
from datetime import datetime, timezone


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="Inclusive UTC date")
    parser.add_argument("--end", required=True, help="Exclusive UTC date")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    if args.apply and args.confirm != "BACKFILL_ARCHIVE_ENTRY_PRICES":
        parser.error("--apply requires --confirm BACKFILL_ARCHIVE_ENTRY_PRICES")
    from leagues.odds_history import backfill_archive_entries
    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    print(json.dumps(backfill_archive_entries(start, end,
            dry_run=not args.apply), sort_keys=True))


if __name__ == "__main__":
    main()
