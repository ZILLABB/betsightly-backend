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
JOB_MAX_AGE_HOURS = {"forecast": 30, "settlement": 8, "market": 36, "backup": 30}
BACKUP_V2_STATUS = "verified_full_private_blob_readback"
BACKUP_V1_STATUS = "verified_private_blob_readback"
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
            "stale" if seconds > JOB_MAX_AGE_HOURS[kind] * 3600 else
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
    if kind == "forecast":
        reason = (detail or {}).get("reason")
        if reason in ("eligible_forecasts_already_recorded",
                      "no_model_eligible_fixture_in_window"):
            safe["reason"] = reason
        readiness = (detail or {}).get("readiness")
        allowed = ("moneyline_eligible", "moneyline_already_recorded",
                   "original_score_eligible", "original_score_already_recorded",
                   "upcoming_source_fixtures")
        if isinstance(readiness, dict):
            safe["readiness"] = {
                key: value for key in allowed
                if (type(value := readiness.get(key)) is int
                    and 0 <= value <= 10000)
            }
    if kind == "settlement":
        provider = (detail or {}).get("provider_status")
        if provider in ("ok", "partial", "idle"):
            safe["provider_status"] = provider
        failed = (detail or {}).get("failed_dates")
        if isinstance(failed, list):
            safe["failed_date_count"] = min(len(failed), 12)
    if kind == "backup":
        for key in ("job_receipt_count", "market_receipt_count", "last_job_id"):
            value = (detail or {}).get(key)
            if type(value) is int and 0 <= value <= 10000:
                safe[key] = value
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
        # Backup receipts must NOT be discovered only through the last 20
        # general jobs: frequent settlement jobs can otherwise hide a valid
        # backup and incorrectly report no offsite recovery.
        latest_backup = db.query(NBAPrivateJobRun).filter(
            NBAPrivateJobRun.kind == "backup",
            NBAPrivateJobRun.status.in_((BACKUP_V1_STATUS, BACKUP_V2_STATUS))
        ).order_by(NBAPrivateJobRun.id.desc()).first()
        archive_digest = _digest(archive)
        backup_version = ("v2" if latest_backup is not None and
                          latest_backup.status == BACKUP_V2_STATUS else
                          "v1" if latest_backup is not None else None)
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
            # Snapshot digest alone does not cover later market receipts.
            and (latest_market is None or
                 _utc_naive(latest_market.recorded_at)
                    <= _utc_naive(latest_backup.recorded_at))
        )
        latest_job_id = db.query(func.max(NBAPrivateJobRun.id)).scalar() or 0
        # A V2 receipt is inserted AFTER the downloaded ledger was frozen;
        # its own audit row is therefore intentionally backed up next time.
        prev_id = (db.query(func.max(NBAPrivateJobRun.id)).filter(
            NBAPrivateJobRun.id < latest_backup.id).scalar()
                   if latest_backup is not None else None)
        fully_backed_jobs = bool(
            backup_version == "v2"
            and type(backup_summary.get("last_job_id")) is int
            and backup_summary["last_job_id"] == (prev_id or 0)
            and latest_job_id == latest_backup.id
        )
        future = [g for g in archive["fixtures"] if
                  g["status"] == "scheduled" and
                  datetime.fromisoformat(g["start_utc"].replace("Z", "+00:00"))
                  > clock.astimezone(timezone.utc)]
        money_ids = {r["game_id"] for r in archive["records"]["moneyline"]}
        score_ids = {r["game_id"] for r in archive["records"]["opening_score"]}
        completed_model_pairs = sum(
            str(g["game_id"]) in money_ids and str(g["game_id"]) in score_ids
            for g in future
        )
        remaining = MAX_FIXTURES - board["summary"]["fixtures"]
        capacity_state = ("exhausted" if remaining <= 0 else
                          "near_limit" if remaining <= max(30, MAX_FIXTURES // 10)
                          else "normal")
        return {
            "status": "private_research_health",
            "research_only": True,
            "public_publishing_enabled": False,
            "archive_digest": archive_digest,
            "fixtures": board["summary"]["fixtures"],
            "pending_fixtures": board["summary"]["pending_fixtures"],
            "verified_settlements": board["summary"]["verified_settlements"],
            "archive_capacity": MAX_FIXTURES,
            "remaining_fixture_slots": remaining,
            "archive_capacity_state": capacity_state,
            "archive_capacity_requires_scale_plan": capacity_state != "normal",
            "archive_cohort_coverage": {
                "future_archived_fixtures": len(future),
                "future_with_moneyline_and_score": completed_model_pairs,
                "future_missing_either_model": len(future) - completed_model_pairs,
                "full_league_schedule_completeness_proven": False,
            },
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
            "job_readiness": _job_readiness(
                jobs + ([latest_backup] if latest_backup is not None and
                        all(j.id != latest_backup.id for j in jobs) else []),
                now=clock,
            ),
            "database_expiry_declared_at": os.getenv(
                "NBA_RESEARCH_DATABASE_EXPIRES_AT") or None,
            "backup_policy": "private_vercel_blob_daily_snapshot_with_hash_readback",
            "automatic_backup_proven": latest_backup is not None,
            "backup_version": backup_version,
            "backup_recent_for_current_archive": recent_archive_backup,
            "backup_recovery_scope": (
                "research_archive_market_receipts_and_job_audit_history"
                if backup_version == "v2" else
                "research_archive_and_market_receipts_only"
            ),
            "job_audit_history_in_portable_backup": backup_version == "v2",
            "backup_covers_latest_job_history": fully_backed_jobs,
            "last_backed_job_id": (
                backup_summary.get("last_job_id") if backup_version == "v2"
                else None
            ),
            "backup_covers_current_market_history": bool(
                latest_backup is not None and
                (latest_market is None or
                 _utc_naive(latest_market.recorded_at)
                    <= _utc_naive(latest_backup.recorded_at))
            ),
            "last_backup_audit": (
                latest_backup.recorded_at.isoformat() + "Z" if latest_backup
                else None
            ),
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
