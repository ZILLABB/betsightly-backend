"""Explicit staging-only lifecycle for independent market shadow evidence.

Capture happens on a fresh prepared board before kickoff, without re-running
the prediction pipeline. Set an additional one-operation confirmation for DB
writes. No official slip, booking code, model promotion or customer notification.

  python -m scripts.staging_multimarket_shadow report
  python -m scripts.staging_multimarket_shadow capture
  python -m scripts.staging_multimarket_shadow refresh-capture
  python -m scripts.staging_multimarket_shadow settle
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from scripts.prepare_staging_board_once import preflight


def execute(command: str) -> dict:
    db_name = preflight()
    from database import engine
    from leagues import market_shadow_observations as shadow

    if command == "report":
        result = shadow.evidence_report(db_engine=engine)
    elif command in {"capture", "refresh-capture"}:
        refresh = None
        if command == "refresh-capture":
            # Confirm BOTH the database identity and separate shadow-write
            # authorization before initiating expensive external provider work.
            # This operation is explicit, never invoked by a request/scheduler.
            shadow.staging_write_gate(db_engine=engine)
            from scripts.prepare_staging_board_once import prepare_once
            refresh = prepare_once()
        from leagues.engine import prepared_board
        picks, fixtures, board = prepared_board(days_ahead=7)
        if not board.get("ready") or board.get("stale"):
            raise RuntimeError(
                "Refusing capture from missing/stale staging snapshot. "
                "Use the explicit refresh-capture operation for one "
                "guarded refresh immediately followed by shadow capture."
            )
        if not board.get("board_snapshot_id") or not fixtures:
            raise RuntimeError("Capture requires persisted provenance and fixtures")
        if refresh and board["board_snapshot_id"] != refresh["board_snapshot_id"]:
            raise RuntimeError("Prepared snapshot changed during refresh; refusing capture")
        result = shadow.collect(
            picks, board["board_snapshot_id"],
            db_engine=engine, observed_at=datetime.now(timezone.utc),
        )
        if refresh is not None:
            result["refresh"] = {
                "snapshot_id": refresh["board_snapshot_id"],
                "fixture_count": refresh["fixture_count"],
                "candidate_count": refresh["candidate_count"],
                "complete": refresh["complete"],
            }
    elif command == "settle":
        result = shadow.settle(db_engine=engine)
    else:
        raise ValueError("Use capture, refresh-capture, settle or report")
    return {
        "database": db_name, "operation": command,
        "production_unchanged": True,
        "official_record_unchanged": True,
        "output": result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("report", "capture", "refresh-capture", "settle")
    )
    args = parser.parse_args()
    print(json.dumps(execute(args.command), sort_keys=True))


if __name__ == "__main__":
    main()
