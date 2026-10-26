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
from basketball.research_private_bundle import _digest, inspect_bundle, report_from_bundle
from basketball.research_private_store import (
    NBAPrivateSnapshot, latest_bundle,
)
from basketball.research_market_store import NBAMarketObservation
from basketball.research_market_presentation import present_market_snapshot

MAX_HISTORY = 160
MAX_BACKUP_BYTES = 8_000_000
MAX_RUNS = 20


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
    if kind not in ("forecast", "settlement", "market"):
        raise ValueError("NBA_UNKNOWN_JOB_KIND")
    safe = {"outcome": str(status)[:40]}
    for key in ("new_finals", "fixture_count", "fixture_matches", "new_forecasts"):
        value = (detail or {}).get(key)
        if isinstance(value, (int, dict)) and not isinstance(value, bool):
            safe[key] = value
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


def read_health(*, db=None):
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
        return {
            "status": "private_research_health",
            "research_only": True,
            "public_publishing_enabled": False,
            "archive_digest": _digest(archive),
            "fixtures": board["summary"]["fixtures"],
            "pending_fixtures": board["summary"]["pending_fixtures"],
            "verified_settlements": board["summary"]["verified_settlements"],
            "archive_capacity": 120,
            "remaining_fixture_slots": 120 - board["summary"]["fixtures"],
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
            "database_expiry_declared_at": os.getenv(
                "NBA_RESEARCH_DATABASE_EXPIRES_AT") or None,
            "backup_policy": "manual_export_only_no_offsite_backup",
            "automatic_backup_proven": False,
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
        }
        if len(_json(bundle).encode("utf-8")) > MAX_BACKUP_BYTES:
            raise ValueError("NBA_BACKUP_EXCEEDS_SAFE_DOWNLOAD_SIZE")
        bundle["backup_sha256"] = hashlib.sha256(
            _json(bundle).encode("utf-8")).hexdigest()
        return bundle
    finally:
        if owned:
            db.close()
