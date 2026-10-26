"""Destructive-operation-free NBA evidence restoration rehearsal.

Builds a disposable SQL database from a full export, then rereads every
archive ledger and every source-quoted market receipt by digest. This is an
isolated proof of export restorability, not a cloud disaster-recovery guarantee.
"""
from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from basketball.research_coldstart import _json
from basketball.research_private_bundle import _digest, inspect_bundle
from basketball.research_private_store import import_bundle, latest_bundle
from basketball.research_market_store import NBAMarketObservation
from basketball.research_ops_health import _verify_receipt


def verify_portable_backup(backup, *, require_sha=True):
    if not isinstance(backup, dict):
        raise ValueError("NBA_BACKUP_OBJECT_INVALID")
    expected={
        "version", "created_at", "archive", "archive_digest",
        "market_receipts", "market_receipt_count", "research_only",
        "not_bookable", "contains_private_research",
        "provider_data_rights_must_be_respected",
        "restore_drill_passed", "backup_sha256",
    }
    if set(backup) != expected:
        raise ValueError("NBA_BACKUP_SCHEMA_MISMATCH")
    if (backup["version"] != "betsightly-nba-private-offline-backup-v1"
        or backup["research_only"] is not True
        or backup["not_bookable"] is not True):
        raise ValueError("NBA_BACKUP_VERSION_OR_SCOPE_INVALID")
    signature=backup["backup_sha256"]
    unsigned={k:v for k,v in backup.items() if k!="backup_sha256"}
    if require_sha and hashlib.sha256(
        _json(unsigned).encode("utf-8")).hexdigest()!=signature:
        raise ValueError("NBA_BACKUP_DIGEST_MISMATCH")
    archive=backup["archive"]
    inspect_bundle(archive)
    if _digest(archive)!=backup["archive_digest"]:
        raise ValueError("NBA_BACKUP_ARCHIVE_DIGEST_MISMATCH")
    receipts=backup["market_receipts"]
    if not isinstance(receipts,list) or len(receipts)!=backup["market_receipt_count"]:
        raise ValueError("NBA_BACKUP_MARKET_COUNT_MISMATCH")
    if len(receipts)>160:
        raise ValueError("NBA_BACKUP_MARKET_LIST_UNBOUNDED")
    origin_ids={str(x["game_id"]) for x in archive["fixtures"]}
    digest_seen=set()
    for receipt in receipts:
        if not isinstance(receipt,dict) or "digest" not in receipt:
            raise ValueError("NBA_BACKUP_MARKET_RECEIPT_INVALID")
        sha=receipt["digest"]
        unsigned_receipt={k:v for k,v in receipt.items() if k!="digest"}
        if hashlib.sha256(_json(unsigned_receipt).encode("utf-8")).hexdigest()!=sha:
            raise ValueError("NBA_BACKUP_MARKET_RECEIPT_DIGEST_MISMATCH")
        if sha in digest_seen:
            raise ValueError("NBA_BACKUP_DUPLICATE_MARKET_SNAPSHOT")
        digest_seen.add(sha)
        for item in receipt.get("fixtures", []):
            if str(item.get("game_id")) not in origin_ids:
                raise ValueError("NBA_BACKUP_UNKNOWN_BOOKMAKER_FIXTURE")

    # No live DB connection: temporary memory-only independent restore.
    engine=create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        factory=sessionmaker(bind=engine)
        with factory() as session:
            receipt=import_bundle(archive,db=session)
            if receipt["digest"]!=backup["archive_digest"]:
                raise ValueError("NBA_BACKUP_RESTORE_WRONG_ARCHIVE")
            NBAMarketObservation.__table__.create(bind=engine,checkfirst=True)
            for row in receipts:
                session.add(NBAMarketObservation(
                    digest=row["digest"],payload_json=_json(row),
                    recorded_at=datetime.fromisoformat(
                        row["observed_at"].replace("Z", "+00:00")
                    ).replace(tzinfo=None),
                ))
            session.commit()
            restored=latest_bundle(session)
            if _digest(restored)!=backup["archive_digest"]:
                raise ValueError("NBA_BACKUP_RESTORE_DIGEST_MISMATCH")
            count=session.query(NBAMarketObservation).count()
            if count!=len(receipts):
                raise ValueError("NBA_BACKUP_RESTORE_MARKET_COUNT_MISMATCH")
            for row in session.query(NBAMarketObservation).all():
                _verify_receipt(row)
    finally:
        engine.dispose()
    return {
        "restore_drill_passed": True,
        "isolated_ephemeral_database": True,
        "archive_digest": backup["archive_digest"],
        "market_receipt_count": len(receipts),
        "permanent_database_unchanged": True,
    }
