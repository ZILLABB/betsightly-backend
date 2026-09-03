"""Append-only operational facts for slip-builder requests.

The browser reports intent and UX interactions. This table records what the
server actually produced, without storing a SportyBet code or model inputs.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, MetaData, String, Table, select

from database import engine

metadata = MetaData()
builder_runs = Table(
    "builder_runs", metadata,
    Column("request_id", String(36), primary_key=True),
    Column("requested_at", DateTime(timezone=True), nullable=False, index=True),
    Column("target_odds", Float, nullable=False),
    Column("horizon", String(16), nullable=False),
    Column("refresh", Boolean, nullable=False, default=False),
    Column("result_status", String(24), nullable=False),
    Column("leg_count", Integer),
    Column("generated_odds", Float),
    Column("ticket_produced", Boolean, nullable=False, default=False),
    Column("booking_status", String(32)),
    Column("actual_sportybet_odds", Float),
    Column("validation_status", String(32)),
    Column("failure_category", String(64)),
    Column("booking_variant_id", String(64)),
    Column("cached", Boolean, nullable=False, default=False),
)


def ensure_table() -> None:
    metadata.create_all(engine, tables=[builder_runs], checkfirst=True)


def _failure_category(result: dict) -> str | None:
    booking = result.get("booking") or {}
    status = str(booking.get("booking_status") or booking.get("status") or "").upper()
    if result.get("status") != "success":
        return str(result.get("status") or "generation_failed")[:64]
    if not booking.get("share_code"):
        return status or "NO_BOOKING_CODE"
    if str(booking.get("readback_validation") or "").upper() not in ("", "PASSED"):
        return "VALIDATION_FAILED"
    return None


def record_run(target: float, horizon: str, refresh: bool, result: dict,
               *, cached: bool = False, request_id: str | None = None) -> str:
    """Persist one request outcome. Raises only to its caller, which logs and continues."""
    ensure_table()
    booking = result.get("booking") or {}
    produced = bool(booking.get("status") == "active" and booking.get("share_code"))
    request_id = request_id or str(uuid.uuid4())
    row = {
        "request_id": request_id,
        "requested_at": datetime.now(timezone.utc),
        "target_odds": float(target), "horizon": str(horizon)[:16],
        "refresh": bool(refresh), "result_status": str(result.get("status") or "error")[:24],
        "leg_count": result.get("legs"), "generated_odds": result.get("odds"),
        "ticket_produced": produced,
        "booking_status": str(booking.get("booking_status") or booking.get("status") or "")[:32] or None,
        "actual_sportybet_odds": booking.get("actual_sportybet_odds"),
        "validation_status": str(booking.get("readback_validation") or "")[:32] or None,
        "failure_category": _failure_category(result),
        "booking_variant_id": str(booking.get("sportybet_selection_fingerprint") or
                                  booking.get("booking_variant_fingerprint") or "")[:64] or None,
        "cached": bool(cached),
    }
    with engine.begin() as conn:
        conn.execute(builder_runs.insert().values(**row))
    return request_id


def summary(start: str, end: str) -> dict:
    ensure_table()
    first = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    last = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    last = last.replace(hour=23, minute=59, second=59, microsecond=999999)
    with engine.begin() as conn:
        rows = conn.execute(select(builder_runs).where(
            builder_runs.c.requested_at >= first,
            builder_runs.c.requested_at <= last,
        )).mappings().all()
    targets, failures = defaultdict(Counter), Counter()
    for row in rows:
        key = str(int(row["target_odds"]) if float(row["target_odds"]).is_integer()
                  else row["target_odds"])
        targets[key]["requests"] += 1
        targets[key]["tickets"] += int(bool(row["ticket_produced"]))
        if row["failure_category"]:
            failures[row["failure_category"]] += 1
    produced = sum(bool(row["ticket_produced"]) for row in rows)
    return {
        "requests": len(rows), "tickets_produced": produced,
        "ticket_rate": round(produced / len(rows), 4) if rows else None,
        "cache_hits": sum(bool(row["cached"]) for row in rows),
        "by_target": [{"target": key, **dict(value)} for key, value in sorted(targets.items())],
        "failures": [{"category": key, "count": value} for key, value in failures.most_common()],
    }
