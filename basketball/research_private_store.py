"""Isolated append-only NBA research archive snapshots in existing Postgres.

No changes to football tables, results, calibration or published slips.
Import is always explicit and protected by the existing admin session.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text, text
from database import Base, SessionLocal
from basketball.research_coldstart import _json
from basketball.research_private_bundle import (
    inspect_bundle, unchanged_prior, report_from_bundle,
)

class NBAPrivateSnapshot(Base):
    __tablename__ = "nba_private_research_snapshots"
    id = Column(Integer, primary_key=True, autoincrement=True)
    digest = Column(String(64), unique=True, nullable=False, index=True)
    bundle_json = Column(Text, nullable=False)
    inserted_at = Column(DateTime, nullable=False)


def _ensure(db):
    """Scoped creation of ONLY the NBA-private table, never all Base tables."""
    NBAPrivateSnapshot.__table__.create(bind=db.get_bind(), checkfirst=True)


def _lock(db):
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                   {"key": 487139510021})


def latest_bundle(db):
    _ensure(db)
    newest = db.query(NBAPrivateSnapshot).order_by(
        NBAPrivateSnapshot.id.desc()).first()
    if newest is None:
        return None
    import json
    body = json.loads(newest.bundle_json)
    digest = hashlib.sha256(_json(body).encode("utf-8")).hexdigest()
    if digest != newest.digest:
        raise ValueError("Stored NBA research snapshot digest mismatch")
    # Original forecast hashes and result identities are checked downstream.
    return body


def import_bundle(bundle, *, db=None):
    """Atomic append. Retries return 'already_saved'; rewrites are rejected."""
    # Fail closed BEFORE we ever create the private NBA table or insert data.
    evaluated = inspect_bundle(bundle)
    encoded = _json(bundle)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    owns_session = db is None
    if owns_session:
        db = SessionLocal()
    try:
        _ensure(db)
        _lock(db)
        previous = latest_bundle(db)
        if previous is not None:
            unchanged_prior(previous, bundle)
            previous_digest = hashlib.sha256(
                _json(previous).encode("utf-8")).hexdigest()
            if previous_digest == digest:
                return {
                    "status": "already_saved", "digest": digest,
                    "fixture_count": evaluated["summary"]["fixtures"],
                    "research_only": True, "not_bookable": True,
                }
        db.add(NBAPrivateSnapshot(
            digest=digest, bundle_json=encoded,
            inserted_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ))
        db.commit()
        return {
            "status": "saved_and_verified", "digest": digest,
            "fixture_count": evaluated["summary"]["fixtures"],
            "records": evaluated["summary"]["forecasts"],
            "research_only": True, "not_bookable": True,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        if owns_session:
            db.close()


def hosted_board():
    db = SessionLocal()
    try:
        saved = latest_bundle(db)
        if saved is None:
            return None
        # Rerun the original 3 archive integrity audits on EVERY admin read.
        return report_from_bundle(saved)
    finally:
        db.close()
