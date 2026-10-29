"""Restore a verified archive into an *existing, empty, disposable* database.

This command never creates or drops a database and never uses --clean.
It refuses unsafe target names, nonempty target schemas and mismatched
backup manifests. Run against isolated PostgreSQL, never production.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from utils.vps_backup import pg_environment
from utils.vps_restore import validate_archive, validate_restore_name


TABLE_COUNT_SQL = (
    "SELECT count(*) FROM pg_catalog.pg_class c "
    "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
    "WHERE c.relkind IN ('r', 'p', 'v', 'm', 'S') "
    "AND n.nspname NOT IN ('pg_catalog','information_schema') "
    "AND n.nspname NOT LIKE 'pg_toast%'"
)


def table_count(target_url):
    from sqlalchemy import create_engine, text
    engine = create_engine(
        target_url, pool_pre_ping=True, connect_args={"connect_timeout": 5}
    )
    try:
        with engine.connect() as conn:
            name = conn.execute(text("SELECT current_database()")).scalar_one()
            count = conn.execute(text(TABLE_COUNT_SQL)).scalar_one()
            return name, int(count)
    finally:
        engine.dispose()


def restore_drill(archive: Path, manifest: Path, target_url: str):
    pg_env, target_name = pg_environment(target_url)
    verified = validate_archive(archive, manifest, target_name)
    validate_restore_name(target_name, verified["source_database"])
    connected_name, before = table_count(target_url)
    if connected_name != target_name or before != 0:
        raise RuntimeError("target identity mismatch or target database is not empty")
    # No --clean, --create, --if-exists or source credentials in argv.
    subprocess.run(
        ["pg_restore", "--dbname", target_name, "--single-transaction",
         "--exit-on-error", "--no-owner", "--no-acl", str(archive)],
        check=True, capture_output=True, timeout=1200, env=pg_env,
    )
    connected_name, after = table_count(target_url)
    if connected_name != target_name or after <= 0:
        raise RuntimeError("restore finished but no user tables were detected")
    return {
        "status": "restored_to_disposable_database",
        "database": target_name,
        "relation_count": after,
        "source_archive": archive.name,
        "sha256": verified["sha256"],
        "note": "This verifies restore mechanics, not every source row or application invariant",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        target = os.environ["RESTORE_DATABASE_URL"]
        result = restore_drill(args.archive, args.manifest, target)
    except Exception as exc:
        print(f"RESTORE_DRILL_FAILED: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
