"""Immutable, optimistic-concurrency history for interactive Builder edits."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, Float, Integer, MetaData, PrimaryKeyConstraint, String,
    Table, Text, UniqueConstraint, select,
)

from database import engine
from leagues.booking import leg_fingerprint

metadata = MetaData()

builder_revision_runs = Table(
    "builder_revision_runs", metadata,
    Column("run_id", String(36), primary_key=True),
    Column("edit_token_hash", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("requested_target", Float, nullable=False),
    Column("horizon", String(16), nullable=False),
    Column("latest_revision", Integer, nullable=False),
)

builder_revisions = Table(
    "builder_revisions", metadata,
    Column("run_id", String(36), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("parent_revision", Integer),
    Column("request_id", String(64), nullable=False),
    Column("action", String(40), nullable=False),
    Column("action_target", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("selected_fingerprint", String(64)),
    Column("locked_selection_ids", Text, nullable=False),
    Column("excluded_fixture_ids", Text, nullable=False),
    Column("excluded_selection_ids", Text, nullable=False),
    Column("result_payload", Text, nullable=False),
    PrimaryKeyConstraint("run_id", "revision"),
    UniqueConstraint("run_id", "request_id", name="uq_builder_revision_request"),
)

builder_revision_bookings = Table(
    "builder_revision_bookings", metadata,
    Column("run_id", String(36), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("selected_fingerprint", String(64)),
    Column("status", String(24), nullable=False),
    Column("booking_detail", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("superseded_at", DateTime(timezone=True)),
    PrimaryKeyConstraint("run_id", "revision"),
)


class BuilderRunNotFound(Exception):
    pass


class BuilderRunForbidden(Exception):
    pass


class StaleBuilderRevision(Exception):
    def __init__(self, latest_revision: int):
        super().__init__("stale_revision")
        self.latest_revision = latest_revision


def ensure_tables() -> None:
    metadata.create_all(
        engine,
        tables=[builder_revision_runs, builder_revisions,
                builder_revision_bookings],
        checkfirst=True,
    )


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _dump(value) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def _loads(value: str | None, fallback):
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError):
        return fallback


def _fingerprint(result: dict) -> str | None:
    games = result.get("games") or []
    return leg_fingerprint(games) if games else None


def _booking_status(result: dict) -> str:
    booking = result.get("booking") or {}
    if booking.get("status") == "active" and booking.get("share_code"):
        return "active"
    return str(booking.get("status") or "unavailable")[:24]


def _decorate(result: dict, *, run_id: str, revision: int,
              parent_revision: int | None, edit_token: str | None,
              locked: set[str], excluded_fixtures: set[str],
              excluded_selections: set[str]) -> dict:
    public = dict(result)
    public.update({
        "builder_run_id": run_id,
        "revision": revision,
        "parent_revision": parent_revision,
        "locked_selection_ids": sorted(locked),
        "excluded_fixture_ids": sorted(excluded_fixtures),
        "excluded_selection_ids": sorted(excluded_selections),
    })
    if edit_token:
        public["edit_token"] = edit_token
    return public


def create_initial_run(target: float, horizon: str, result: dict) -> dict:
    """Create a user-owned revision chain for one generated slip response."""
    ensure_tables()
    run_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    stored = _decorate(
        result, run_id=run_id, revision=1, parent_revision=None,
        edit_token=None, locked=set(), excluded_fixtures=set(),
        excluded_selections=set(),
    )
    fingerprint = _fingerprint(result)
    with engine.begin() as conn:
        conn.execute(builder_revision_runs.insert().values(
            run_id=run_id, edit_token_hash=_token_hash(token),
            created_at=now, updated_at=now, requested_target=float(target),
            horizon=str(horizon)[:16], latest_revision=1,
        ))
        conn.execute(builder_revisions.insert().values(
            run_id=run_id, revision=1, parent_revision=None,
            request_id=f"initial:{run_id}", action="generate",
            action_target=None, created_at=now,
            selected_fingerprint=fingerprint,
            locked_selection_ids="[]", excluded_fixture_ids="[]",
            excluded_selection_ids="[]", result_payload=_dump(stored),
        ))
        conn.execute(builder_revision_bookings.insert().values(
            run_id=run_id, revision=1, selected_fingerprint=fingerprint,
            status=_booking_status(result),
            booking_detail=_dump(result.get("booking") or {}), created_at=now,
        ))
    return _decorate(
        result, run_id=run_id, revision=1, parent_revision=None,
        edit_token=token, locked=set(), excluded_fixtures=set(),
        excluded_selections=set(),
    )


def load_state(run_id: str, edit_token: str) -> dict:
    ensure_tables()
    with engine.begin() as conn:
        run = conn.execute(select(builder_revision_runs).where(
            builder_revision_runs.c.run_id == run_id
        )).mappings().first()
        if not run:
            raise BuilderRunNotFound(run_id)
        if not hmac.compare_digest(run["edit_token_hash"], _token_hash(edit_token)):
            raise BuilderRunForbidden(run_id)
        row = conn.execute(select(builder_revisions).where(
            builder_revisions.c.run_id == run_id,
            builder_revisions.c.revision == run["latest_revision"],
        )).mappings().one()
    return {
        "run_id": run_id,
        "requested_target": float(run["requested_target"]),
        "horizon": run["horizon"],
        "latest_revision": int(run["latest_revision"]),
        "result": _loads(row["result_payload"], {}),
        "locked_selection_ids": set(_loads(row["locked_selection_ids"], [])),
        "excluded_fixture_ids": set(_loads(row["excluded_fixture_ids"], [])),
        "excluded_selection_ids": set(_loads(row["excluded_selection_ids"], [])),
    }


def idempotent_result(run_id: str, edit_token: str, request_id: str) -> dict | None:
    state = load_state(run_id, edit_token)
    with engine.begin() as conn:
        row = conn.execute(select(builder_revisions).where(
            builder_revisions.c.run_id == run_id,
            builder_revisions.c.request_id == request_id,
        )).mappings().first()
    if not row:
        return None
    result = _loads(row["result_payload"], {})
    result["edit_token"] = edit_token
    result["idempotent_replay"] = True
    result["latest_revision"] = state["latest_revision"]
    return result


def persist_revision(
    *, run_id: str, edit_token: str, expected_revision: int,
    request_id: str, action: str, action_target: dict | None,
    result: dict, locked_selection_ids: set[str],
    excluded_fixture_ids: set[str], excluded_selection_ids: set[str],
) -> dict:
    """Append exactly one revision, rejecting obsolete writers."""
    ensure_tables()
    now = datetime.now(timezone.utc)
    new_revision = expected_revision + 1
    fingerprint = _fingerprint(result)
    stored = _decorate(
        result, run_id=run_id, revision=new_revision,
        parent_revision=expected_revision, edit_token=None,
        locked=locked_selection_ids, excluded_fixtures=excluded_fixture_ids,
        excluded_selections=excluded_selection_ids,
    )
    with engine.begin() as conn:
        run = conn.execute(select(builder_revision_runs).where(
            builder_revision_runs.c.run_id == run_id
        )).mappings().first()
        if not run:
            raise BuilderRunNotFound(run_id)
        if not hmac.compare_digest(run["edit_token_hash"], _token_hash(edit_token)):
            raise BuilderRunForbidden(run_id)
        latest = int(run["latest_revision"])
        if latest != expected_revision:
            raise StaleBuilderRevision(latest)
        conn.execute(builder_revisions.insert().values(
            run_id=run_id, revision=new_revision,
            parent_revision=expected_revision, request_id=request_id,
            action=str(action)[:40], action_target=_dump(action_target or {}),
            created_at=now, selected_fingerprint=fingerprint,
            locked_selection_ids=_dump(sorted(locked_selection_ids)),
            excluded_fixture_ids=_dump(sorted(excluded_fixture_ids)),
            excluded_selection_ids=_dump(sorted(excluded_selection_ids)),
            result_payload=_dump(stored),
        ))
        prior_booking = conn.execute(select(builder_revision_bookings).where(
            builder_revision_bookings.c.run_id == run_id,
            builder_revision_bookings.c.revision == expected_revision,
        )).mappings().first()
        prior_fingerprint = (prior_booking or {}).get("selected_fingerprint")
        if prior_fingerprint != fingerprint:
            conn.execute(builder_revision_bookings.update().where(
                builder_revision_bookings.c.run_id == run_id,
                builder_revision_bookings.c.status == "active",
            ).values(status="superseded", superseded_at=now))
        else:
            conn.execute(builder_revision_bookings.update().where(
                builder_revision_bookings.c.run_id == run_id,
                builder_revision_bookings.c.status == "active",
            ).values(status="carried_forward", superseded_at=now))
        conn.execute(builder_revision_bookings.insert().values(
            run_id=run_id, revision=new_revision,
            selected_fingerprint=fingerprint, status=_booking_status(result),
            booking_detail=_dump(result.get("booking") or {}), created_at=now,
        ))
        updated = conn.execute(builder_revision_runs.update().where(
            builder_revision_runs.c.run_id == run_id,
            builder_revision_runs.c.latest_revision == expected_revision,
        ).values(latest_revision=new_revision, updated_at=now))
        if updated.rowcount != 1:
            raise StaleBuilderRevision(latest)
    return _decorate(
        result, run_id=run_id, revision=new_revision,
        parent_revision=expected_revision, edit_token=edit_token,
        locked=locked_selection_ids, excluded_fixtures=excluded_fixture_ids,
        excluded_selections=excluded_selection_ids,
    )
