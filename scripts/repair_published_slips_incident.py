"""One-off, guarded repair for published_slips dated 2026-09-15..24.

Default execution is read-only.  This script intentionally has no generic
date flags: its date scope is the authorised September incident only.
"""

import argparse
import json
import sys

from leagues.published_slip_repair import (
    CONFIRM_TOKEN,
    RepairPreconditionError,
    run_repair,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="apply the fixed-scope repair after validation")
    parser.add_argument("--confirm", default="",
                        help=f"required token: {CONFIRM_TOKEN}")
    parser.add_argument("--backup-dir", default="maintenance_backups",
                        help="directory for the pre-repair JSON backup")
    parser.add_argument("--verify", action="store_true",
                        help="fail unless a fresh read-only report has no remaining repairs")
    args = parser.parse_args()
    if args.apply and args.verify:
        parser.error("--apply and --verify cannot be used together")
    try:
        result = run_repair(apply=args.apply, confirmation=args.confirm,
                            backup_dir=args.backup_dir)
    except RepairPreconditionError as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}, indent=2))
        return 2
    if args.verify:
        remaining = result["rows_to_change"]
        result["verification_clean"] = remaining == 0
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0 if remaining == 0 else 3
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
