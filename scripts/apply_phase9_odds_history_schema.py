"""Install or inspect only the Phase 9 odds-history schema.

This script deliberately does not invoke Alembic and never reads or writes
alembic_version. It is for legacy databases whose physical runtime schema is
ahead of their Alembic bookkeeping.
"""
from __future__ import annotations

import argparse
import json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    if args.apply and args.confirm != "APPLY_PHASE9_ODDS_SCHEMA":
        parser.error("--apply requires --confirm APPLY_PHASE9_ODDS_SCHEMA")
    from leagues.odds_history import ensure_odds_history_schema, odds_history_schema_status
    payload = (ensure_odds_history_schema() if args.apply
               else {**odds_history_schema_status(), "changes_applied": []})
    print(json.dumps(payload, sort_keys=True, default=str))
    return 0 if payload["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
