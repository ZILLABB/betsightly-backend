"""Versioned full private NBA recovery envelope (no production rollout).

V1 portable backups remain readable and the existing Vercel cron stays V1.
V2 adds immutable scheduler-audit records and independently restores them in
an ephemeral database to verify full research/market/audit history readback.
Never stores tokens, football data, or public predictions.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from basketball.research_coldstart import _json
from basketball.research_ops_health import (
    JOB_KINDS, NBAPrivateJobRun, SessionLocal, export_verified_backup,
)
from basketball.research_restore_drill import verify_portable_backup

VERSION = "betsightly-nba-private-full-recovery-v2"
MAX_JOB_ROWS = 10000
MAX_RECOVERY_BYTES = 30_000_000
ALLOWED_SUMMARY_KEYS = frozenset({
    "outcome", "new_finals", "fixture_count", "fixture_matches",
    "new_forecasts", "provider_status", "failed_date_count", "archive_digest",
    "reason", "readiness", "coverage",
})


def _validate_rows(records):
    if not isinstance(records, list) or len(records) > MAX_JOB_ROWS:
        raise ValueError("NBA_RECOVERY_AUDIT_HISTORY_UNBOUNDED")
    previous = 0
    for record in records:
        if not isinstance(record, dict) or set(record) != {
            "id", "kind", "status", "summary_json", "recorded_at"
        }:
            raise ValueError("NBA_RECOVERY_AUDIT_ROW_INVALID")
        rid = record["id"]
        if type(rid) is not int or rid <= previous:
            raise ValueError("NBA_RECOVERY_AUDIT_IDENTITY_INVALID")
        previous = rid
        if (record["kind"] not in JOB_KINDS or
            not isinstance(record["status"], str) or
            not 1 <= len(record["status"]) <= 40):
            raise ValueError("NBA_RECOVERY_AUDIT_SCOPE_INVALID")
        raw = record["summary_json"]
        if not isinstance(raw, str) or len(raw) > 5000:
            raise ValueError("NBA_RECOVERY_AUDIT_SUMMARY_INVALID")
        try:
            summary = json.loads(raw)
            at = datetime.fromisoformat(record["recorded_at"].replace("Z", "+00:00"))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("NBA_RECOVERY_AUDIT_CONTENT_INVALID") from exc
        if (not isinstance(summary, dict) or
            any(key not in ALLOWED_SUMMARY_KEYS for key in summary) or
            at.tzinfo is None or at.utcoffset() is None or
            at.utcoffset().total_seconds() != 0):
            raise ValueError("NBA_RECOVERY_AUDIT_CONTENT_INVALID")


def _row_for_backup(row):
    return {
        "id": row.id,
        "kind": row.kind,
        "status": row.status,
        "summary_json": row.summary_json,
        "recorded_at": row.recorded_at.replace(tzinfo=timezone.utc).isoformat(),
    }


def build_full_recovery(*, db=None):
    """Export current private source using one session; no source changes."""
    owned = db is None
    db = db or SessionLocal()
    try:
        backup = export_verified_backup(db=db)
        NBAPrivateJobRun.__table__.create(bind=db.get_bind(), checkfirst=True)
        jobs = [_row_for_backup(item) for item in
                db.query(NBAPrivateJobRun).order_by(NBAPrivateJobRun.id.asc()).all()]
        _validate_rows(jobs)
        envelope = {
            "version": VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "portable_backup_v1": backup,
            "job_receipts": jobs,
            "job_receipt_count": len(jobs),
            "research_only": True,
            "not_bookable": True,
        }
        envelope["sha256"] = hashlib.sha256(
            _json(envelope).encode("utf-8")).hexdigest()
        if len(_json(envelope).encode("utf-8")) > MAX_RECOVERY_BYTES:
            raise ValueError("NBA_RECOVERY_EXPORT_TOO_LARGE")
        verify_full_recovery(envelope)
        return envelope
    finally:
        if owned:
            db.close()


def verify_full_recovery(envelope):
    """Fail closed on truncation/tampering; restore job rows in temporary SQL.

    This verifies export format and isolated recoverability, not offsite
    retention or full disaster recovery of the live Supabase service.
    """
    if not isinstance(envelope, dict) or set(envelope) != {
        "version", "created_at", "portable_backup_v1", "job_receipts",
        "job_receipt_count", "research_only", "not_bookable", "sha256",
    } or envelope["version"] != VERSION or envelope["research_only"] is not True or (
        envelope["not_bookable"] is not True
    ):
        raise ValueError("NBA_RECOVERY_SCHEMA_INVALID")
    if len(_json(envelope).encode("utf-8")) > MAX_RECOVERY_BYTES:
        raise ValueError("NBA_RECOVERY_EXPORT_TOO_LARGE")
    unsigned = {k: v for k, v in envelope.items() if k != "sha256"}
    actual = hashlib.sha256(_json(unsigned).encode("utf-8")).hexdigest()
    if envelope["sha256"] != actual:
        raise ValueError("NBA_RECOVERY_SIGNATURE_MISMATCH")
    rows = envelope["job_receipts"]
    if type(envelope["job_receipt_count"]) is not int or (
        envelope["job_receipt_count"] != len(rows)
    ):
        raise ValueError("NBA_RECOVERY_AUDIT_COUNT_INVALID")
    _validate_rows(rows)
    original = verify_portable_backup(envelope["portable_backup_v1"])
    if original["restore_drill_passed"] is not True:
        raise ValueError("NBA_RECOVERY_ARCHIVE_RESTORE_FAILED")
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        NBAPrivateJobRun.__table__.create(bind=engine, checkfirst=True)
        factory = sessionmaker(bind=engine)
        with factory() as session:
            for row in rows:
                session.add(NBAPrivateJobRun(
                    id=row["id"], kind=row["kind"], status=row["status"],
                    summary_json=row["summary_json"],
                    recorded_at=datetime.fromisoformat(
                        row["recorded_at"].replace("Z", "+00:00")
                    ).replace(tzinfo=None),
                ))
            session.commit()
            recovered = [
                _row_for_backup(item) for item in session.query(
                    NBAPrivateJobRun
                ).order_by(NBAPrivateJobRun.id.asc()).all()
            ]
            if recovered != rows:
                raise ValueError("NBA_RECOVERY_AUDIT_READBACK_MISMATCH")
    finally:
        engine.dispose()
    return {
        "status": "full_private_recovery_drill_passed",
        "research_only": True,
        "not_bookable": True,
        "archive_digest": envelope["portable_backup_v1"]["archive_digest"],
        "market_receipt_count": envelope["portable_backup_v1"]["market_receipt_count"],
        "job_receipt_count": len(rows),
        "isolated_ephemeral_database": True,
        "source_unchanged": True,
        "offsite_storage_proven": False,
    }
