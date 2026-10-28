"""Restore exact four-table basketball rights/history into an EMPTY Postgres.

Only for a separately provisioned disposable disaster-recovery destination.
Never points at active Supabase/Render; no promotion or production failback.
"""
from __future__ import annotations
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from basketball.research_licensed_backup import (
    SCOPES, TIME_FIELDS, _time, verify_history_recovery,
)
from basketball.research_safe_migrate import isolated_target_is_safe

_SCHEMA_SQL = Path(__file__).resolve().parents[1] / (
    "sql/nba_private_licensed_history_20261028.sql"
)
_PROBE_SQL = Path(__file__).resolve().parents[1] / (
    "sql/nba_private_six_league_source_probes_20261028.sql"
)
_SOURCE_SQL = Path(__file__).resolve().parents[1] / (
    "sql/nba_private_licensed_backup_receipts_20261028.sql"
)

def restore_licensed_history_empty_postgres(
        envelope, target_url, *, active_primary_url, original_render_url,
        engine_factory=create_engine):
    """Check source identities and empty DB before mutating any target data."""
    verified=verify_history_recovery(envelope)
    if not active_primary_url or not original_render_url:
        raise ValueError("BASKETBALL_HISTORY_RESTORE_SOURCE_IDENTITIES_REQUIRED")
    safe=isolated_target_is_safe(target_url,active_primary_url)
    isolated_target_is_safe(target_url,original_render_url)
    if make_url(str(safe)).host in (
        make_url(active_primary_url).host,
        make_url(original_render_url).host
    ):
        raise ValueError("BASKETBALL_HISTORY_RESTORE_SAME_HOST_BLOCKED")
    engine=engine_factory(safe,pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            schema=conn.execute(text("""
                SELECT 1 FROM pg_namespace WHERE nspname='nba_research'
            """)).scalar()
            if not schema:
                raise ValueError("BASKETBALL_HISTORY_RESTORE_SCHEMA_REQUIRED")
            if inspect(conn).get_table_names(schema="nba_research"):
                raise ValueError("BASKETBALL_HISTORY_RESTORE_TARGET_NOT_EMPTY")
            for filepath in (_SCHEMA_SQL,_PROBE_SQL,_SOURCE_SQL):
                for statement in filepath.read_text(encoding="utf-8").split(";"):
                    if statement.strip():
                        conn.exec_driver_sql(statement)
            for key,(table,columns) in SCOPES.items():
                data=envelope["tables"][key]
                if not data:
                    continue
                sql=text(
                    "INSERT INTO nba_research." + table +
                    " (" + ",".join(columns) + ") OVERRIDING SYSTEM VALUE VALUES (" +
                    ",".join(":"+col for col in columns) + ")"
                )
                conn.execute(sql,data)
                conn.execute(text("""
                    SELECT setval(pg_get_serial_sequence(:relation,'id'),
                    :last_id,true)
                """),{
                    "relation":"nba_research."+table,
                    "last_id":data[-1]["id"]
                })
            for key,(table,columns) in SCOPES.items():
                actual=conn.execute(text(
                    "SELECT "+",".join(columns)+" FROM nba_research."+
                    table+" ORDER BY id"
                )).mappings().all()
                normalized=[{
                    col:(_time(row[col]) if col in TIME_FIELDS
                         and row[col] is not None else row[col])
                    for col in columns
                } for row in actual]
                if normalized!=envelope["tables"][key]:
                    raise ValueError(
                        "BASKETBALL_HISTORY_RESTORE_READBACK_MISMATCH"
                    )
        return {
            "status":"disposable_licensed_history_postgres_restore_verified",
            "counts":verified["counts"],
            "tables_sha256":envelope["tables_sha256"],
            "source_unchanged":True,"research_only":True,
            "not_bookable":True,"production_failback_performed":False,
        }
    finally:
        engine.dispose()
