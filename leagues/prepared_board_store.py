"""Optional persistent cache for the fully evaluated prepared Builder board.

The immutable decision archive is intentionally compact and cannot reconstruct
the runtime Builder universe. This store keeps the complete already-evaluated
prepared entry so a new process can serve the last safe board immediately
while a replacement refresh runs in the background.

Persistence is feature-flagged and disabled by default. Merely importing this
module never creates a table.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    delete,
    insert,
    select,
)

from database import engine

logger = logging.getLogger(__name__)

FEATURE_FLAG = "PREPARED_BOARD_PERSISTENCE_ENABLED"
SCHEMA_VERSION = "prepared-board-v1"
MAX_COMPRESSED_BYTES = 64 * 1024 * 1024

metadata = MetaData()

prepared_board_cache = Table(
    "prepared_board_cache",
    metadata,
    Column("cache_key", String(96), primary_key=True),
    Column("schema_version", String(32), nullable=False),
    Column("horizon_days", Integer, nullable=False, index=True),
    Column("slot", String(16), nullable=False),
    Column("saved_at", DateTime(timezone=True), nullable=False),
    Column("payload_sha256", String(64), nullable=False),
    Column("payload_bytes", Integer, nullable=False),
    Column("payload", LargeBinary, nullable=False),
)


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def enabled() -> bool:
    return _truthy(os.getenv(FEATURE_FLAG, "false"))


def ensure_table() -> None:
    """Create only this cache table, and only after the feature flag is on."""
    if not enabled():
        return
    metadata.create_all(
        engine,
        tables=[prepared_board_cache],
        checkfirst=True,
    )


def _cache_key(days_ahead: int, slot: str) -> str:
    return f"{SCHEMA_VERSION}:{int(days_ahead)}:{slot}"


def _encode(entry: dict) -> tuple[bytes, str]:
    raw = json.dumps(
        entry,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
        allow_nan=False,
    ).encode("utf-8")
    payload = gzip.compress(
        raw,
        compresslevel=6,
        mtime=0,
    )
    if len(payload) > MAX_COMPRESSED_BYTES:
        raise ValueError(
            "prepared board payload exceeds "
            f"{MAX_COMPRESSED_BYTES} compressed bytes"
        )
    return payload, hashlib.sha256(payload).hexdigest()


def _decode(payload: bytes, expected_sha256: str) -> dict:
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_sha256:
        raise ValueError("prepared board payload hash mismatch")

    value = json.loads(
        gzip.decompress(payload).decode("utf-8")
    )

    if not isinstance(value, dict):
        raise ValueError("prepared board payload must be an object")
    if not isinstance(value.get("picks"), list):
        raise ValueError("prepared board payload missing picks")
    if not isinstance(value.get("fixtures"), list):
        raise ValueError("prepared board payload missing fixtures")
    if not isinstance(value.get("metadata"), dict):
        raise ValueError("prepared board payload missing metadata")

    value.setdefault(
        "builder_supplemental_picks",
        [],
    )
    value["ts"] = float(
        value.get("ts") or 0
    )
    return value


def persist_entry(
    days_ahead: int,
    entry: dict,
    *,
    healthy: bool,
) -> dict:
    """Persist latest, and preserve a separate last-healthy slot."""
    if not enabled():
        return {"status": "disabled"}

    ensure_table()

    payload, payload_sha256 = _encode(entry)
    slots = ["latest"]
    if healthy:
        slots.append("healthy")

    saved_at = datetime.now(timezone.utc)

    with engine.begin() as conn:
        for slot in slots:
            key = _cache_key(
                days_ahead,
                slot,
            )
            conn.execute(
                delete(
                    prepared_board_cache
                ).where(
                    prepared_board_cache.c.cache_key
                    == key
                )
            )
            conn.execute(
                insert(
                    prepared_board_cache
                ).values(
                    cache_key=key,
                    schema_version=SCHEMA_VERSION,
                    horizon_days=int(days_ahead),
                    slot=slot,
                    saved_at=saved_at,
                    payload_sha256=payload_sha256,
                    payload_bytes=len(payload),
                    payload=payload,
                )
            )

    return {
        "status": "saved",
        "slots": slots,
        "payload_bytes": len(payload),
        "payload_sha256": payload_sha256,
    }


def load_entries() -> list[dict]:
    """Return all valid current-version cache slots, newest first."""
    if not enabled():
        return []

    ensure_table()

    with engine.connect() as conn:
        rows = conn.execute(
            select(
                prepared_board_cache
            ).where(
                prepared_board_cache.c.schema_version
                == SCHEMA_VERSION
            ).order_by(
                prepared_board_cache.c.saved_at.desc()
            )
        ).mappings().all()

    out = []

    for row in rows:
        try:
            entry = _decode(
                bytes(row["payload"]),
                str(row["payload_sha256"]),
            )
        except Exception as exc:
            logger.warning(
                "ignored invalid persisted prepared board "
                "key=%s error=%s",
                row["cache_key"],
                exc,
            )
            continue

        out.append({
            "horizon_days": int(
                row["horizon_days"]
            ),
            "slot": str(
                row["slot"]
            ),
            "saved_at": row["saved_at"],
            "entry": entry,
        })

    return out
