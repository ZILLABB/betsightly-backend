"""Independent, immutable football-market forecast observations (staging pilot).

Never reads or writes official slips, calibration fits, customer tickets or
bookmaker booking tables. Capture is first-write-wins before kickoff; scores
can be attached later only from verified completed fixtures. Production is
not wired to this module and stage writes require explicit operator consent.
"""
from __future__ import annotations

import hashlib
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer, MetaData, String,
    Table, inspect, select, UniqueConstraint,
)
from sqlalchemy.exc import IntegrityError

from leagues.goal_distribution_challenger import settlement_labels
from leagues.market_registry import MARKETS

metadata = MetaData()
observations = Table(
    "market_shadow_forecasts_v1", metadata,
    Column("observation_key", String(64), primary_key=True),
    Column("fixture_id", String(128), nullable=False, index=True),
    Column("market", String(64), nullable=False, index=True),
    Column("model_version", String(96), nullable=False),
    Column("snapshot_id", String(96), nullable=False),
    Column("home_team", String(180), nullable=False),
    Column("away_team", String(180), nullable=False),
    Column("league_slug", String(120)),
    Column("kickoff", DateTime(timezone=True), nullable=False, index=True),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("probability", Float, nullable=False),
    Column("quoted_odds", Float),
    Column("odds_are_real", Boolean, nullable=False),
    Column("bookable_at_capture", Boolean, nullable=False),
    Column("sportybet_event_id", String(128)),
    Column("status", String(24), nullable=False),
    Column("home_score", Integer),
    Column("away_score", Integer),
    Column("outcome", Integer),
    Column("settlement_source", String(80)),
    Column("settled_at", DateTime(timezone=True)),
    UniqueConstraint("model_version", "fixture_id", "market",
                     name="uq_market_shadow_model_fixture_market"),
)

MARKET_OBSERVATION_VERSION = "market-shadow-baseline-20261008"
MIN_BEFORE_KICKOFF = timedelta(minutes=10)
MIN_SETTLE_AFTER_KICKOFF = timedelta(hours=3)


def _utc(value) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if result.tzinfo is None or result.utcoffset() is None:
        return None
    return result.astimezone(timezone.utc)


def staging_write_gate(*, db_engine) -> str:
    """Always query actual database identity; never trust a URL string label."""
    from scripts.prepare_staging_board_once import preflight

    name = preflight()
    if os.getenv("BETSIGHTLY_STAGING_MARKET_SHADOW_WRITE") != "CONFIRM_SHADOW_ONLY":
        raise RuntimeError("Shadow writes disabled: require CONFIRM_SHADOW_ONLY")
    if db_engine.dialect.name != "postgresql":
        raise RuntimeError("Shadow collection requires actual staging PostgreSQL")
    return name


def make_observation(pick: dict, snapshot_id: str,
                     observed_at: datetime) -> tuple[dict | None, str]:
    """Pure validation. The first captured model probability cannot change."""
    fixture = pick.get("_fixture") or {}
    market = str(pick.get("market") or "")
    spec = MARKETS.get(market)
    if not spec or not spec.settlement or not spec.candidate_generation:
        return None, "unregistered_or_unsettleable_market"
    fixture_id = str(pick.get("match_id") or "").strip()
    home = str((fixture.get("home") or {}).get("name") or "").strip()
    away = str((fixture.get("away") or {}).get("name") or "").strip()
    kickoff = _utc(fixture.get("commence_time"))
    observed = _utc(observed_at)
    if not fixture_id or not home or not away or not kickoff or not observed:
        return None, "invalid_fixture_identity"
    if kickoff - observed < MIN_BEFORE_KICKOFF:
        return None, "started_or_too_close_to_kickoff"
    if not snapshot_id:
        return None, "missing_snapshot"
    try:
        probability = float(pick.get("confidence"))
        price = float(pick.get("odds")) if pick.get("odds") is not None else None
    except (ValueError, TypeError):
        return None, "invalid_probability_or_price"
    if not (math.isfinite(probability) and 0 < probability < 1):
        return None, "invalid_probability"
    if price is not None and (not math.isfinite(price) or price < 1):
        return None, "invalid_price"
    # Do not invent a verified quote from an estimated price.
    real = bool(pick.get("odds_are_real", False))
    model_version = MARKET_OBSERVATION_VERSION
    key = hashlib.sha256(
        f"{model_version}|{fixture_id}|{market}".encode("utf-8")
    ).hexdigest()
    return {
        "observation_key": key,
        "fixture_id": fixture_id,
        "market": market,
        "model_version": model_version,
        "snapshot_id": str(snapshot_id)[:96],
        "home_team": home[:180],
        "away_team": away[:180],
        "league_slug": str(fixture.get("league_slug") or "")[:120],
        "kickoff": kickoff,
        "observed_at": observed,
        "probability": probability,
        "quoted_odds": price if real else None,
        "odds_are_real": real,
        "bookable_at_capture": bool(pick.get("bookable")),
        "sportybet_event_id": str(pick.get("sportybet_event_id") or "")[:128] or None,
        "status": "pending",
    }, "ready"


def ensure_table(db_engine) -> None:
    metadata.create_all(db_engine, tables=[observations], checkfirst=True)


def collect(picks: list[dict], snapshot_id: str, *,
            db_engine, observed_at: datetime | None = None) -> dict:
    """Append only, with full staging DB preflight and explicit opt-in."""
    staging_write_gate(db_engine=db_engine)
    now = _utc(observed_at or datetime.now(timezone.utc))
    if now is None:
        raise RuntimeError("Capture timestamp must be UTC-aware")
    pending_rows = []
    refused = Counter()
    seen = set()
    for pick in picks:
        row, reason = make_observation(pick, snapshot_id, now)
        if row is None:
            refused[reason] += 1
            continue
        if row["observation_key"] in seen:
            refused["same_run_duplicate"] += 1
            continue
        seen.add(row["observation_key"])
        pending_rows.append(row)
    # The table is not created unless stage preflight passed.
    ensure_table(db_engine)
    inserted = 0
    existing = 0
    for row in pending_rows:
        try:
            with db_engine.begin() as connection:
                prior = connection.execute(
                    select(observations.c.observation_key).where(
                        observations.c.observation_key == row["observation_key"]
                    )
                ).first()
                if prior:
                    existing += 1
                    continue
                connection.execute(observations.insert().values(**row))
                inserted += 1
        except IntegrityError:
            existing += 1
    return {
        "status": "SHADOW_CAPTURE_ONLY",
        "inserted": inserted, "existing": existing,
        "refused": dict(sorted(refused.items())),
        "snapshot_id": snapshot_id,
        "official_results_changed": False,
        "production_models_changed": False,
        "booking_created": False,
    }


def pending_fixtures(*, db_engine, now: datetime | None = None,
                     limit: int = 100) -> tuple[list[dict], list[dict]]:
    """Read eligible score lookups, one request item per fixture."""
    if not inspect(db_engine).has_table(observations.name):
        return [], []
    current = _utc(now or datetime.now(timezone.utc))
    with db_engine.connect() as conn:
        rows = conn.execute(
            select(observations)
            .where(
                observations.c.status == "pending",
                observations.c.kickoff <= current - MIN_SETTLE_AFTER_KICKOFF,
            )
            .order_by(observations.c.kickoff.asc())
            .limit(min(2000, max(1, limit) * 20))
        ).mappings().all()
    fixtures = {}
    for row in rows:
        fixture_id = row["fixture_id"]
        fixtures.setdefault(fixture_id, {
            "match_id": fixture_id,
            "home_team": row["home_team"],
            "away_team": row["away_team"],
            "commence_time": _utc(row["kickoff"]).isoformat(),
            "league_slug": row["league_slug"],
        })
        if len(fixtures) >= limit:
            break
    ids = set(fixtures)
    return [dict(row) for row in rows if row["fixture_id"] in ids], list(fixtures.values())


def verified_result_for_row(row: dict, scores: dict) -> tuple[dict | None, str]:
    """Fail closed on unresolved/ambiguous final scores and unknown markets."""
    from leagues.results_checker import _lookup_settlement_score
    kickoff = _utc(row["kickoff"])
    result = _lookup_settlement_score(
        scores, row["home_team"], row["away_team"],
        kickoff.date().isoformat(),
    )
    if not result:
        return None, "score_not_verified"
    if result.get("ambiguous"):
        return None, "ambiguous_score"
    try:
        home = result["home_score"]
        away = result["away_score"]
        if type(home) is not int or type(away) is not int:
            return None, "non_integer_score"
        labels = settlement_labels(home, away)
        if row["market"] not in labels:
            return None, "unsettleable_market"
        outcome = labels[row["market"]]
    except (ValueError, TypeError, KeyError):
        return None, "invalid_score"
    return {"home_score": home, "away_score": away,
            "outcome": outcome, "status": "void" if outcome is None else "settled"}, "ready"


def settle(*, db_engine, now: datetime | None = None,
           limit: int = 100, score_fetcher=None) -> dict:
    """Only explicit staging invocation; never updates published predictions."""
    staging_write_gate(db_engine=db_engine)
    current = _utc(now or datetime.now(timezone.utc))
    rows, fixtures = pending_fixtures(db_engine=db_engine, now=current, limit=limit)
    if not rows:
        return {"status": "SHADOW_SETTLEMENT_ONLY", "checked": 0,
                "settled": 0, "void": 0, "unresolved": 0}
    if score_fetcher is None:
        from leagues.results_checker import _collect_scores_for_picks
        score_fetcher = _collect_scores_for_picks
    scores, source = score_fetcher(fixtures)
    source = str(source or "unknown")[:80]
    resolved = {"settled": 0, "void": 0, "unresolved": 0}
    why = Counter()
    for row in rows:
        grade, reason = verified_result_for_row(row, scores)
        if grade is None:
            resolved["unresolved"] += 1
            why[reason] += 1
            continue
        with db_engine.begin() as conn:
            result = conn.execute(
                observations.update().where(
                    observations.c.observation_key == row["observation_key"],
                    observations.c.status == "pending",
                ).values(**grade, settled_at=current, settlement_source=source)
            )
            if result.rowcount:
                resolved[grade["status"]] += 1
    return {
        "status": "SHADOW_SETTLEMENT_ONLY", "checked": len(rows),
        **resolved, "unresolved_reasons": dict(sorted(why.items())),
        "score_source": source, "official_results_changed": False,
        "booking_created": False,
    }


def evidence_report(*, db_engine) -> dict:
    """Descriptive prospective shadow evidence, NOT calibration approval."""
    if not inspect(db_engine).has_table(observations.name):
        return {"status": "NO_TABLE", "markets": {}}
    with db_engine.connect() as conn:
        rows = conn.execute(select(observations)).mappings().all()
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["market"]].append(row)
    report = {}
    for market, entries in sorted(grouped.items()):
        completed = [r for r in entries if r["status"] == "settled"]
        brier = None
        if completed:
            brier = round(
                sum((float(r["probability"]) - int(r["outcome"])) ** 2
                    for r in completed) / len(completed), 6
            )
        report[market] = {
            "captured": len(entries),
            "pending": sum(r["status"] == "pending" for r in entries),
            "settled": len(completed),
            "void": sum(r["status"] == "void" for r in entries),
            "brier": brier,
            "real_price_captured": sum(bool(r["odds_are_real"]) for r in entries),
            "bookable_at_capture": sum(bool(r["bookable_at_capture"]) for r in entries),
            "ready_for_publication": False,
        }
    return {
        "status": "SHADOW_EVIDENCE_ONLY",
        "markets": report,
        "official_accuracy_changed": False,
        "market_promotion_allowed": False,
    }
