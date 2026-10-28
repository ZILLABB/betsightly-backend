"""First-write-wins Jev shadow snapshots, independent from official publication.

Use only in an explicitly enabled worker. Database table is not created on
module import, on public HTTP requests, or if a provider key is missing.
Insert a claim BEFORE paying for a Jev request; no second request for a held
same-fingerprint snapshot after restarts or concurrent worker claims.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import uuid
from typing import Any

from sqlalchemy import (
    Column, DateTime, MetaData, String, Table, Text, inspect,
    select, update, func,
)
from sqlalchemy.exc import IntegrityError

from leagues.jev_evidence_contract import _utc, JEV_MODEL_ID

METADATA = MetaData()
AUDITS = Table(
    "jev_shadow_evidence_audits", METADATA,
    Column("audit_id", String(36), primary_key=True),
    Column("audit_key", String(64), nullable=False, unique=True),
    Column("model_version", String(96), nullable=False),
    Column("sport", String(24), nullable=False),
    Column("fixture_id", String(128), nullable=False),
    Column("market", String(80), nullable=False),
    Column("kickoff_utc", DateTime(timezone=True), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("state_fingerprint", String(64), nullable=False),
    Column("status", String(40), nullable=False),
    Column("evidence_json", Text, nullable=False),
    Column("decision_json", Text, nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
)


def _engine():
    from database import engine
    return engine


def table_exists(db_engine=None) -> bool:
    db_engine = db_engine if db_engine is not None else _engine()
    return inspect(db_engine).has_table(AUDITS.name)


def _key(envelope) -> str:
    return sha256((JEV_MODEL_ID + "|" + envelope["state_fingerprint"]).encode()).hexdigest()


def claim(envelope: dict, *, db_engine=None) -> dict[str, Any]:
    """One immutable pregame state claim: no endpoint or production pick edits."""
    if (not isinstance(envelope, dict)
            or envelope.get("status") != "ready_for_shadow_review"
            or envelope.get("shadow_only") is not True
            or envelope.get("publication_authority") is not False):
        return {"status": "ineligible", "claimed": False}
    state = envelope.get("state") or {}
    selection = state.get("selection") or {}
    observed = _utc(state.get("as_of"))
    kickoff = _utc(selection.get("kickoff_utc"))
    fixture = str(selection.get("fixture_id") or "")
    market = str(selection.get("market") or "")
    if (not observed or not kickoff or observed >= kickoff
            or not fixture or not market
            or not envelope.get("state_fingerprint")
            or state.get("sport") not in {"football", "basketball"}):
        return {"status": "invalid_or_post_kickoff", "claimed": False}
    key = _key(envelope)
    db_engine = db_engine if db_engine is not None else _engine()
    # Table must be initialized by an authorized worker, never a browser GET.
    METADATA.create_all(db_engine, tables=[AUDITS], checkfirst=True)
    row = {
        "audit_id": str(uuid.uuid4()), "audit_key": key,
        "model_version": JEV_MODEL_ID,
        "sport": state["sport"], "fixture_id": fixture,
        "market": market, "kickoff_utc": kickoff,
        "observed_at": observed, "state_fingerprint": envelope["state_fingerprint"],
        "status": "claimed",
        "evidence_json": json.dumps(state, sort_keys=True, default=str),
        "decision_json": None,
    }
    try:
        with db_engine.begin() as con:
            con.execute(AUDITS.insert().values(**row))
        return {"status": "claimed", "claimed": True, "audit_key": key}
    except IntegrityError:
        return {"status": "already_claimed", "claimed": False,
                "audit_key": key}


def complete(audit_key: str, result: dict, *, db_engine=None) -> dict:
    if (not isinstance(result, dict)
            or result.get("publication_authority") is not False
            or result.get("shadow_only") is not True):
        return {"status": "invalid_result", "updated": False}
    if not isinstance(audit_key, str) or len(audit_key) != 64:
        return {"status": "invalid_key", "updated": False}
    db_engine = db_engine if db_engine is not None else _engine()
    now = datetime.now(timezone.utc)
    reduced = {
        "status": str(result.get("status") or "unavailable")[:40],
        "evidence_state": result.get("evidence_state"),
        "requires_human_review_probability": result.get(
            "requires_human_review_probability"),
        "classification_confidence": result.get("classification_confidence"),
        "reason": result.get("reason"),
    }
    with db_engine.begin() as con:
        updated = con.execute(
            update(AUDITS).where(
                AUDITS.c.audit_key == audit_key,
                AUDITS.c.status == "claimed",
            ).values(status=reduced["status"],
                     decision_json=json.dumps(reduced, default=str),
                     completed_at=now)
        ).rowcount
    return {"status": "completed" if updated else "unchanged",
            "updated": bool(updated)}


def summary(*, db_engine=None) -> dict:
    """Safe diagnostics only; never expose source text or provider credentials."""
    db_engine = db_engine if db_engine is not None else _engine()
    if not table_exists(db_engine):
        return {"status": "not_initialized", "total": 0,
                "publication_authority": False}
    with db_engine.connect() as con:
        counts = con.execute(
            select(AUDITS.c.status, func.count()).group_by(AUDITS.c.status)
        ).all()
        by_sport = con.execute(
            select(AUDITS.c.sport, func.count()).group_by(AUDITS.c.sport)
        ).all()
    return {"status": "ok", "total": sum(n for _, n in counts),
            "by_status": {name: n for name, n in counts},
            "by_sport": {sport: n for sport, n in by_sport},
            "publication_authority": False}
