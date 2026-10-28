"""Read-only source/restore exact-row-count acceptance check.

Set SOURCE_DATABASE_URL and RESTORE_DATABASE_URL on an owner-controlled
private host (NOT in CI with production secrets). No data rows are exported.
The source must be fenced or compared against an exact dump snapshot or
post-backup writes will cause legitimate count divergence.
"""

from __future__ import annotations

import json
import os
import sys

from utils.vps_backup import pg_environment
from utils.vps_parity import compare_inventory
from utils.vps_restore import validate_restore_name


def inspect_public_tables(url: str) -> dict[str, int]:
    from sqlalchemy import create_engine, text

    engine = create_engine(
        url,
        isolation_level="REPEATABLE READ",
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )
    try:
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            tables = conn.execute(text(
                "SELECT tablename FROM pg_catalog.pg_tables "
                "WHERE schemaname = 'public' ORDER BY tablename"
            )).scalars().all()
            if not tables or len(tables) > 500:
                raise RuntimeError("unexpected PostgreSQL public table inventory")
            result = {}
            for table in tables:
                # Identifier quoting cannot be replaced by bind params.
                quoted = '"' + table.replace('"', '""') + '"'
                result[table] = int(conn.execute(text(
                    f'SELECT count(*) FROM "public".{quoted}'
                )).scalar_one())
            return result
    finally:
        engine.dispose()


def main() -> int:
    try:
        source = os.environ["SOURCE_DATABASE_URL"]
        restored = os.environ["RESTORE_DATABASE_URL"]
        _, source_db = pg_environment(source)
        _, restored_db = pg_environment(restored)
        validate_restore_name(restored_db, source_db)
        report = compare_inventory(
            inspect_public_tables(source),
            inspect_public_tables(restored),
        )
    except Exception as exc:
        # Avoid exposing URL, passwords and server error messages.
        report = {"healthy": False, "error": f"PARITY_CHECK_ERROR:{type(exc).__name__}"}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["healthy"] else 2


if __name__ == "__main__":
    sys.exit(main())
