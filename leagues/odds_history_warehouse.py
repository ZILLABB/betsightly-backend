"""Phase 9: append-only SportyBet odds warehouse, without fabricated CLV.

A booked ticket is NOT a closing line. The quoted price is observed at
booking time; CLV stays unavailable until an independently verified,
same-event, same-market, same-bookmaker closing observation is captured.
This module stores only sportsbook fixture prices, never bettor activity.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import math
from typing import Any

from sqlalchemy import (Column, DateTime, Float, MetaData, String, Table,
                        func, insert, select, text)

from database import engine

_METADATA = MetaData()
_TABLE = Table(
    "sportsbook_price_observations", _METADATA,
    Column("observation_id", String(64), primary_key=True),
    Column("publish_date", String(10), nullable=False, index=True),
    Column("tier", String(24), nullable=False),
    Column("fixture_id", String(120), nullable=False, index=True),
    Column("event_id", String(120)),
    Column("market", String(40), nullable=False),
    Column("price", Float, nullable=False),
    Column("phase", String(24), nullable=False),
    Column("provider", String(32), nullable=False),
    Column("snapshot_id", String(120)),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("kickoff_at", DateTime(timezone=True), nullable=False),
)


def ensure_tables() -> None:
    _METADATA.create_all(engine, tables=[_TABLE], checkfirst=True)


def _date(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and "T" in value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else (
        parsed.astimezone(timezone.utc)
    )


def _price(value):
    try:
        v = float(value)
        return v if math.isfinite(v) and 1.0 < v < 1000 else None
    except (TypeError, ValueError, OverflowError):
        return None


def prepare_booked_quotes(publish_date: str, tier: str,
                          record: dict, captured_at=None) -> list[dict]:
    """Only original real-priced bookmaker legs, from validated whole readback.

    Partial accumulator codes and price-model guesses are excluded.
    An Over1.5 partial singles booking may carry independently valid legs.
    """
    status = str(record.get("booking_status") or "").upper()
    if (record.get("status") != "active"
            or record.get("readback_validation") != "PASSED"
            or status not in {"FULL", "REBUILT_FULL", "PARTIAL"}
            or status == "PARTIAL" and tier != "over_1_5"):
        return []
    observed = _date(captured_at or record.get("priced_at")) or datetime.now(timezone.utc)
    snapshot_id = str(record.get("board_snapshot_id") or "")
    result = []
    for leg in record.get("final_booked_legs") or []:
        price = _price(leg.get("odds"))
        kickoff = _date(leg.get("kickoff") or leg.get("commence_time"))
        fixture_id = str(leg.get("match_id") or leg.get("fixture_id") or "")
        market = str(leg.get("market") or leg.get("market_key") or "")
        if (price is None or leg.get("odds_are_real") is not True
                or kickoff is None or kickoff <= observed
                or not fixture_id or not market):
            continue
        event_id = str(
            leg.get("sportybet_event_id")
            or (leg.get("sportybet_availability") or {}).get("event_id")
            or ""
        )
        # Snapshot identity is stable across retries; without one, bucket
        # per minute and actual price to avoid unbounded duplicate writes.
        identity = "|".join((
            publish_date, tier, fixture_id, event_id, market, snapshot_id,
            str(price), observed.strftime("%Y-%m-%dT%H:%M"),
        ))
        result.append({
            "observation_id": hashlib.sha256(identity.encode()).hexdigest(),
            "publish_date": publish_date,
            "tier": tier,
            "fixture_id": fixture_id,
            "event_id": event_id or None,
            "market": market,
            "price": price,
            "phase": "BOOKED_PRICE",
            "provider": "SportyBet",
            "snapshot_id": snapshot_id or None,
            "observed_at": observed,
            "kickoff_at": kickoff,
        })
    return result


def capture_validated_booking(publish_date: str, tier: str,
                              record: dict) -> int:
    """Write after booking persistence; never alter the locked prediction."""
    rows = prepare_booked_quotes(publish_date, tier, record)
    if not rows:
        return 0
    ensure_tables()
    with engine.begin() as conn:
        for row in rows:
            conn.execute(text(
                "INSERT INTO sportsbook_price_observations "
                "(observation_id,publish_date,tier,fixture_id,event_id,market,"
                "price,phase,provider,snapshot_id,observed_at,kickoff_at) "
                "VALUES (:observation_id,:publish_date,:tier,:fixture_id,"
                ":event_id,:market,:price,:phase,:provider,:snapshot_id,"
                ":observed_at,:kickoff_at) "
                "ON CONFLICT (observation_id) DO NOTHING"
            ), row)
    return len(rows)


def clv_comparison(booked: dict | None,
                   closing: dict | None) -> dict[str, Any]:
    """Bookmaker-price CLV is impossible without a verified closing quote."""
    if not booked or booked.get("phase") != "BOOKED_PRICE":
        return {"status": "MISSING_BOOKED_PRICE", "clv": None}
    if not closing or closing.get("phase") != "VERIFIED_CLOSING":
        return {"status": "MISSING_VERIFIED_CLOSING", "clv": None}
    same = all(
        str(booked.get(field) or "") == str(closing.get(field) or "")
        for field in ("fixture_id", "market", "provider")
    )
    if (not same or (booked.get("event_id") and closing.get("event_id")
                     and str(booked["event_id"]) != str(closing["event_id"]))):
        return {"status": "QUOTE_IDENTITY_MISMATCH", "clv": None}
    a, b = _price(booked.get("price")), _price(closing.get("price"))
    btime, ctime, kickoff = (
        _date(booked.get("observed_at")),
        _date(closing.get("observed_at")),
        _date(booked.get("kickoff_at")),
    )
    if (not a or not b or not btime or not ctime or not kickoff
            or not btime < ctime < kickoff):
        return {"status": "INVALID_PRICE_CHRONOLOGY", "clv": None}
    return {
        "status": "VERIFIED_CLOSING_AVAILABLE",
        "clv": round(a / b - 1.0, 6),
        "booked_odds": a,
        "closing_odds": b,
        "basis": "booked_odds / verified_closing_odds - 1",
    }


def warehouse_status() -> dict:
    """Admin-only monitoring. No user wagers, no inferred closing prices."""
    ensure_tables()
    with engine.connect() as conn:
        rows = conn.execute(
            select(_TABLE.c.phase, func.count()).group_by(_TABLE.c.phase)
        ).all()
    counts = {str(phase): int(n) for phase, n in rows}
    return {
        "status": "success", "shadow_only": True,
        "rows_by_phase": counts,
        "clv_ready": bool(counts.get("BOOKED_PRICE")
                          and counts.get("VERIFIED_CLOSING")),
        "closing_capture_implemented": False,
        "warning": "Booking prices are not closing lines; never report CLV "
                   "until verified near-kickoff closing observations exist.",
    }
