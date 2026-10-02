"""Append-only, opt-in odds evidence and read-only closing-line evaluation.

This module never fetches a provider and is not an input to prediction policy.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import (Boolean, Column, DateTime, Float, Index,
                        Integer, MetaData, String, Table, Text, UniqueConstraint,
                        func, or_, select)
from sqlalchemy.exc import IntegrityError

from database import engine

logger = logging.getLogger(__name__)
metadata = MetaData()

observations = Table(
    "odds_observations", metadata,
    Column("id", String(64), primary_key=True),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("provider", String(40), nullable=False),
    Column("provider_snapshot_id", String(128), nullable=False),
    Column("canonical_fixture_id", String(128), nullable=False),
    Column("provider_event_id", String(128)),
    Column("league_id", String(128)),
    Column("kickoff_utc", DateTime(timezone=True), nullable=False),
    Column("market", String(64), nullable=False),
    Column("selection", String(128), nullable=False),
    Column("bookmaker", String(80), nullable=False),
    Column("decimal_odds", Float, nullable=False),
    Column("implied_probability", Float, nullable=False),
    Column("bookable", Boolean, nullable=False),
    Column("real_odds", Boolean, nullable=False),
    Column("source_type", String(40), nullable=False),
    Column("provenance_json", Text),
    Column("policy_version", String(64)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("ix_odds_obs_fixture", "canonical_fixture_id"),
    Index("ix_odds_obs_kickoff", "kickoff_utc"),
    Index("ix_odds_obs_observed", "observed_at"),
    Index("ix_odds_obs_provider", "provider"),
    Index("ix_odds_obs_market", "market"),
    Index("ix_odds_obs_close", "canonical_fixture_id", "market", "selection", "observed_at"),
)

entries = Table(
    "odds_selection_entries", metadata,
    Column("id", String(64), primary_key=True),
    Column("source_kind", String(24), nullable=False),
    Column("source_id", String(128), nullable=False),
    Column("leg_index", Integer, nullable=False),
    Column("selected_at", DateTime(timezone=True), nullable=False),
    Column("canonical_fixture_id", String(128), nullable=False),
    Column("provider_event_id", String(128)),
    Column("league_id", String(128)),
    Column("kickoff_utc", DateTime(timezone=True), nullable=False),
    Column("market", String(64), nullable=False),
    Column("selection", String(128), nullable=False),
    Column("entry_odds", Float, nullable=False),
    Column("entry_source", String(64), nullable=False),
    Column("mode", String(24)),
    Column("horizon", String(16)),
    Column("policy_version", String(64)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("source_kind", "source_id", "leg_index", name="uq_odds_entry_source_leg"),
    Index("ix_odds_entry_fixture", "canonical_fixture_id"),
    Index("ix_odds_entry_selected", "selected_at"),
)


def capture_enabled() -> bool:
    return os.getenv("ODDS_HISTORY_CAPTURE_ENABLED", "false").lower() in {"1", "true", "yes"}


def _utc(value) -> datetime | None:
    if isinstance(value, (int, float)):
        try:
            value = datetime.fromtimestamp(value, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    elif isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    return value.astimezone(timezone.utc)


def _db_utc(value) -> datetime | None:
    """SQLite drops timezone metadata; persisted timestamps are UTC by contract."""
    if isinstance(value, datetime) and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return _utc(value)


def _digest(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, separators=(",", ":"),
                                     default=str).encode()).hexdigest()


def _valid_odds(value) -> float | None:
    try:
        odds = float(value)
    except (TypeError, ValueError):
        return None
    return odds if math.isfinite(odds) and odds > 1.0 else None


def _insert_ignore(conn, table: Table, row: dict) -> bool:
    """Portable idempotency; DB primary/unique constraints settle races."""
    try:
        with conn.begin_nested():
            conn.execute(table.insert().values(**row))
        return True
    except IntegrityError:
        return False


def _insert_rows(conn, table: Table, rows: list[dict]) -> int:
    """Batch insert with DB-enforced idempotency; bound SQL parameter count."""
    dialect = conn.dialect.name
    if dialect in {"postgresql", "sqlite"}:
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        inserted = 0
        for offset in range(0, len(rows), 35):
            batch = rows[offset:offset + 35]
            statement = insert(table).values(batch).on_conflict_do_nothing(
                index_elements=[table.c.id])
            inserted += max(0, conn.execute(statement).rowcount or 0)
        return inserted
    return sum(_insert_ignore(conn, table, row) for row in rows)


def ingest_observations(rows: list[dict], *, connection=None) -> dict:
    """Persist real pre-kickoff quotes from an already-fetched snapshot."""
    prepared = []
    rejected = 0
    for item in rows:
        at, kickoff = _utc(item.get("observed_at")), _utc(item.get("kickoff_utc"))
        odds = _valid_odds(item.get("decimal_odds"))
        provider = str(item.get("provider") or "").strip().lower()
        snapshot = str(item.get("provider_snapshot_id") or "").strip()
        fixture = str(item.get("canonical_fixture_id") or "").strip()
        market = str(item.get("market") or "").strip()
        selection = str(item.get("selection") or "").strip()
        book = str(item.get("bookmaker") or "").strip()
        if (not all((at, kickoff, odds, provider, snapshot, fixture, market,
                     selection, book)) or at >= kickoff or
                not item.get("real_odds")):
            rejected += 1
            continue
        identity = (provider, snapshot, item.get("provider_event_id") or fixture,
                    market, selection, book)
        prepared.append({
            "id": _digest(*identity), "observed_at": at, "provider": provider,
            "provider_snapshot_id": snapshot,
            "canonical_fixture_id": fixture,
            "provider_event_id": str(item.get("provider_event_id") or "") or None,
            "league_id": str(item.get("league_id") or "") or None,
            "kickoff_utc": kickoff, "market": market, "selection": selection,
            "bookmaker": book, "decimal_odds": odds,
            "implied_probability": 1.0 / odds,
            "bookable": bool(item.get("bookable")),
            "real_odds": True, "source_type": str(item.get("source_type") or "snapshot"),
            "provenance_json": json.dumps(item.get("provenance") or {}, sort_keys=True),
            "policy_version": item.get("policy_version"),
            "created_at": datetime.now(timezone.utc),
        })
    def insert(conn):
        return _insert_rows(conn, observations, prepared)
    if connection is None:
        with engine.begin() as conn:
            inserted = insert(conn)
    else:
        inserted = insert(connection)
    return {"inserted": inserted, "existing": len(prepared) - inserted,
            "rejected": rejected}


def capture_sportybet_fixture_prices(fixtures: list[dict], board: dict) -> dict:
    """Record matched board prices only; never performs a provider request."""
    from leagues import sportybet
    meta = sportybet.board_metadata(board)
    fetched = meta.get("fetched_at")
    snapshot = meta.get("snapshot_id")
    if not snapshot or not fetched:
        return {"inserted": 0, "reason": "snapshot_identity_missing"}
    rows = []
    by_event = {str(entry.get("event_id")): entry
                for _, entry in sportybet._board_entries(board)
                if entry.get("event_id")}
    for fixture in fixtures:
        odds = fixture.get("odds") or {}
        event_id = odds.get("sportybet_event_id")
        match_id = fixture.get("match_id")
        kickoff = fixture.get("commence_time")
        provider_entry = by_event.get(str(event_id)) if event_id else None
        if not provider_entry or not match_id:
            continue
        for market, price in (provider_entry.get("prices") or {}).items():
            if market not in sportybet.MARKET_TO_SPORTYBET:
                continue
            if not _valid_odds(price):
                continue
            rows.append({
                "observed_at": fetched, "provider": "sportybet",
                "provider_snapshot_id": snapshot,
                "canonical_fixture_id": f"espn:{match_id}",
                "provider_event_id": event_id,
                "league_id": fixture.get("league_slug"),
                "kickoff_utc": kickoff, "market": market,
                "selection": market, "bookmaker": "SportyBet",
                "decimal_odds": price, "bookable": True, "real_odds": True,
                "source_type": "prepared_board", "provenance": {"matched_event_id": True},
            })
    return ingest_observations(rows)


def capture_odds_api_events(events: list[dict], sport_key: str) -> dict:
    """Store raw h2h quotes from the existing budgeted fetch, not a new call.

    These are real quotes, but not exact SportyBet-bookable prices and are
    deliberately ineligible as a closing price under the current policy.
    """
    rows = []
    for event in events:
        event_id = event.get("id")
        home, away = event.get("home_team"), event.get("away_team")
        if not event_id or not home or not away:
            continue
        for book in event.get("bookmakers") or []:
            at = book.get("last_update")
            if not at:
                continue
            for market in book.get("markets") or []:
                if market.get("key") != "h2h":
                    continue
                for outcome in market.get("outcomes") or []:
                    name = outcome.get("name")
                    selection = ("home_win" if name == home else
                                 "away_win" if name == away else
                                 "draw" if name == "Draw" else None)
                    if not selection:
                        continue
                    rows.append({
                        "observed_at": at, "provider": "the_odds_api",
                        "provider_snapshot_id": f"{event_id}:{book.get('key')}:{at}",
                        "canonical_fixture_id": f"oddsapi:{event_id}",
                        "provider_event_id": event_id,
                        "league_id": sport_key,
                        "kickoff_utc": event.get("commence_time"),
                        "market": selection, "selection": selection,
                        "bookmaker": book.get("title") or book.get("key"),
                        "decimal_odds": outcome.get("price"),
                        "real_odds": True, "bookable": False,
                        "source_type": "existing_odds_shop_fetch",
                    })
    return ingest_observations(rows)


def capture_closing_snapshot() -> dict:
    """Explicitly disabled-by-default extra capture, never a public route.

    A separate authorized worker schedule may call this close to kickoff.
    No scheduler is registered here and the database lease prevents overlap.
    """
    if os.getenv("ODDS_HISTORY_CLOSE_FETCH_ENABLED", "false").lower() not in {
            "1", "true", "yes"}:
        return {"status": "disabled", "provider_calls": 0}
    role = os.getenv("BETSIGHTLY_PROCESS_ROLE", "web").lower()
    if role not in {"worker", "scheduler"}:
        return {"status": "wrong_process_role", "provider_calls": 0}
    from sqlalchemy import inspect
    if not inspect(engine).has_table("odds_observations"):
        return {"status": "migration_required", "provider_calls": 0}
    from services.process_leases import acquire_process_lease
    lease = acquire_process_lease("betsightly:odds_history:closing_capture")
    if lease is None:
        return {"status": "owned_elsewhere", "provider_calls": 0}
    try:
        from leagues.engine import prepared_board
        from leagues import sportybet
        _, fixtures, state = prepared_board(7)
        if not state.get("ready") or not fixtures:
            return {"status": "prepared_board_unavailable", "provider_calls": 0}
        board = sportybet.fetch_board(force=True)
        result = capture_sportybet_fixture_prices(fixtures, board)
        return {"status": "captured", "provider_calls": 1, **result}
    finally:
        lease.release()


def _entry_price(game: dict, booking: dict | None) -> tuple[float, str] | None:
    booking = booking or {}
    available = game.get("sportybet_availability") or {}
    quote = _valid_odds(available.get("sportybet_odds") or game.get("sportybet_odds"))
    if (quote and booking.get("status") == "active" and
            booking.get("booking_status") in {"FULL", "REBUILT_FULL"} and
            booking.get("readback_validation") == "PASSED"):
        # Readback confirms the selection set, not an individual leg price.
        return quote, "validated_booking_board_quote"
    if quote and available.get("sportybet_available"):
        return quote, "sportybet_selection_quote"
    odds = _valid_odds(game.get("odds"))
    if odds and game.get("odds_are_real"):
        return odds, "real_attached_provider_quote"
    return None


def record_selection_entries(source_kind: str, source_id: str, games: list[dict],
                             *, selected_at: datetime, booking: dict | None = None,
                             mode: str | None = None, horizon: str | None = None,
                             policy_version: str | None = None,
                             connection=None) -> dict:
    """Link immutable published/Builder legs to truthful entry prices."""
    if source_kind not in {"builder", "published"}:
        raise ValueError("unsupported source_kind")
    selected_at = _utc(selected_at)
    if not selected_at:
        raise ValueError("selected_at must be timezone-aware")
    prepared, skipped = [], 0
    for index, game in enumerate(games):
        price = _entry_price(game, booking)
        kickoff = _utc(game.get("kickoff") or game.get("commence_time") or game.get("date"))
        match_id = game.get("match_id")
        market = str(game.get("market") or "").strip()
        event_id = game.get("sportybet_event_id") or (game.get("sportybet_availability") or {}).get("event_id")
        if not price or not kickoff or not match_id or not market or selected_at >= kickoff:
            skipped += 1
            continue
        prepared.append({
            "id": _digest(source_kind, source_id, index),
            "source_kind": source_kind, "source_id": str(source_id),
            "leg_index": index, "selected_at": selected_at,
            "canonical_fixture_id": f"espn:{match_id}",
            "provider_event_id": str(event_id) if event_id else None,
            "league_id": game.get("league_slug") or game.get("league"),
            "kickoff_utc": kickoff, "market": market, "selection": market,
            "entry_odds": price[0], "entry_source": price[1],
            "mode": mode, "horizon": horizon, "policy_version": policy_version,
            "created_at": datetime.now(timezone.utc),
        })
    def insert(conn):
        return _insert_rows(conn, entries, prepared)
    if connection is None:
        with engine.begin() as conn:
            inserted = insert(conn)
    else:
        inserted = insert(connection)
    return {"inserted": inserted, "existing": len(prepared) - inserted,
            "skipped": skipped}


def evaluate_entry(entry: dict, observed: list[dict], *,
                   now: datetime | None = None, safety_seconds: int = 60) -> dict:
    """Choose the final later, real, bookable quote before kickoff."""
    now = _utc(now or datetime.now(timezone.utc))
    kickoff = _db_utc(entry["kickoff_utc"])
    selected = _db_utc(entry["selected_at"])
    bound = kickoff - timedelta(seconds=max(0, safety_seconds))
    candidates = []
    for quote in observed:
        at = _db_utc(quote.get("observed_at"))
        same_fixture = quote.get("canonical_fixture_id") == entry["canonical_fixture_id"]
        same_event = (entry.get("provider_event_id") and
                      quote.get("provider") == "sportybet" and
                      quote.get("provider_event_id") == entry["provider_event_id"])
        if (at and selected < at < bound and (same_fixture or same_event) and
                quote.get("market") == entry["market"] and
                quote.get("selection") == entry["selection"] and
                _db_utc(quote.get("kickoff_utc")) == kickoff and
                quote.get("real_odds") and quote.get("bookable") and
                _valid_odds(quote.get("decimal_odds"))):
            candidates.append(quote)
    if not candidates or now < bound:
        return {"status": "pending" if now < bound else "unavailable",
                "entry_odds": entry["entry_odds"], "closing_odds": None,
                "entry_implied_probability": 1.0 / float(entry["entry_odds"]),
                "closing_implied_probability": None,
                "price_clv": None, "probability_clv": None}
    latest = max(candidates, key=lambda q: (_db_utc(q["observed_at"]), q.get("id") or ""))
    entry_odds, close = float(entry["entry_odds"]), float(latest["decimal_odds"])
    return {"status": "complete", "entry_odds": entry_odds,
            "entry_at": selected.isoformat(), "entry_source": entry["entry_source"],
            "closing_odds": close, "closing_at": _db_utc(latest["observed_at"]).isoformat(),
            "closing_source": latest["provider"],
            "entry_implied_probability": 1.0 / entry_odds,
            "closing_implied_probability": 1.0 / close,
            "price_clv": entry_odds / close - 1.0,
            "probability_clv": 1.0 / close - 1.0 / entry_odds}


def selection_report(*, start: datetime | None = None,
                     end: datetime | None = None,
                     now: datetime | None = None) -> list[dict]:
    """Read-only per-selection CLV; query observations in bounded batches."""
    conditions = []
    if start:
        conditions.append(entries.c.selected_at >= _utc(start))
    if end:
        conditions.append(entries.c.selected_at < _utc(end))
    with engine.connect() as conn:
        entry_rows = [dict(row) for row in conn.execute(
            select(entries).where(*conditions)).mappings()]
        result = []
        for offset in range(0, len(entry_rows), 100):
            batch = entry_rows[offset:offset + 100]
            fixture_ids = {row["canonical_fixture_id"] for row in batch}
            event_ids = {row["provider_event_id"] for row in batch
                         if row.get("provider_event_id")}
            identity = observations.c.canonical_fixture_id.in_(fixture_ids)
            if event_ids:
                identity = or_(identity,
                    (observations.c.provider == "sportybet") &
                    observations.c.provider_event_id.in_(event_ids))
            quotes = [dict(row) for row in conn.execute(select(observations).where(
                identity,
                observations.c.market.in_({row["market"] for row in batch}),
                observations.c.observed_at > min(row["selected_at"] for row in batch),
                observations.c.observed_at < max(row["kickoff_utc"] for row in batch),
            )).mappings()]
            by_fixture, by_event = defaultdict(list), defaultdict(list)
            for quote in quotes:
                key = (quote["market"], quote["selection"])
                by_fixture[(quote["canonical_fixture_id"], *key)].append(quote)
                if quote["provider"] == "sportybet" and quote["provider_event_id"]:
                    by_event[(quote["provider_event_id"], *key)].append(quote)
            for entry in batch:
                key = (entry["market"], entry["selection"])
                possible = list(by_fixture[(entry["canonical_fixture_id"], *key)])
                if entry.get("provider_event_id"):
                    possible += by_event[(entry["provider_event_id"], *key)]
                distinct = {quote["id"]: quote for quote in possible}
                result.append({**entry, **evaluate_entry(entry, list(distinct.values()),
                                                        now=now)})
    return result


def aggregate_report(rows: list[dict]) -> dict:
    completed = [row for row in rows if row["status"] == "complete"]
    def summary(items):
        values = [row["price_clv"] for row in items if row["status"] == "complete"]
        probabilities = [row["probability_clv"] for row in items if row["status"] == "complete"]
        return {"selection_count": len(items), "evaluated_count": len(values),
                "unavailable_count": sum(row["status"] == "unavailable" for row in items),
                "pending_count": sum(row["status"] == "pending" for row in items),
                "positive_clv_rate": sum(v > 0 for v in values) / len(values) if values else None,
                "average_price_clv": statistics.mean(values) if values else None,
                "median_price_clv": statistics.median(values) if values else None,
                "average_probability_clv": statistics.mean(probabilities) if probabilities else None}
    out = summary(rows)
    for field in ("market", "league_id", "mode", "horizon", "policy_version",
                  "entry_source", "closing_source"):
        groups = defaultdict(list)
        for row in rows:
            groups[str(row.get(field) or "unknown")].append(row)
        out[f"by_{field}"] = {key: summary(items) for key, items in sorted(groups.items())}
    out["by_provider"] = out["by_closing_source"]
    out["completed_count"] = len(completed)
    return out


def status_report() -> dict:
    with engine.connect() as conn:
        row = conn.execute(select(func.count(), func.min(observations.c.observed_at),
                                  func.max(observations.c.observed_at),
                                  func.count(func.distinct(observations.c.canonical_fixture_id)))).one()
        providers = dict(conn.execute(select(observations.c.provider,
                              func.count()).group_by(observations.c.provider)).all())
    result = aggregate_report(selection_report())
    return {"observation_count": row[0], "earliest_observation": row[1],
            "latest_observation": row[2], "fixture_count": row[3],
            "provider_counts": providers,
            "selections_awaiting_close": result["pending_count"],
            "selections_evaluated": result["evaluated_count"],
            "selections_unavailable": result["unavailable_count"],
            "last_successful_capture": row[2]}


def backfill_archive_entries(start: datetime, end: datetime, *,
                             dry_run: bool = True) -> dict:
    """Bounded, resumable entry-only backfill from immutable stored selections.

    No historical snapshot/closing odds are synthesized. Existing naive
    created_at values came from utcnow() in these archives.
    """
    start, end = _utc(start), _utc(end)
    if not start or not end or start >= end or end - start > timedelta(days=31):
        raise ValueError("A positive date range of at most 31 days is required")
    from leagues.builder_runs import builder_predictions
    from leagues.picks_db import PublishedSlip
    from sqlalchemy.orm import Session
    planned, inserted, skipped = 0, 0, 0
    with Session(engine) as session:
        builder_rows = session.execute(select(builder_predictions).where(
            builder_predictions.c.created_at >= start,
            builder_predictions.c.created_at < end)).mappings().all()
        slip_rows = session.query(PublishedSlip).filter(
            PublishedSlip.created_at >= start.replace(tzinfo=None),
            PublishedSlip.created_at < end.replace(tzinfo=None)).all()
        sources = []
        for row in builder_rows:
            sources.append(("builder", row["selection_fingerprint"],
                            row["picks"], row["created_at"], row["mode"],
                            row["horizon"], row["policy_version"]))
        for slip in slip_rows:
            sources.append(("published", str(slip.id), slip.picks,
                            slip.created_at, slip.category, "today",
                            slip.policy_version))
        for kind, source_id, payload, created, mode, horizon, policy in sources:
            games = json.loads(payload or "[]")
            if not isinstance(games, list):
                skipped += 1
                continue
            created = created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created
            # A dry-run never calls the insert function or opens a write txn.
            if dry_run:
                for game in games:
                    kickoff = _utc(game.get("kickoff") or game.get("commence_time") or
                                   game.get("date"))
                    if (_entry_price(game, None) and kickoff and created < kickoff and
                            game.get("match_id") and game.get("market")):
                        planned += 1
                    else:
                        skipped += 1
                continue
            outcome = record_selection_entries(
                kind, source_id, games, selected_at=created, mode=mode,
                horizon=horizon, policy_version=policy,
            )
            inserted += outcome["inserted"]
            skipped += outcome["skipped"]
    return {"dry_run": dry_run, "source_count": len(sources),
            "planned_entries": planned, "inserted_entries": inserted,
            "skipped_legs": skipped, "closing_prices_backfilled": 0}
