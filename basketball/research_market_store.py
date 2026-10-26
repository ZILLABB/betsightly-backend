"""Append-only, isolated NBA bookmaker research receipts on STAGING ONLY.

Exact quoted line/odds observations are preserved with SHA256 digests.
No bets, booking codes, football tables or model calibration are modified.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text, text
from database import Base, SessionLocal
from basketball.research_coldstart import _json
from basketball.research_private_bundle import report_from_bundle
from basketball.research_private_store import latest_bundle
from basketball.research_market_watch import (
    fetch_exact_nba_markets, compare_to_archive,
)


class NBAMarketObservation(Base):
    __tablename__ = "nba_private_market_observations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    digest = Column(String(64), unique=True, nullable=False)
    payload_json = Column(Text, nullable=False)
    recorded_at = Column(DateTime, nullable=False)


def _latest(db):
    NBAMarketObservation.__table__.create(bind=db.get_bind(), checkfirst=True)
    last = db.query(NBAMarketObservation).order_by(
        NBAMarketObservation.id.desc()).first()
    if last is None:
        return None
    payload = json.loads(last.payload_json)
    digest = payload.pop("digest", None)
    if (digest != last.digest or
            hashlib.sha256(_json(payload).encode("utf-8")).hexdigest() != digest):
        raise ValueError("NBA_MARKET_DIGEST_MISMATCH")
    payload["digest"] = digest
    return payload


def read_observations(*, db=None):
    owns = db is None
    db = db or SessionLocal()
    try:
        archive = latest_bundle(db)
        if archive is None:
            raise ValueError("NBA_RESEARCH_ARCHIVE_MISSING")
        board = report_from_bundle(archive)
        observation = _latest(db)
        if observation is None:
            return {
                "status": "no_market_snapshot",
                "quoted_totals": [], "fixture_matches": 0,
                "calibrated_betting_edge": False,
                "research_only": True, "not_bookable": True,
            }
        return {
            **compare_to_archive(board, observation),
            "research_only": True,
        }
    finally:
        if owns:
            db.close()


def capture_observations(*, now=None, db=None, collector=None):
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("NAIVE_NBA_MARKET_CAPTURE_CLOCK")
    owns = db is None
    db = db or SessionLocal()
    try:
        archive = latest_bundle(db)
        if archive is None:
            raise ValueError("NBA_RESEARCH_ARCHIVE_MISSING")
        board = report_from_bundle(archive)
        receipt = (collector or fetch_exact_nba_markets)(
            archive["fixtures"], now=instant
        )
        # Independent reconciliation with the archived pregame board.
        comparisons = compare_to_archive(board, receipt)
        encoded = _json(receipt)
        if len(encoded.encode("utf-8")) > 250_000:
            raise ValueError("NBA_MARKET_RECEIPT_TOO_LARGE")
        NBAMarketObservation.__table__.create(
            bind=db.get_bind(), checkfirst=True)
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                       {"key": 487139510023})
        existing = db.query(NBAMarketObservation).filter(
            NBAMarketObservation.digest == receipt["digest"]).first()
        if existing is None:
            db.add(NBAMarketObservation(
                digest=receipt["digest"], payload_json=encoded,
                recorded_at=instant.astimezone(timezone.utc).replace(
                    tzinfo=None),
            ))
            db.commit()
        return {
            **comparisons,
            "status": ("saved" if existing is None else "already_saved"),
            "archive_unchanged": True,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        if owns:
            db.close()
