"""Admin-curated fallback for empty prediction tiers, kept separate from model history.

Editors choose real SportyBet event IDs and canonical markets. Nothing is
published until the full SportyBet share code is read back and verified.
This database is separate from published_slips to avoid corrupting official
model/calibration/ROI evidence. Existing auto tickets are never overwritten.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone
from math import prod

from sqlalchemy import text

LOG = logging.getLogger(__name__)
WAT = timezone(timedelta(hours=1))
TIERS = {"banker", "2_odds", "5_odds", "10_odds", "over_1_5"}
MAX_LEGS = {"banker": 1, "2_odds": 12, "5_odds": 20,
            "10_odds": 20, "over_1_5": 10}
MIN_ODDS = {"banker": 1.01, "2_odds": 2.0, "5_odds": 5.0,
            "10_odds": 10.0, "over_1_5": 1.01}

def _now():
    return datetime.now(timezone.utc)

def _today():
    return _now().astimezone(WAT).date().isoformat()

def _engine():
    from database import engine
    return engine

def _ensure(conn):
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS editorial_tier_slips (
            publish_date VARCHAR(10) NOT NULL,
            tier VARCHAR(24) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            detail TEXT NOT NULL,
            PRIMARY KEY (publish_date, tier)
        )
    """))

def parse_input(lines: str, tier: str) -> list[tuple[str, str]]:
    """Accepted lines: SportyBet event ID,canonical_market (also CSV files)."""
    from leagues.sportybet import MARKET_TO_SPORTYBET
    if tier not in TIERS:
        raise ValueError("Unknown prediction tier")
    results = []
    for n, line in enumerate(lines.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        columns = [value.strip().strip('"') for value in line.split(",")]
        if len(columns) != 2:
            raise ValueError(f"Row {n}: expected event_id,market")
        event, market = columns
        if event.lower() in {"event_id", "sportybet_event_id", "id"} and market.lower() == "market":
            continue
        if not event or len(event) > 60 or not event.isascii() or any(
                c not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ:-_"
                for c in event):
            raise ValueError(f"Row {n}: invalid SportyBet event ID")
        if market not in MARKET_TO_SPORTYBET:
            raise ValueError(f"Row {n}: {market!r} is not a mapped SportyBet market")
        if tier == "over_1_5" and market != "over_1_5":
            raise ValueError("Over 1.5 tier only accepts over_1_5")
        if (event, market) in results or any(e == event for e, _ in results):
            raise ValueError(f"Row {n}: fixture repeated in the same ticket")
        results.append((event, market))
    if not results or len(results) > MAX_LEGS[tier]:
        raise ValueError(f"Enter 1–{MAX_LEGS[tier]} distinct fixtures for {tier}")
    if tier == "banker" and len(results) != 1:
        raise ValueError("Banker requires exactly one selection")
    return results

def _current_bookable_games(requested: list[tuple[str, str]], board: dict,
                            *, now=None, date=None) -> list[dict]:
    """Resolve by exact SportyBet event IDs, not ambiguous team-name matching."""
    from leagues.sportybet import _board_entries, availability_for
    from leagues.market_registry import MARKETS

    at = now or _now()
    target = date or at.astimezone(WAT).date().isoformat()
    ids = {event for event, _ in requested}
    entries = {}
    for _, entry in _board_entries(board):
        key = str(entry.get("event_id") or "")
        if key in ids:
            if key in entries:
                raise ValueError(f"SportyBet event {key} appears more than once")
            entries[key] = entry
    games = []
    for event_id, market in requested:
        entry = entries.get(event_id)
        if not entry:
            raise ValueError(f"SportyBet event {event_id} not on the live board")
        kickoff_ms = entry.get("kickoff_ms")
        try:
            kickoff = datetime.fromtimestamp(float(kickoff_ms) / 1000, timezone.utc)
        except (TypeError, ValueError, OSError):
            raise ValueError(f"SportyBet event {event_id} has no valid kickoff")
        if kickoff <= at + timedelta(minutes=20):
            raise ValueError(f"SportyBet event {event_id} started or is too close to kickoff")
        if kickoff.astimezone(WAT).date().isoformat() != target:
            raise ValueError(f"SportyBet event {event_id} is not on {target} WAT")
        home, away = str(entry["home_team"]), str(entry["away_team"])
        league = str(entry.get("competition") or "Football")[:120]
        availability = availability_for(
            board, home, away, kickoff.isoformat(), league, market,
            event_id=event_id,
        )
        if not availability.get("sportybet_available"):
            raise ValueError(
                f"{event_id} {market}: {availability.get('failure_reason') or availability.get('status')}"
            )
        price = float(availability["sportybet_odds"])
        if not math.isfinite(price) or price <= 1:
            raise ValueError(f"{event_id}: invalid market price")
        spec = MARKETS.get(market)
        label = (spec.label if spec is not None else market)
        try:
            readable = label.format(home=home, away=away)
        except (ValueError, KeyError):
            readable = market.replace("_", " ").title()
        game = {
            "match_id": f"sportybet:{event_id}",
            "sportybet_event_id": event_id,
            "fixture_id": int(event_id) if event_id.isdigit() else 0,
            "selection_id": f"sportybet:{event_id}:{market}",
            "home_team": home, "away_team": away,
            "league": league, "kickoff": kickoff.isoformat(),
            "date": kickoff.isoformat(), "market": market,
            "prediction": readable,
            "prediction_type": getattr(spec, "group", "editorial"),
            "odds": price, "real_odds": price,
            "odds_are_real": True, "odds_provider": "SportyBet",
            "bookable": True, "bookmaker": "SportyBet",
            "sportybet_availability": availability,
            "editorial_manual": True,
            "model_probability_available": False,
            "model_sources": ["Admin curated · bookmaker verified"],
        }
        games.append(game)
    return games

def check_tier_target(tier: str, total_odds: float, count: int) -> None:
    if count > MAX_LEGS[tier]:
        raise ValueError("Too many selections for this tier")
    if total_odds + 1e-8 < MIN_ODDS[tier]:
        raise ValueError(
            f"{tier} must reach {MIN_ODDS[tier]:.2f}x verified odds, "
            f"current total is {total_odds:.2f}x"
        )

def _claimed_identifiers(card: dict, booking_rows: dict, manual_rows: dict,
                         *, exclude: str = "") -> set[str]:
    ids = set()
    for tier, data in (card or {}).items():
        if tier == exclude or not isinstance(data, dict) or not data.get("selected"):
            continue
        for g in data.get("games") or []:
            if g.get("sportybet_event_id"):
                ids.add(str(g["sportybet_event_id"]))
            if g.get("match_id"):
                ids.add(str(g["match_id"]))
    for tier, booking in (booking_rows or {}).items():
        if tier == exclude:
            continue
        for g in booking.get("final_booked_legs") or []:
            if g.get("sportybet_event_id"):
                ids.add(str(g["sportybet_event_id"]))
            if g.get("match_id"):
                ids.add(str(g["match_id"]))
    for tier, data in (manual_rows or {}).items():
        if tier == exclude:
            continue
        for g in data.get("games") or []:
            if g.get("sportybet_event_id"):
                ids.add(str(g["sportybet_event_id"]))
    return ids

def _check_exposure(games, card, booking_rows, manual_rows, *, tier):
    ids = _claimed_identifiers(card, booking_rows, manual_rows, exclude=tier)
    for game in games:
        if (str(game["sportybet_event_id"]) in ids
                or str(game["match_id"]) in ids):
            raise ValueError(
                f"{game['home_team']} vs {game['away_team']} is already used "
                "in a published BetSightly product"
            )

def list_published(date: str | None = None) -> dict[str, dict]:
    """No table creation in customer-facing read requests."""
    date = date or _today()
    try:
        with _engine().connect() as conn:
            rows = conn.execute(text(
                "SELECT tier, detail FROM editorial_tier_slips WHERE publish_date=:d"
            ), {"d": date}).all()
        return {tier: json.loads(detail) for tier, detail in rows}
    except Exception:
        return {}

def preview(tier: str, lines: str, *, board=None, now=None) -> dict:
    """Admin-only price preview. Never writes a card or creates a booking."""
    from leagues import sportybet
    from leagues.picks_db import load_card
    from leagues.booking import bookings_for

    at = now or _now()
    day = at.astimezone(WAT).date().isoformat()
    requested = parse_input(lines, tier)
    card = load_card(day) or {}
    if (card.get(tier) or {}).get("selected"):
        raise ValueError(f"{tier} already has an immutable official slip today")
    manual = list_published(day)
    if tier in manual:
        raise ValueError(f"{tier} already has a published manual slip")
    live_board = board if board is not None else sportybet.fetch_board(force=True)
    games = _current_bookable_games(requested, live_board, now=at, date=day)
    _check_exposure(games, card, bookings_for(day), manual, tier=tier)
    total = round(prod(g["odds"] for g in games), 3)
    check_tier_target(tier, total, len(games))
    return {
        "status": "PREVIEW", "date": day, "tier": tier,
        "games": games, "total_odds": total,
        "booking_code_created": False, "research_only": False,
        "editorial_manual": True,
    }

def publish(tier: str, lines: str) -> dict:
    """Full bookmaker readback first, then atomic one-way publication."""
    from leagues import sportybet
    from leagues.booking import create_booking, bookings_for
    from leagues.picks_db import load_card

    inspected = preview(tier, lines)
    day, games = inspected["date"], inspected["games"]
    board = sportybet.fetch_board(force=True)
    # Fresh booking-time repricing and kickoff validation.
    revised = _current_bookable_games(parse_input(lines, tier), board, date=day)
    _check_exposure(revised, load_card(day) or {}, bookings_for(day),
                    list_published(day), tier=tier)
    odds = round(prod(g["odds"] for g in revised), 3)
    check_tier_target(tier, odds, len(revised))
    booked = create_booking(
        revised, board, booking_status="FULL",
        original_games=revised, predicted_odds=odds,
        ticket_type="accumulator",
    )
    if (booked.get("status") != "active"
            or booked.get("booking_status") != "FULL"
            or booked.get("readback_validation") != "PASSED"
            or not booked.get("share_code")
            or len(booked.get("final_booked_legs") or []) != len(revised)):
        raise ValueError(
            "SportyBet did not return a verified full-match booking code; "
            "nothing has been published"
        )
    actual = float(booked.get("actual_sportybet_odds") or 0)
    check_tier_target(tier, actual, len(revised))
    payload = {
        "date": day, "tier": tier,
        "editorial_manual": True, "source": "admin_curated",
        "games": revised, "total_odds": actual,
        "booking": booked, "published_at": _now().isoformat(),
        "model_probability_available": False,
        "settlement_track": "editorial_separate",
    }
    with _engine().begin() as conn:
        _ensure(conn)
        # Serialize all manual publication for a day, guarding cross-tier
        # reuse even when admins submit in two tabs simultaneously.
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
                     {"k": f"editorial:{day}"})
        existing = conn.execute(text(
            "SELECT tier, detail FROM editorial_tier_slips WHERE publish_date=:d"
        ), {"d": day}).all()
        manual = {key: json.loads(value) for key, value in existing}
        if tier in manual:
            raise ValueError("This tier was published in another session")
        locked = conn.execute(text(
            "SELECT payload FROM daily_cards WHERE publish_date=:d"
        ), {"d": day}).scalar()
        card = json.loads(locked) if locked else {}
        if (card.get(tier) or {}).get("selected"):
            raise ValueError("This tier already has an immutable engine slip")
        # Every originally verified booking keeps its fixture reservation.
        _check_exposure(revised, card, bookings_for(day), manual, tier=tier)
        conn.execute(text(
            "INSERT INTO editorial_tier_slips"
            " (publish_date,tier,created_at,detail)"
            " VALUES (:d,:t,:at,:detail)"
        ), {"d": day, "t": tier, "at": _now(),
            "detail": json.dumps(payload)})
    # Clear any in-process day cache; locked reads also have a short TTL.
    from leagues import daily_feed
    daily_feed._accum_cache.update({"result": None, "ts": 0})
    return {
        "status": "PUBLISHED", "date": day, "tier": tier,
        "total_odds": actual, "leg_count": len(revised),
        "share_code": booked["share_code"],
        "editorial_manual": True, "official_engine_record_unchanged": True,
    }

def overlay_on_card(date: str, accumulators: dict) -> dict:
    """Only populate genuinely empty tiers; never rewrite an automated slip."""
    merged = dict(accumulators)
    from leagues.booking import booking_lifecycle
    for tier, record in list_published(date).items():
        if tier not in TIERS or (merged.get(tier) or {}).get("selected"):
            continue
        games = record["games"]
        booking = booking_lifecycle(record["booking"], games)
        merged[tier] = {
            "selected": True,
            "games": games,
            "total_odds": record["total_odds"],
            "hit_probability": None,
            "reason": "Admin-curated selection; statistical confidence not evaluated",
            "presentation": "accumulator",
            "sportybet_ticket_type": "accumulator",
            "editorial_manual": True,
            "source": "admin_curated",
            "booking": booking,
            "booking_code": (booking or {}).get("share_code"),
            "risk_level": "Unscored editorial accumulator",
        }
    return merged
