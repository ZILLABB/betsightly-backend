"""PostgreSQL-backed completed history and crash-recoverable refresh claims.

No external service is required: production already has PostgreSQL. Claims and
artifact promotion are short transactions; provider I/O never holds a DB
connection. Local SQLite engines can be injected for multi-instance tests.
"""

import hashlib
import json
import os
import uuid
from contextlib import contextmanager

from sqlalchemy import text

def production_shared() -> bool:
    return os.getenv("ENVIRONMENT", "").lower() in {"production", "staging"}


def _engine(engine=None):
    if engine is not None:
        return engine
    from database import engine as configured
    return configured


def _db_epoch(engine) -> str:
    """Use the database clock, not potentially skewed app-instance clocks."""
    if engine.dialect.name == "postgresql":
        return "EXTRACT(EPOCH FROM clock_timestamp())"
    if engine.dialect.name == "sqlite":
        return "CAST(strftime('%s', 'now') AS REAL)"
    raise RuntimeError("unsupported history lease database")


def read(cache_key: str, schema: int, *, required: str, engine=None):
    db = _engine(engine)
    with db.connect() as conn:
        row = conn.execute(text(
            "SELECT schema_version, payload, payload_sha256 FROM history_artifacts "
            "WHERE cache_key = :key"), {"key": cache_key}).first()
    if not row or row[0] != schema or not row[1]:
        return None
    if hashlib.sha256(row[1].encode("utf-8")).hexdigest() != row[2]:
        return None
    data = json.loads(row[1])
    if (not isinstance(data, dict) or data.get("_cache_schema") != schema
            or data.get("_failed_leagues") or data.get("failed_leagues")
            or required not in data):
        return None
    return data


def lease_active(cache_key: str, *, engine=None) -> bool:
    db = _engine(engine)
    now = _db_epoch(db)
    with db.connect() as conn:
        row = conn.execute(text(
            "SELECT lease_until > " + now + " FROM history_artifacts "
            "WHERE cache_key = :key"),
            {"key": cache_key}).first()
    return bool(row and row[0])


@contextmanager
def claim(cache_key: str, schema: int, *, lease_seconds: int = 900,
          engine=None):
    db = _engine(engine)
    owner = str(uuid.uuid4())
    now = _db_epoch(db)
    with db.begin() as conn:
        conn.execute(text(
            "INSERT INTO history_artifacts (cache_key, schema_version) "
            "VALUES (:key, :schema) ON CONFLICT (cache_key) DO NOTHING"),
            {"key": cache_key, "schema": schema})
        updated = conn.execute(text(
            "UPDATE history_artifacts SET lease_owner = :owner, "
            "lease_until = " + now + " + :seconds WHERE cache_key = :key "
            "AND schema_version = :schema "
            "AND (lease_until IS NULL OR lease_until < " + now + ")"),
            {"owner": owner, "seconds": lease_seconds,
             "key": cache_key, "schema": schema})
        acquired = updated.rowcount == 1
    try:
        yield owner if acquired else None
    finally:
        if acquired:
            with db.begin() as conn:
                conn.execute(text(
                    "UPDATE history_artifacts SET lease_owner = NULL, "
                    "lease_until = NULL WHERE cache_key = :key "
                    "AND lease_owner = :owner"),
                    {"key": cache_key, "owner": owner})


def promote(cache_key: str, schema: int, data: dict, owner: str,
            *, required: str, engine=None) -> bool:
    if (not isinstance(data, dict) or data.get("_cache_schema") != schema
            or data.get("_failed_leagues") or data.get("failed_leagues")
            or required not in data):
        raise ValueError("refusing incomplete shared history artifact")
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    db = _engine(engine)
    now = _db_epoch(db)
    with db.begin() as conn:
        changed = conn.execute(text(
            "UPDATE history_artifacts SET payload = :payload, "
            "payload_sha256 = :digest, schema_version = :schema, "
            "built_at = " + now + " WHERE cache_key = :key "
            "AND lease_owner = :owner AND schema_version = :schema "
            "AND lease_until >= " + now),
            {"payload": payload, "digest": digest, "schema": schema,
             "key": cache_key, "owner": owner})
    return changed.rowcount == 1
