"""Read-only post-restore reconciliation against the live NBA source.

This never alters either database or stores source archives in GitHub logs.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import create_engine, text
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


def compare_live_source_to_target(target_url, *, source_url=None,
                                  engine_factory=create_engine):
    """Export live source NOW, then verify full target research evidence."""
    from basketball.research_ops_health import export_verified_backup
    backup = export_verified_backup()
    target = isolated_target_is_safe(target_url, source_url)
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
