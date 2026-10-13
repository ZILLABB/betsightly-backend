"""Admin-controlled manual football picks, completely separate from model-record slips.

A curator may publish labelled research or request an exact SportyBet code.
Research is NEVER represented as bookmaker-verified. Booking requires ALL legs
to be active and a full code read-back. Official daily slips remain immutable.
"""
from __future__ import annotations

import json
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from math import prod

from sqlalchemy import (
    Column, DateTime, MetaData, String, Table, Text, UniqueConstraint,
    select, desc,
)

WAT = timezone(timedelta(hours=1))
METADATA = MetaData()
TABLE = Table(
    "manual_editorial_slips", METADATA,
    Column("slip_id", String(36), primary_key=True),
    Column("publish_date", String(10), nullable=False, index=True),
    Column("tier", String(20), nullable=False),
    Column("status", String(30), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("payload", Text, nullable=False),
    UniqueConstraint("publish_date", "tier", name="manual_editorial_day_tier"),
)
TIERS = {"banker": (1, 1, 1.0), "2_odds": (1, 12, 2.0),
         "5_odds": (2, 20, 5.0), "10_odds": (2, 20, 10.0),
         "over_1_5": (1, 20, 1.0)}
FIELD_LIMITS = {"home_team": 100, "away_team": 100, "league": 120}

def _db():
    from database import engine
    return engine

def _day(now=None):
    return (now or datetime.now(timezone.utc)).astimezone(WAT).date().isoformat()

def _parse_iso(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return None
        return stamp.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None

def normalise(payload: dict, now=None) -> dict:
    """Deterministic, admin-only parser. Never trusts a submitted probability."""
    current = now or datetime.now(timezone.utc)
    day = _day(current)
    if not isinstance(payload, dict):
        raise ValueError("The request must be a JSON object")
    tier = str(payload.get("tier") or "").strip()
    if tier not in TIERS:
        raise ValueError("Choose a valid tier, excluding Rollover")
    if payload.get("date") not in (None, "", day):
        raise ValueError("Manual desk only publishes today's remaining games")
    legs = payload.get("legs") or []
    if not isinstance(legs, list):
        raise ValueError("legs must be an array")
    minimum, maximum, target = TIERS[tier]
    if not minimum <= len(legs) <= maximum:
        raise ValueError(f"{tier} requires {minimum}-{maximum} selections")
    from leagues.sportybet import MARKET_TO_SPORTYBET
    result, ids = [], set()
    for i, entry in enumerate(legs):
        if not isinstance(entry, dict):
            raise ValueError(f"Selection {i + 1} must be an object")
        names = {}
        for field, limit in FIELD_LIMITS.items():
            value = str(entry.get(field) or "").strip()
            if not value or len(value) > limit or any(ord(c) < 32 for c in value):
                raise ValueError(f"Selection {i + 1}: valid {field} required")
            names[field] = value
        market = str(entry.get("market") or "").strip()
        if market not in MARKET_TO_SPORTYBET:
            raise ValueError(f"Selection {i + 1}: unsupported SportyBet market")
        if tier == "over_1_5" and market != "over_1_5":
            raise ValueError("Over 1.5 tier accepts only over_1_5 selections")
        event_id = str(entry.get("sportybet_event_id") or "").strip()
        if event_id and not re.fullmatch(r"[A-Za-z0-9_-]{3,64}", event_id):
            raise ValueError(f"Selection {i + 1}: invalid SportyBet match ID")
        fixture_id = str(entry.get("match_id") or "").strip()
        if not event_id and not fixture_id:
            raise ValueError(f"Selection {i + 1}: a fixture or SportyBet ID is required")
        kickoff = _parse_iso(entry.get("kickoff"))
        if kickoff is None or kickoff < current + timedelta(minutes=20):
            raise ValueError(f"Selection {i + 1}: kickoff has passed or is too close")
        if _day(kickoff) != day:
            raise ValueError(f"Selection {i + 1}: kickoff must be today (WAT)")
        identity = event_id or (
            names["home_team"].casefold(), names["away_team"].casefold()
        )
        if identity in ids:
            raise ValueError("A fixture cannot appear more than once in a slip")
        ids.add(identity)
        result.append({
            **names, "market": market,
            "prediction": market.replace("_", " ").title(),
            "sportybet_event_id": event_id or None,
            "match_id": fixture_id or event_id,
            "kickoff": kickoff.isoformat(),
            "date": kickoff.isoformat(),
            "source": "ADMIN_MANUAL",
            "bookable": False,
        })
    note = str(payload.get("note") or "").strip()[:500]
    return {"date": day, "tier": tier, "legs": result, "note": note,
            "target_odds": target}

def _official_keys(day: str) -> set:
    from leagues.daily_feed import build_daily_accumulators
    card = build_daily_accumulators(allow_generation=False) or {}
    keys = set()
    if card.get("date") != day:
        return keys
    for tier, info in (card.get("accumulators") or {}).items():
        if tier.startswith("_") or not isinstance(info, dict):
            continue
        if info.get("selected") is False:
            continue
        for game in info.get("games") or []:
            sporty_id = game.get("sportybet_event_id") or (
                game.get("sportybet_availability") or {}
            ).get("event_id")
            if sporty_id:
                keys.add(("id", str(sporty_id)))
            keys.add(("teams", str(game.get("home_team") or "").lower().strip(),
                      str(game.get("away_team") or "").lower().strip()))
    return keys

def _selection_keys(legs: list[dict]) -> set:
    result = set()
    for game in legs:
        if game.get("sportybet_event_id"):
            result.add(("id", str(game["sportybet_event_id"])))
        result.add(("teams", str(game.get("home_team") or "").lower().strip(),
                    str(game.get("away_team") or "").lower().strip()))
    return result

def public_slips(date: str | None = None) -> dict:
    """Read-only; does not create schema, publish or call a bookmaker."""
    target = date or _day()
    try:
        with _db().connect() as connection:
            rows = connection.execute(select(TABLE.c.payload).where(
                TABLE.c.publish_date == target
            ).order_by(TABLE.c.created_at.desc())).scalars().all()
        slips = []
        from leagues.booking import booking_lifecycle
        for raw in rows:
            slip = json.loads(raw)
            if slip.get("booking"):
                safe = booking_lifecycle(slip["booking"], slip["legs"])
                slip["booking"] = (safe if safe and safe.get("actionable")
                                   else None)
            slips.append(slip)
        return {"date": target, "status": "success", "slips": slips,
                "manual_editorial": True}
    except Exception:
        return {"date": target, "status": "not_available", "slips": [],
                "manual_editorial": True}

def preview(payload: dict) -> dict:
    validated = normalise(payload)
    return {
        **validated, "status": "PREVIEW", "manually_curated": True,
        "official_model_record_unchanged": True,
        "booking_verified": False,
        "warning": ("The submission is a human editorial opinion, not a "
                    "statistically validated BetSightly model ticket. "
                    "No code will appear without a FULL bookmaker readback."),
    }

def publish(payload: dict) -> dict:
    """Only an authenticated admin route calls this mutation."""
    from leagues import sportybet
    from leagues.booking import create_booking
    request = normalise(payload)
    book = payload.get("mode") == "book"
    if payload.get("mode") not in {"research", "book"}:
        raise ValueError("Choose research or book mode")
    date, tier = request["date"], request["tier"]
    engine = _db()
    METADATA.create_all(engine, tables=[TABLE], checkfirst=True)
    with engine.connect() as conn:
        existing = conn.execute(select(TABLE.c.slip_id).where(
            TABLE.c.publish_date == date, TABLE.c.tier == tier,
        )).first()
    if existing:
        raise ValueError("This manual tier is already published today; it cannot be overwritten")

    other = public_slips(date).get("slips") or []
    claimed = _official_keys(date)
    for item in other:
        claimed |= _selection_keys(item.get("legs") or [])
    if _selection_keys(request["legs"]) & claimed:
        raise ValueError("At least one match is already used by another published tier")

    booking = None
    chosen = request["legs"]
    if book:
        board = sportybet.fetch_board(force=True)
        if not board:
            raise ValueError("SportyBet board unavailable: nothing was published")
        from leagues.booking import _revalidate_games
        chosen, excluded = _revalidate_games(chosen, board)
        if excluded or len(chosen) != len(request["legs"]):
            raise ValueError("Every manual leg must match an active, exact SportyBet market")
        booking = create_booking(chosen, board, booking_status="FULL",
                                 original_games=chosen,
                                 ticket_type="accumulator")
        if (booking.get("status") != "active"
                or booking.get("booking_status") != "FULL"
                or booking.get("readback_validation") != "PASSED"
                or not booking.get("share_code")):
            raise ValueError("SportyBet did not verify the full ticket; nothing published")
        actual = float(booking.get("actual_sportybet_odds") or 0)
        if not math.isfinite(actual) or actual < request["target_odds"]:
            raise ValueError("Read-back ticket odds are below the selected tier target")
    if book:
        for leg in chosen:
            leg["bookable"] = True
            leg["odds_are_real"] = True
    slip = {
        "slip_id": str(uuid.uuid4()), "date": date,
        "tier": tier, "status": "BOOKED" if book else "RESEARCH",
        "legs": chosen, "note": request["note"],
        "booking": booking, "actual_odds": (
            booking.get("actual_sportybet_odds") if booking else None),
        "manual_editorial": True, "not_model_verified": True,
        "official_record_unchanged": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with engine.begin() as conn:
        conn.execute(TABLE.insert().values(
            slip_id=slip["slip_id"], publish_date=date,
            tier=tier, status=slip["status"],
            created_at=datetime.now(timezone.utc),
            payload=json.dumps(slip, default=str),
        ))
    return {**slip, "booking": {
        "status": booking.get("status"), "readback_validation": booking.get(
            "readback_validation"), "share_code": booking.get("share_code"),
        "share_url": booking.get("share_url"),
    } if booking else None}
