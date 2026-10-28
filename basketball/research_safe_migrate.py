"""Fail-closed, one-time migration of an exported NBA research backup.

Requires a freshly created, EMPTY and separate Postgres target. Never modifies
source staging, football tables, or source DATABASE_URL. The local backup must
pass existing cryptographic archive/market and isolated SQLite restore drills.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from basketball.research_coldstart import _json
from basketball.research_restore_drill import verify_portable_backup
from basketball.research_private_store import import_bundle, latest_bundle
from basketball.research_market_store import NBAMarketObservation

MAX_BACKUP_FILE = 30_000_000


def load_checked_backup(path: str | Path):
    location = Path(path)
    if not location.is_file() or location.stat().st_size > MAX_BACKUP_FILE:
        raise ValueError("NBA_EXPORT_FILE_MISSING_OR_UNBOUNDED")
    with location.open("rb") as stream:
        raw = stream.read(MAX_BACKUP_FILE + 1)
    if len(raw) > MAX_BACKUP_FILE:
        raise ValueError("NBA_EXPORT_TOO_LARGE")
    try:
        backup = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("NBA_EXPORT_JSON_INVALID") from exc
    proof = verify_portable_backup(backup)
    if proof.get("restore_drill_passed") is not True:
        raise ValueError("NBA_EXPORT_RESTORE_DRILL_FAILED")
    return backup, proof


def isolated_target_is_safe(target: str, source_url: str | None = None):
    """Check only URL shape/identity here; SQL emptiness is checked on target."""
    if not isinstance(target, str) or not target.strip():
        raise ValueError("NBA_RESTORE_TARGET_NOT_PROVIDED")
    try:
        url = make_url(target)
        if url.get_backend_name() != "postgresql" or not url.database or not url.host:
            raise ValueError("NBA_RESTORE_TARGET_MUST_BE_POSTGRES")
        if source_url:
            current = make_url(source_url)
            if (url.host, url.port, url.username, url.database) == (
                current.host, current.port, current.username, current.database
            ):
                raise ValueError("NBA_RESTORE_REFUSES_SOURCE_DATABASE")
    except (TypeError, AttributeError) as exc:
        raise ValueError("NBA_RESTORE_TARGET_URL_INVALID") from exc
    return url


def probe_empty_target(target_url: str, *, source_url: str | None = None,
                       engine_factory=create_engine) -> dict:
    """Read-only test of distinct, empty, private PostgreSQL destination."""
    from sqlalchemy import text
    target = isolated_target_is_safe(target_url, source_url)
    engine = engine_factory(target, pool_pre_ping=True)
    try:
        # Supabase pooler connections default to public; change the search path
        # ONLY for this transaction, never globally or on the live source.
        # No caller input can become part of this fixed SQL statement.
        with engine.begin() as conn:
            conn.exec_driver_sql("SET LOCAL search_path TO nba_research")
            schema = str(conn.execute(text("SELECT current_schema()")).scalar() or "")
            if schema != "nba_research":
                raise ValueError("NBA_RESTORE_PRIVATE_SCHEMA_REQUIRED")
            tables = inspect(conn).get_table_names(schema=schema)
            if tables:
                raise ValueError("NBA_RESTORE_TARGET_NOT_EMPTY")
        return {"status": "target_empty", "schema": schema,
                "research_only": True, "not_bookable": True,
                "source_unchanged": True}
    finally:
        engine.dispose()


def restore_into_empty_target(backup: dict, target_url: str, *,
                              source_url: str | None = None, engine_factory=create_engine):
    """Atomic import into a freshly empty destination; never overwrite tables."""
    verify_portable_backup(backup)
    target = isolated_target_is_safe(target_url, source_url)
    engine = engine_factory(target, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            # Pin ALL SQLAlchemy model imports and readbacks to the private
            # Supabase schema for this transaction only, even via Supavisor.
            conn.exec_driver_sql("SET LOCAL search_path TO nba_research")
            schema = str(conn.exec_driver_sql("SELECT current_schema()").scalar() or "")
            if schema != "nba_research":
                raise ValueError("NBA_RESTORE_PRIVATE_SCHEMA_REQUIRED")
            if inspect(conn).get_table_names(schema=schema):
                raise ValueError("NBA_RESTORE_TARGET_NOT_EMPTY")
            session = sessionmaker(bind=conn)()
            try:
                response = import_bundle(backup["archive"], db=session)
                if response["digest"] != backup["archive_digest"]:
                    raise ValueError("NBA_RESTORE_ARCHIVE_WRONG_HASH")
                NBAMarketObservation.__table__.create(bind=conn, checkfirst=True)
                for item in backup["market_receipts"]:
                    session.add(NBAMarketObservation(
                        digest=item["digest"], payload_json=_json(item),
                        recorded_at=__parse_utc(item["observed_at"]),
                    ))
                session.flush()
                saved = latest_bundle(session)
                if saved is None or hashlib.sha256(
                    _json(saved).encode("utf-8")
                ).hexdigest() != backup["archive_digest"]:
                    raise ValueError("NBA_RESTORE_READBACK_WRONG_HASH")
                rows = session.query(NBAMarketObservation).all()
                if len(rows) != backup["market_receipt_count"]:
                    raise ValueError("NBA_RESTORE_MARKET_COUNT_DIFFERS")
                for row in rows:
                    payload = json.loads(row.payload_json)
                    if payload.get("digest") != row.digest:
                        raise ValueError("NBA_RESTORE_MARKET_ROW_HASH_DIFFERS")
                    unsigned = {k: v for k, v in payload.items() if k != "digest"}
                    if hashlib.sha256(_json(unsigned).encode("utf-8")).hexdigest() != row.digest:
                        raise ValueError("NBA_RESTORE_MARKET_DIGEST_DIFFERS")
            finally:
                session.close()
        return {
            "status": "restored_and_verified",
            "nba_only": True,
            "archive_sha256": backup["archive_digest"],
            "market_receipt_count": backup["market_receipt_count"],
            "source_unchanged": True,
            "target": "new_isolated_database",
        }
    finally:
        engine.dispose()


def __parse_utc(raw):
    from datetime import datetime, timezone
    parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("NBA_RESTORE_MARKET_TIMESTAMP_UNVERIFIED")
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def main(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", required=True)
    parser.add_argument("--confirm-sha256", default=None)
    parser.add_argument("--execute", action="store_true")
    ns = parser.parse_args(args)
    backup, proof = load_checked_backup(ns.backup)
    sha = backup["backup_sha256"]
    if not ns.execute:
        print(json.dumps({"status":"dry_run_ok", "backup_sha256":sha,
                          "archive_digest":backup["archive_digest"],
                          "market_receipt_count":proof["market_receipt_count"],
                          "fresh_postgres_needed":True,
                          "source_unchanged":True},sort_keys=True))
        return 0
    if ns.confirm_sha256 != sha:
        parser.error("--confirm-sha256 must match the verified export SHA256")
    destination = os.getenv("NBA_RESTORE_TARGET_DATABASE_URL")
    if not destination:
        parser.error("A dedicated NBA_RESTORE_TARGET_DATABASE_URL is required")
    response = restore_into_empty_target(
        backup, destination, source_url=os.getenv("DATABASE_URL"),
    )
    print(json.dumps(response,sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
