"""Database-visible heartbeat for background runtime ownership."""

from __future__ import annotations

import json
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    Text,
    inspect,
    select,
)

from database import engine


metadata = MetaData()

runtime_process_heartbeats = Table(
    "runtime_process_heartbeats",
    metadata,
    Column("instance_id", String(128), primary_key=True),
    Column("role", String(32), nullable=False, index=True),
    Column("state", String(24), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("heartbeat_at", DateTime(timezone=True), nullable=False, index=True),
    Column("stopped_at", DateTime(timezone=True)),
    Column("ownership_json", Text),
)


_INSTANCE_ID = (
    os.getenv("RENDER_INSTANCE_ID")
    or os.getenv("HOSTNAME")
    or socket.gethostname()
    or str(uuid.uuid4())
)[:128]


def _utc(value):
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(
        timezone.utc
    )


def ensure_table(db_engine=engine) -> None:
    metadata.create_all(
        db_engine,
        tables=[
            runtime_process_heartbeats
        ],
        checkfirst=True,
    )


def instance_id() -> str:
    return _INSTANCE_ID


def touch(
    role: str,
    *,
    ownership: dict | None = None,
    now: datetime | None = None,
    db_engine=engine,
    process_instance_id: str | None = None,
) -> dict:
    ensure_table(db_engine)

    current = _utc(
        now or datetime.now(timezone.utc)
    )

    identity = str(
        process_instance_id
        or _INSTANCE_ID
    )[:128]

    values = {
        "role":
            str(role)[:32],

        "state":
            "running",

        "heartbeat_at":
            current,

        "stopped_at":
            None,

        "ownership_json":
            json.dumps(
                ownership or {},
                separators=(",", ":"),
                sort_keys=True,
            ),
    }

    with db_engine.begin() as conn:
        existing = conn.execute(
            select(
                runtime_process_heartbeats
                .c.instance_id
            ).where(
                runtime_process_heartbeats
                .c.instance_id
                == identity
            )
        ).first()

        if existing:
            conn.execute(
                runtime_process_heartbeats
                .update()
                .where(
                    runtime_process_heartbeats
                    .c.instance_id
                    == identity
                )
                .values(
                    **values
                )
            )

        else:
            conn.execute(
                runtime_process_heartbeats
                .insert()
                .values(
                    instance_id=identity,
                    started_at=current,
                    **values,
                )
            )

    return {
        "instance_id":
            identity,

        "role":
            str(role),

        "state":
            "running",

        "heartbeat_at":
            current.isoformat(),
    }


def mark_stopped(
    *,
    now: datetime | None = None,
    db_engine=engine,
    process_instance_id: str | None = None,
) -> None:

    if not inspect(
        db_engine
    ).has_table(
        runtime_process_heartbeats.name
    ):
        return

    current = _utc(
        now or datetime.now(timezone.utc)
    )

    identity = str(
        process_instance_id
        or _INSTANCE_ID
    )[:128]

    with db_engine.begin() as conn:
        conn.execute(
            runtime_process_heartbeats
            .update()
            .where(
                runtime_process_heartbeats
                .c.instance_id
                == identity
            )
            .values(
                state="stopped",
                heartbeat_at=current,
                stopped_at=current,
            )
        )


def status(
    *,
    role: str | None = None,
    stale_after_seconds: int = 120,
    now: datetime | None = None,
    db_engine=engine,
) -> dict:

    ensure_table(db_engine)

    current = _utc(
        now or datetime.now(timezone.utc)
    )

    stale_seconds = max(
        30,
        int(stale_after_seconds),
    )

    cutoff = current - timedelta(
        seconds=stale_seconds
    )

    query = select(
        runtime_process_heartbeats
    )

    if role:
        query = query.where(
            runtime_process_heartbeats
            .c.role
            == str(role)
        )

    with db_engine.begin() as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                query
            ).mappings().all()
        ]

    for row in rows:
        row["started_at"] = _utc(
            row.get("started_at")
        )

        row["heartbeat_at"] = _utc(
            row.get("heartbeat_at")
        )

        row["stopped_at"] = _utc(
            row.get("stopped_at")
        )

    active = [
        row
        for row in rows
        if (
            row.get("state") == "running"
            and row.get("heartbeat_at")
            and row["heartbeat_at"] >= cutoff
        )
    ]

    latest = max(
        rows,
        key=lambda row: (
            row.get("heartbeat_at")
            or datetime.min.replace(
                tzinfo=timezone.utc
            )
        ),
        default=None,
    )

    latest_payload = None

    if latest:
        latest_payload = {
            "instance_id":
                latest.get("instance_id"),

            "role":
                latest.get("role"),

            "state":
                latest.get("state"),

            "started_at":
                (
                    latest["started_at"]
                    .isoformat()
                    if latest.get("started_at")
                    else None
                ),

            "heartbeat_at":
                (
                    latest["heartbeat_at"]
                    .isoformat()
                    if latest.get("heartbeat_at")
                    else None
                ),

            "stopped_at":
                (
                    latest["stopped_at"]
                    .isoformat()
                    if latest.get("stopped_at")
                    else None
                ),

            "ownership":
                json.loads(
                    latest.get(
                        "ownership_json"
                    )
                    or "{}"
                ),
        }

    return {
        "role":
            role,

        "active":
            bool(active),

        "active_count":
            len(active),

        "duplicate_active":
            len(active) > 1,

        "stale_after_seconds":
            stale_seconds,

        "latest":
            latest_payload,
    }
