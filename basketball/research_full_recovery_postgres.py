"""Fail-closed V2 recovery into a separate *empty* disposable PostgreSQL DB.

Never repairs or overwrites the active source. Pre-verifies full archive,
markets and audit receipt hashes before connecting to a destination.
The complete write/readback is enclosed in a destination-only transaction.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from basketball.research_coldstart import _json
from basketball.research_full_recovery import verify_full_recovery, _row_for_backup
from basketball.research_safe_migrate import isolated_target_is_safe
from basketball.research_private_store import import_bundle, latest_bundle
from basketball.research_market_store import NBAMarketObservation
from basketball.research_ops_health import NBAPrivateJobRun


def _timestamp(value):
    instant = datetime.fromisoformat(value.replace("Z","+00:00"))
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("NBA_V2_RESTORE_TIMESTAMP_INVALID")
    return instant.astimezone(timezone.utc).replace(tzinfo=None)


def restore_full_v2_empty_postgres(envelope, target_url, *,
                                   active_primary_url, original_render_url,
                                   engine_factory=create_engine):
    # All checks happen before opening a connection or creating any table.
    verify_full_recovery(envelope)
    # Both source identities must be supplied explicitly; missing source
    # could make a production host appear disposable.
    if not active_primary_url or not original_render_url:
        raise ValueError("NBA_V2_RESTORE_SOURCE_IDENTITY_REQUIRED")
    target = isolated_target_is_safe(target_url, active_primary_url)
    isolated_target_is_safe(target_url, original_render_url)
    # Stronger than distinct credentials: a target on the same Postgres host
    # could affect production even when the database name differs.
    from sqlalchemy.engine import make_url
    if (make_url(str(target)).host in (
            make_url(active_primary_url).host,
            make_url(original_render_url).host)):
        raise ValueError("NBA_V2_RESTORE_TARGET_HOST_NOT_DISPOSABLE")
    source = envelope["portable_backup_v1"]
    jobs = envelope["job_receipts"]
    engine = engine_factory(target, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("SET LOCAL search_path TO nba_research")
            if str(conn.exec_driver_sql("SELECT current_schema()").scalar() or "") != "nba_research":
                raise ValueError("NBA_V2_RESTORE_PRIVATE_SCHEMA_REQUIRED")
            if inspect(conn).get_table_names(schema="nba_research"):
                raise ValueError("NBA_V2_RESTORE_TARGET_NOT_EMPTY")
            session = sessionmaker(bind=conn)()
            try:
                result = import_bundle(source["archive"], db=session)
                if result["digest"] != source["archive_digest"]:
                    raise ValueError("NBA_V2_RESTORE_ARCHIVE_HASH_MISMATCH")
                NBAMarketObservation.__table__.create(bind=conn, checkfirst=True)
                NBAPrivateJobRun.__table__.create(bind=conn, checkfirst=True)
                for item in source["market_receipts"]:
                    session.add(NBAMarketObservation(
                        digest=item["digest"], payload_json=_json(item),
                        recorded_at=_timestamp(item["observed_at"]),
                    ))
                for row in jobs:
                    session.add(NBAPrivateJobRun(
                        id=row["id"], kind=row["kind"], status=row["status"],
                        summary_json=row["summary_json"],
                        recorded_at=_timestamp(row["recorded_at"]),
                    ))
                session.flush()
                saved = latest_bundle(session)
                if saved != source["archive"]:
                    raise ValueError("NBA_V2_RESTORE_ARCHIVE_READBACK_MISMATCH")
                markets = session.query(NBAMarketObservation).order_by(
                    NBAMarketObservation.id.asc()).all()
                if (len(markets) != source["market_receipt_count"] or
                    [(item.digest, json.loads(item.payload_json)) for item in markets]
                     != [(item["digest"], item) for item in source["market_receipts"]]):
                    raise ValueError("NBA_V2_RESTORE_MARKETS_READBACK_MISMATCH")
                saved_jobs = [
                    _row_for_backup(row) for row in
                    session.query(NBAPrivateJobRun).order_by(
                        NBAPrivateJobRun.id.asc()).all()
                ]
                if saved_jobs != jobs:
                    raise ValueError("NBA_V2_RESTORE_AUDIT_READBACK_MISMATCH")
                if jobs:
                    conn.exec_driver_sql(
                        "SELECT setval(pg_get_serial_sequence('nba_private_job_runs',"
                        "'id'), (SELECT max(id) FROM nba_private_job_runs), true)"
                    )
            finally:
                session.close()
        return {
            "status": "disposable_full_postgres_restore_verified",
            "archive_digest": source["archive_digest"],
            "market_receipt_count": source["market_receipt_count"],
            "job_receipt_count": len(jobs),
            "source_unchanged": True, "research_only": True,
            "not_bookable": True, "production_switch_performed": False,
        }
    finally:
        engine.dispose()
