"""Anonymous Builder ticket history for future repeat/exposure controls."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, MetaData, String, Table, Text, UniqueConstraint, select

from database import engine

metadata = MetaData()
ticket_history = Table("user_ticket_history", metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(128), nullable=True, index=True),
    Column("anonymous_id", String(128), nullable=True, index=True),
    Column("builder_request_id", String(64), nullable=False),
    Column("ticket_fingerprint", String(64), nullable=False, index=True),
    Column("mode", String(24), nullable=False), Column("horizon", String(16), nullable=False),
    Column("requested_target_odds", Float), Column("requested_game_count", Integer),
    Column("generated_odds", Float), Column("booking_status", String(32)),
    Column("validation_status", String(32)), Column("board_snapshot_id", String(128)),
    Column("generated", Boolean, nullable=False, default=True),
    Column("booking_validated", Boolean, nullable=False, default=False),
    Column("copied_at", DateTime(timezone=True)), Column("played_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
    Column("expires_at", DateTime(timezone=True)), Column("metadata_json", Text),
    UniqueConstraint("anonymous_id", "ticket_fingerprint", name="uq_ticket_history_anonymous_fingerprint"),
)
ticket_selections = Table("user_ticket_selections", metadata,
    Column("id", String(36), primary_key=True), Column("ticket_id", String(36), ForeignKey("user_ticket_history.id"), nullable=False, index=True),
    Column("selection_fingerprint", String(128), nullable=False), Column("fixture_id", String(128)),
    Column("home_team", String(255)), Column("away_team", String(255)), Column("league", String(255)),
    Column("market", String(64)), Column("prediction", String(255)), Column("odds", Float),
    Column("confidence", Float), Column("evidence_probability", Float), Column("trust_grade", String(8)),
    Column("kickoff", DateTime(timezone=True)), Column("created_at", DateTime(timezone=True), nullable=False),
)

def ensure_tables(): metadata.create_all(engine, tables=[ticket_history, ticket_selections], checkfirst=True)

RECENT_EXPOSURE_DAYS = 7
RECENT_FIXTURE_DAYS = 3


def _normalise_key(value) -> str:
    return str(value or "").strip().casefold()


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def recent_exposure(
    anonymous_id: str | None,
    *,
    now: datetime | None = None,
) -> dict:
    """Return bounded recent Builder exposure for one anonymous user.

    This is diversification context only. It never changes prediction
    probabilities, trust grades, market policy, or bookability.
    """
    empty = {
        "window_days": RECENT_EXPOSURE_DAYS,
        "fixture_window_days": RECENT_FIXTURE_DAYS,
        "history_ticket_count": 0,
        "exact_selection_ids": [],
        "recent_fixture_ids": [],
        "team_counts": {},
        "league_counts": {},
        "market_counts": {},
    }

    if not anonymous_id:
        return empty

    ensure_tables()

    now = _utc(now) or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=RECENT_EXPOSURE_DAYS)
    fixture_cutoff = now - timedelta(days=RECENT_FIXTURE_DAYS)

    stmt = (
        select(
            ticket_history.c.id.label("ticket_id"),
            ticket_history.c.created_at.label("ticket_created_at"),
            ticket_selections.c.selection_fingerprint,
            ticket_selections.c.fixture_id,
            ticket_selections.c.home_team,
            ticket_selections.c.away_team,
            ticket_selections.c.league,
            ticket_selections.c.market,
        )
        .select_from(
            ticket_history.join(
                ticket_selections,
                ticket_selections.c.ticket_id == ticket_history.c.id,
            )
        )
        .where(
            ticket_history.c.anonymous_id == anonymous_id,
            ticket_history.c.created_at >= cutoff,
        )
    )

    with engine.connect() as conn:
        rows = conn.execute(stmt).mappings().all()

    tickets = set()
    selections = set()
    fixtures = set()
    team_counts = {}
    league_counts = {}
    market_counts = {}

    for row in rows:
        ticket_id = str(row.get("ticket_id") or "")
        if ticket_id:
            tickets.add(ticket_id)

        selection_id = str(row.get("selection_fingerprint") or "")
        if selection_id:
            selections.add(selection_id)

        created_at = _utc(row.get("ticket_created_at"))
        fixture_id = str(row.get("fixture_id") or "")

        if (
            fixture_id
            and created_at is not None
            and created_at >= fixture_cutoff
        ):
            fixtures.add(fixture_id)

        for team in (row.get("home_team"), row.get("away_team")):
            key = _normalise_key(team)
            if key:
                team_counts[key] = team_counts.get(key, 0) + 1

        league = _normalise_key(row.get("league"))
        if league:
            league_counts[league] = league_counts.get(league, 0) + 1

        market = str(row.get("market") or "").strip()
        if market:
            market_counts[market] = market_counts.get(market, 0) + 1

    return {
        "window_days": RECENT_EXPOSURE_DAYS,
        "fixture_window_days": RECENT_FIXTURE_DAYS,
        "history_ticket_count": len(tickets),
        "exact_selection_ids": sorted(selections),
        "recent_fixture_ids": sorted(fixtures),
        "team_counts": team_counts,
        "league_counts": league_counts,
        "market_counts": market_counts,
    }


def _fingerprint(games: list[dict]) -> str:
    stable = [{"fixture": str(g.get("fixture_id") or g.get("match_id") or ""), "selection": str(g.get("selection_id") or ""), "market": str(g.get("market") or ""), "prediction": str(g.get("prediction") or "")} for g in games]
    return hashlib.sha256(json.dumps(sorted(stable, key=lambda x: json.dumps(x, sort_keys=True)), sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def record_generated_ticket(payload: dict, result: dict) -> str | None:
    anonymous_id = payload.get("anonymous_id")
    if not anonymous_id or result.get("status") != "success" or not result.get("games"):
        return None
    ensure_tables(); games = result["games"]; fingerprint = _fingerprint(games)
    with engine.begin() as conn:
        prior = conn.execute(select(ticket_history.c.id).where(ticket_history.c.anonymous_id == anonymous_id, ticket_history.c.ticket_fingerprint == fingerprint)).scalar()
        if prior: return prior
        booking = result.get("booking") or {}; now = datetime.now(timezone.utc); ticket_id = str(uuid.uuid4())
        conn.execute(ticket_history.insert().values(id=ticket_id, anonymous_id=anonymous_id[:128], builder_request_id=str(result.get("request_id") or "")[:64], ticket_fingerprint=fingerprint, mode=str(payload.get("mode") or "")[:24], horizon=str(payload.get("horizon") or "")[:16], requested_target_odds=payload.get("target_odds"), requested_game_count=payload.get("game_count"), generated_odds=result.get("odds"), booking_status=booking.get("booking_status") or booking.get("status"), validation_status=booking.get("readback_validation"), board_snapshot_id=(result.get("board") or {}).get("board_snapshot_id"), generated=True, booking_validated=str(booking.get("readback_validation") or "").upper()=="PASSED", created_at=now, expires_at=now+timedelta(days=7), metadata_json=json.dumps({"version":"v2"})))
        for game in games:
            kickoff = game.get("kickoff") or game.get("date")
            if isinstance(kickoff, str):
                try: kickoff = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
                except ValueError: kickoff = None
            conn.execute(ticket_selections.insert().values(id=str(uuid.uuid4()), ticket_id=ticket_id, selection_fingerprint=str(game.get("selection_id") or game.get("match_id") or ""), fixture_id=str(game.get("fixture_id") or game.get("match_id") or "") or None, home_team=game.get("home_team"), away_team=game.get("away_team"), league=game.get("league"), market=game.get("market"), prediction=game.get("prediction"), odds=game.get("odds"), confidence=game.get("confidence"), evidence_probability=game.get("evidence_adjusted_probability"), trust_grade=(game.get("trust") or {}).get("grade"), kickoff=kickoff, created_at=now))
    return ticket_id
