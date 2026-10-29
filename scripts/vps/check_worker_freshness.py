"""Read-only check of VPS worker ownership (exit 0 healthy / 2 unhealthy).

Requires DATABASE_URL and the application's SQLAlchemy/psycopg2 dependencies.
Execute from outside the worker containers (a separate observer job), not as
the worker's own heartbeat, so it can detect an unresponsive worker.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from utils.worker_freshness import evaluate_worker_freshness


def fetch_heartbeats(database_url):
    from sqlalchemy import create_engine, inspect, text

    if not database_url.startswith(
        ("postgresql://", "postgresql+psycopg2://")
    ):
        raise ValueError("monitor requires PostgreSQL DATABASE_URL")
    db = create_engine(database_url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    try:
        if not inspect(db).has_table("runtime_process_heartbeats"):
            raise RuntimeError("runtime_process_heartbeats table is missing")
        with db.connect() as conn:
            return [dict(row) for row in conn.execute(text(
                "SELECT role, state, heartbeat_at, ownership_json "
                "FROM runtime_process_heartbeats"
            )).mappings()]
    finally:
        db.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stale-seconds", type=int, default=120)
    parser.add_argument("--require-telegram", action="store_true")
    args = parser.parse_args()
    try:
        url = os.environ["DATABASE_URL"]
        report = evaluate_worker_freshness(
            fetch_heartbeats(url),
            stale_seconds=args.stale_seconds,
            require_telegram=args.require_telegram,
        )
    except Exception as exc:
        # Avoid leaking URLs, passwords or SQL diagnostics into alerts.
        report = {"healthy": False, "problems": [f"monitor_error:{type(exc).__name__}"]}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["healthy"] else 2


if __name__ == "__main__":
    sys.exit(main())
