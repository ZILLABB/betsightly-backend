"""External read-only daily job-success gate.

Requires DATABASE_URL and PostgreSQL. Can run from monitoring host via
timer, exit 0 healthy, 2 unhealthy. Never creates a DB table or triggers work.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from utils.vps_daily_freshness import WAT, check_daily_publication


def fetch_daily_run(url, date):
    if not url.startswith(("postgresql://", "postgresql+psycopg2://")):
        raise ValueError("PostgreSQL required")
    from sqlalchemy import create_engine, inspect, text
    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    try:
        if not inspect(engine).has_table("daily_runs"):
            return None
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT run_date, status, report FROM daily_runs "
                "WHERE run_date = :date LIMIT 1"
            ), {"date": date}).mappings().first()
            return dict(result) if result else None
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--grace-minutes", type=int, default=90)
    args = parser.parse_args()
    try:
        now = datetime.now(timezone.utc)
        today = now.astimezone(WAT).date().isoformat()
        row = fetch_daily_run(os.environ["DATABASE_URL"], today)
        result = check_daily_publication(row, now=now, grace_minutes=args.grace_minutes)
    except Exception as exc:
        result = {"healthy": False, "status": "monitor_error",
                  "problems": [f"monitor_error:{type(exc).__name__}"]}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["healthy"] else 2


if __name__ == "__main__":
    sys.exit(main())
