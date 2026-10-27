"""Private NBA research health, frozen market audit, and export readiness.

Read-only except explicit private job events. All outputs remain behind
administrator authentication and staging-only routing. No public odds,
predictions, wagers, or football database changes.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text, func
from database import Base, SessionLocal
from basketball.research_coldstart import _json
from basketball.research_private_bundle import _digest, inspect_bundle, report_from_bundle, MAX_FIXTURES
from basketball.research_private_store import (
    NBAPrivateSnapshot, latest_bundle,
)
from basketball.research_market_store import NBAMarketObservation
from basketball.research_market_presentation import present_market_snapshot

MAX_HISTORY = 600
MAX_BACKUP_BYTES = 10_000_000
MAX_RUNS = 20
JOB_EXPECTED_INTERVAL_HOURS = 36
JOB_KINDS = ("forecast", "settlement", "market", "backup")


def _utc_naive(instant: datetime) -> datetime:
    if instant.tzinfo is not None:
        return instant.astimezone(timezone.utc).replace(tzinfo=None)
    return instant


def _job_readiness(jobs, *, now: datetime) -> dict:
    """Last observed cron invocation, not proof that its work succeeded."""
    latest = {}
    for item in jobs:
        latest.setdefault(item.kind, item)
    summary = {}
    for kind in JOB_KINDS:
        item = latest.get(kind)
        if item is None:
            summary[kind] = {
                "state": "not_observed", "last_status": None,
                "last_observed_at": None, "age_hours": None,
            }
            continue
        seconds = (_utc_naive(now) - _utc_naive(item.recorded_at)).total_seconds()
        degraded = (item.status.startswith("http_") or
                    item.status in ("provider_partial", "source_not_fresh",
                                    "archive_capacity_reached"))
        state = (
            "clock_skew" if seconds < -300 else
            "stale" if seconds > JOB_EXPECTED_INTERVAL_HOURS * 3600 else
            "degraded" if degraded else "observed"
        )
        summary[kind] = {
            "state": state, "last_status": item.status,
            "last_observed_at": _utc_naive(item.recorded_at).isoformat() + "Z",
            "age_hours": round(max(0, seconds) / 3600, 2),
        }
    return summary


class NBAPrivateJobRun(Base):
    __tablename__ = "nba_private_job_runs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(20), nullable=False)
    status = Column(String(40), nullable=False)
    summary_json = Column(Text, nullable=False)
    recorded_at = Column(DateTime, nullable=False)


def _session_tables(db):
    NBAPrivateSnapshot.__table__.create(bind=db.get_bind(), checkfirst=True)
    NBAMarketObservation.__table__.create(bind=db.get_bind(), checkfirst=True)
    NBAPrivateJobRun.__table__.create(bind=db.get_bind(), checkfirst=True)


def _verify_receipt(record):
    content = json.loads(record.payload_json)
    digest = content.pop("digest", None)
    if (digest != record.digest or
            hashlib.sha256(_json(content).encode("utf-8")).hexdigest() != digest):
        raise ValueError("NBA_RESEARCH_MARKET_HISTORY_DIGEST_INVALID")
    content["digest"] = digest
    return content


def record_run(kind, status, *, detail=None):
    """Best-effort observability only; never store secrets or request payloads."""
    if kind not in ("forecast", "settlement", "market", "backup"):
        raise ValueError("NBA_UNKNOWN_JOB_KIND")
    safe = {"outcome": str(status)[:40]}
    for key in ("new_finals", "fixture_count", "fixture_matches", "new_forecasts"):
        value = (detail or {}).get(key)
        if isinstance(value, (int, dict)) and not isinstance(value, bool):
            safe[key] = value
    if kind == "settlement":
        provider = (detail or {}).get("provider_status")
        if provider in ("ok", "partial", "idle"):
            safe["provider_status"] = provider
        failed = (detail or {}).get("failed_dates")
        if isinstance(failed, list):
            safe["failed_date_count"] = min(len(failed), 12)
    if kind == "backup":
        digest = (detail or {}).get("archive_digest")
        if isinstance(digest, str) and len(digest) == 64 and all(
                ch in "0123456789abcdef" for ch in digest):
            safe["archive_digest"] = digest
    db = SessionLocal()
    try:
        _session_tables(db)
        db.add(NBAPrivateJobRun(
            kind=kind, status=str(status)[:40], summary_json=_json(safe),
            recorded_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def read_health(*, db=None, now: datetime | None = None):
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("NBA_HEALTH_CLOCK_MUST_BE_UTC_AWARE")
    owned = db is None
    db = db or SessionLocal()
    try:
        _session_tables(db)
        archive = latest_bundle(db)
        if archive is None:
            raise ValueError("NBA_RESEARCH_ARCHIVE_MISSING")
        board = report_from_bundle(archive)
        snapshot_count = db.query(func.count(NBAPrivateSnapshot.id)).scalar() or 0
        market_count = db.query(func.count(NBAMarketObservation.id)).scalar() or 0
        latest_market = db.query(NBAMarketObservation).order_by(
            NBAMarketObservation.id.desc()).first()
        if latest_market is not None:
            _verify_receipt(latest_market)
        jobs = db.query(NBAPrivateJobRun).order_by(
            NBAPrivateJobRun.id.desc()).limit(MAX_RUNS).all()
        backups = [row for row in jobs if row.kind == "backup"
                   and row.status == "verified_private_blob_readback"]
        archive_digest = _digest(archive)
        latest_backup = backups[0] if backups else None
        backup_summary = json.loads(latest_backup.summary_json) if latest_backup else {}
        backup_age = (
            (_utc_naive(clock) - _utc_naive(latest_backup.recorded_at)).total_seconds()
            if latest_backup else None
        )
        # Receipt must be recent and match the *current* signed archive.
        # Market-history completeness requires its own separate readback proof.
        recent_archive_backup = bool(
            latest_backup is not None and backup_age is not None
            and 0 <= backup_age <= JOB_EXPECTED_INTERVAL_HOURS * 3600
            and backup_summary.get("archive_digest") == archive_digest
        )
        return {
            "status": "private_research_health",
            "research_only": True,
            "public_publishing_enabled": False,
            "archive_digest": archive_digest,
            "fixtures": board["summary"]["fixtures"],
            "pending_fixtures": board["summary"]["pending_fixtures"],
            "verified_settlements": board["summary"]["verified_settlements"],
            "archive_capacity": MAX_FIXTURES,
            "remaining_fixture_slots": MAX_FIXTURES - board["summary"]["fixtures"],
            "research_snapshots": snapshot_count,
            "market_snapshots": market_count,
            "last_market_observed_at": (
                _verify_receipt(latest_market)["observed_at"]
                if latest_market is not None else None
            ),
            "jobs": [
                {"kind": item.kind, "status": item.status,
                 "recorded_at": item.recorded_at.isoformat()+"Z",
                 "summary": json.loads(item.summary_json)}
                for item in jobs
            ],
            "job_readiness": _job_readiness(jobs, now=clock),
            "database_expiry_declared_at": os.getenv(
                "NBA_RESEARCH_DATABASE_EXPIRES_AT") or None,
            "backup_policy": "private_vercel_blob_daily_snapshot_with_hash_readback",
            "automatic_backup_proven": bool(backups),
            "backup_recent_for_current_archive": recent_archive_backup,
            "last_backup_audit": backups[0].recorded_at.isoformat() + "Z" if backups else None,
        }
    finally:
        if owned:
            db.close()


def frozen_market_history(*, db=None):
    owned = db is None
    db = db or SessionLocal()
    try:
        _session_tables(db)
        archive = latest_bundle(db)
        if archive is None:
            raise ValueError("NBA_RESEARCH_ARCHIVE_MISSING")
        board = report_from_bundle(archive)
        total = db.query(func.count(NBAMarketObservation.id)).scalar() or 0
        receipts = db.query(NBAMarketObservation).order_by(
            NBAMarketObservation.id.asc()).limit(MAX_HISTORY).all()
        by_game = {}
        for saved in receipts:
            snapshot = _verify_receipt(saved)
            for event in snapshot["fixtures"]:
                game_id = event["game_id"]
                if game_id in by_game:
                    continue
                # Every frozen reference is from the first recorded,
                # before-tipoff bookmaker observation for this game.
                report = present_market_snapshot(board, {
                    **snapshot, "fixtures": [event]})
                if report["reference_games"]:
                    by_game[game_id] = report["reference_games"][0]
        results = sorted(by_game.values(), key=lambda x: (
            x["tipoff_utc"], x["game_id"]))
        completed = [r for r in results if r["paper_grade"] in (
            "correct", "incorrect", "push"
        )]
        return {
            "status": "first_pregame_market_snapshot_per_game",
            "research_only": True, "real_bets_placed": 0,
            "evaluated_games": len(results),
            "results": results,
            "source_snapshots_examined": len(receipts),
            "source_snapshots_total": total,
            "history_truncated": total > len(receipts),
            "paper_results": {
                "correct": sum(r["paper_grade"] == "correct" for r in completed),
                "incorrect": sum(r["paper_grade"] == "incorrect" for r in completed),
                "push": sum(r["paper_grade"] == "push" for r in completed),
                "pending": len(results)-len(completed),
            },
            "calibrated_betting_edge": False,
            "no_market_recommendations": True,
        }
    finally:
        if owned:
            db.close()


def export_verified_backup(*, db=None):
    """Explicit portable FULL export; refuse partial downloads."""
    owned = db is None
    db = db or SessionLocal()
    try:
        _session_tables(db)
        archive = latest_bundle(db)
        if archive is None:
            raise ValueError("NBA_RESEARCH_ARCHIVE_MISSING")
        inspect_bundle(archive)
        market_count = db.query(func.count(NBAMarketObservation.id)).scalar() or 0
        if market_count > MAX_HISTORY:
            raise ValueError("NBA_BACKUP_TOO_MANY_MARKET_SNAPSHOTS")
        receipts = db.query(NBAMarketObservation).order_by(
            NBAMarketObservation.id.asc()).all()
        markets = [_verify_receipt(r) for r in receipts]
        bundle = {
            "version": "betsightly-nba-private-offline-backup-v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "archive": archive,
            "archive_digest": _digest(archive),
            "market_receipts": markets,
            "market_receipt_count": market_count,
            "research_only": True,
            "not_bookable": True,
            "contains_private_research": True,
            "provider_data_rights_must_be_respected": True,
            "restore_drill_passed": True,
            "backup_sha256": "pending",
        }
        if len(_json(bundle).encode("utf-8")) > MAX_BACKUP_BYTES:
            raise ValueError("NBA_BACKUP_EXCEEDS_SAFE_DOWNLOAD_SIZE")
        from basketball.research_restore_drill import verify_portable_backup
        result = verify_portable_backup(bundle, require_sha=False)
        if result["restore_drill_passed"] is not True:
            raise ValueError("NBA_BACKUP_RESTORE_DRILL_FAILED")
        unsigned = {k: v for k, v in bundle.items() if k != "backup_sha256"}
        bundle["backup_sha256"] = hashlib.sha256(
            _json(unsigned).encode("utf-8")).hexdigest()
        return bundle
    finally:
        if owned:
            db.close()
