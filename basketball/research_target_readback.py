"""Read-only post-restore reconciliation against the live NBA source.

This never alters either database or stores source archives in GitHub logs.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from basketball.research_coldstart import _json
from basketball.research_restore_drill import verify_portable_backup
from basketball.research_safe_migrate import isolated_target_is_safe


def compare_archive_and_markets(backup, latest_digest, latest_body, rows):
    """Pure exact comparison; refuse stale snapshots or missing market receipts."""
    verified = verify_portable_backup(backup)
    if verified.get("restore_drill_passed") is not True:
        raise ValueError("NBA_RECONCILE_SOURCE_DRILL_FAILED")
    if (latest_digest != backup["archive_digest"] or
        hashlib.sha256(_json(json.loads(latest_body)).encode("utf-8")).hexdigest()
            != latest_digest):
        raise ValueError("NBA_RECONCILE_ARCHIVE_DRIFT")
    original = backup["market_receipts"]
    if len(rows) != len(original):
        raise ValueError("NBA_RECONCILE_MARKET_COUNT_DIFFERS")
    for (digest, raw), expected in zip(rows, original):
        actual = json.loads(raw)
        if (digest != expected["digest"] or actual != expected or
            hashlib.sha256(_json({k: v for k, v in actual.items()
                                  if k != "digest"}).encode("utf-8")).hexdigest()
                != digest):
            raise ValueError("NBA_RECONCILE_MARKET_HISTORY_DIFFERS")
    return {
        "status": "source_target_identical",
        "archive_sha256": latest_digest,
        "market_receipt_count": len(rows),
        "source_unchanged": True,
        "research_only": True,
        "not_bookable": True,
        "cutover_approved": False,
    }


def export_original_render_source(source_url, *, engine_factory=create_engine,
                                  exporter=None):
    """Export explicitly from immutable original DATABASE_URL, never SessionLocal.

    SessionLocal may already point to the restored Supabase target after a
    stage-only cutover; using it would compare the target against itself.
    The Render source transaction is forced READ ONLY and rolled back.
    """
    if not source_url:
        raise ValueError("NBA_RECONCILE_ORIGINAL_SOURCE_URL_REQUIRED")
    url = make_url(source_url)
    if url.get_backend_name() != "postgresql" or not url.host or not url.database:
        raise ValueError("NBA_RECONCILE_ORIGINAL_SOURCE_MUST_BE_POSTGRES")
    if exporter is None:
        from basketball.research_ops_health import export_verified_backup
        exporter = export_verified_backup
    engine = engine_factory(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                with Session(bind=connection) as db:
                    return exporter(db=db)
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def compare_live_source_to_target(target_url, *, source_url=None,
                                  engine_factory=create_engine):
    """Compare original Render source against Supabase, NEVER target-to-self."""
    target = isolated_target_is_safe(target_url, source_url)
    backup = export_original_render_source(
        source_url, engine_factory=engine_factory
    )
    engine = engine_factory(target, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("SET LOCAL search_path TO nba_research")
            if conn.execute(text("SELECT current_schema()")).scalar() != "nba_research":
                raise ValueError("NBA_RECONCILE_PRIVATE_SCHEMA_REQUIRED")
            latest = conn.execute(text(
                "SELECT digest, bundle_json FROM nba_private_research_snapshots "
                "ORDER BY id DESC LIMIT 1"
            )).one_or_none()
            if latest is None:
                raise ValueError("NBA_RECONCILE_MISSING_TARGET_ARCHIVE")
            rows = conn.execute(text(
                "SELECT digest, payload_json FROM nba_private_market_observations "
                "ORDER BY id ASC"
            )).all()
            return compare_archive_and_markets(backup, latest[0], latest[1], rows)
    finally:
        engine.dispose()


def verified_audit_prefix(existing, source):
    """Only append if every existing ordered target row exactly matches source."""
    if len(existing) > len(source) or existing != source[:len(existing)]:
        raise ValueError("NBA_AUDIT_EXISTING_HISTORY_MISMATCH")
    return source[len(existing):]


def mirror_verified_job_history(target_url, *, source_url=None,
                                engine_factory=create_engine):
    """Mirror only sanitized existing NBA scheduler receipts; no football rows.

    Target must contain a byte-for-byte ordered prefix or be empty. On retry,
    append only new receipts. Preserve identifiers; fix Postgres sequence.
    """
    from basketball.research_ops_health import NBAPrivateJobRun, JOB_KINDS
    from database import SessionLocal

    source_db = SessionLocal()
    try:
        source_rows = source_db.query(NBAPrivateJobRun).order_by(
            NBAPrivateJobRun.id.asc()).all()
        if len(source_rows) > 10000:
            raise ValueError("NBA_AUDIT_HISTORY_LIMIT_REACHED")
        verified = []
        for item in source_rows:
            if (item.kind not in JOB_KINDS or len(item.status) > 40
                or len(item.summary_json) > 5000):
                raise ValueError("NBA_AUDIT_HISTORY_UNSAFE_ROW")
            json.loads(item.summary_json)
            verified.append((item.id, item.kind, item.status,
                             item.summary_json, item.recorded_at))
    finally:
        source_db.close()

    target = isolated_target_is_safe(target_url, source_url)
    engine = engine_factory(target, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("SET LOCAL search_path TO nba_research")
            if conn.execute(text("SELECT current_schema()")).scalar() != "nba_research":
                raise ValueError("NBA_AUDIT_PRIVATE_SCHEMA_REQUIRED")
            table = NBAPrivateJobRun.__table__
            table.create(bind=conn, checkfirst=True)
            sql = text("SELECT id, kind, status, summary_json, recorded_at "
                       "FROM nba_private_job_runs ORDER BY id ASC")
            existing = [tuple(x) for x in conn.execute(sql).all()]
            fresh = verified_audit_prefix(existing, verified)
            if fresh:
                conn.execute(table.insert(), [
                    dict(zip(("id", "kind", "status", "summary_json", "recorded_at"), row))
                    for row in fresh
                ])
            if [tuple(x) for x in conn.execute(sql).all()] != verified:
                raise ValueError("NBA_AUDIT_TARGET_READBACK_MISMATCH")
            if verified:
                conn.exec_driver_sql(
                    "SELECT setval(pg_get_serial_sequence('nba_private_job_runs',"
                    "'id'), (SELECT max(id) FROM nba_private_job_runs), true)"
                )
        return {"status": "audit_history_mirrored", "rows_verified": len(verified),
                "new_rows_mirrored": len(verified)-len(existing),
                "source_unchanged": True, "research_only": True,
                "not_bookable": True, "cutover_approved": False}
    finally:
        engine.dispose()
