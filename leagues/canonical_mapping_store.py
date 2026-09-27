"""Explicit persistence for canonical provider mappings.

Nothing in this module is called by public prediction/Builder endpoints.
Writers are opt-in maintenance/shadow jobs only. Read-only diagnostics may
reuse verified mappings once they exist.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, MetaData, String, Table,
    and_, insert, select, update,
)
from sqlalchemy.exc import IntegrityError

from database import engine as default_engine
from leagues import canonical_identity

metadata = MetaData()

canonical_teams = Table(
    "canonical_teams", metadata,
    Column("id", String(36), primary_key=True),
    Column("canonical_name", String(180), nullable=False),
    Column("normalized_name", String(180), nullable=False),
    Column("country", String(80)),
    Column("squad", String(24), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

canonical_competitions = Table(
    "canonical_competitions", metadata,
    Column("id", String(36), primary_key=True),
    Column("canonical_name", String(180), nullable=False),
    Column("normalized_name", String(180), nullable=False),
    Column("country", String(80)),
    Column("competition_type", String(32)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

canonical_fixtures = Table(
    "canonical_fixtures", metadata,
    Column("id", String(36), primary_key=True),
    Column("home_team_id", String(36), ForeignKey("canonical_teams.id"), nullable=False),
    Column("away_team_id", String(36), ForeignKey("canonical_teams.id"), nullable=False),
    Column("competition_id", String(36), ForeignKey("canonical_competitions.id")),
    Column("kickoff", DateTime(timezone=True), nullable=False),
    Column("status", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

provider_team_mappings = Table(
    "provider_team_mappings", metadata,
    Column("provider", String(32), primary_key=True),
    Column("provider_team_id", String(128), primary_key=True),
    Column("provider_name", String(180), nullable=False),
    Column("canonical_team_id", String(36), ForeignKey("canonical_teams.id"), nullable=False),
    Column("match_method", String(32), nullable=False),
    Column("confidence", Float, nullable=False),
    Column("verified", Boolean, nullable=False),
    Column("matched_at", DateTime(timezone=True), nullable=False),
)

provider_competition_mappings = Table(
    "provider_competition_mappings", metadata,
    Column("provider", String(32), primary_key=True),
    Column("provider_competition_id", String(128), primary_key=True),
    Column("provider_name", String(180), nullable=False),
    Column("canonical_competition_id", String(36), ForeignKey("canonical_competitions.id"), nullable=False),
    Column("match_method", String(32), nullable=False),
    Column("confidence", Float, nullable=False),
    Column("verified", Boolean, nullable=False),
    Column("matched_at", DateTime(timezone=True), nullable=False),
)

provider_fixture_mappings = Table(
    "provider_fixture_mappings", metadata,
    Column("provider", String(32), primary_key=True),
    Column("provider_fixture_id", String(128), primary_key=True),
    Column("canonical_fixture_id", String(36), ForeignKey("canonical_fixtures.id"), nullable=False),
    Column("match_method", String(32), nullable=False),
    Column("confidence", Float, nullable=False),
    Column("verified", Boolean, nullable=False),
    Column("matched_at", DateTime(timezone=True), nullable=False),
)

team_aliases = Table(
    "team_aliases", metadata,
    Column("provider", String(32), primary_key=True),
    Column("normalized_alias", String(180), primary_key=True),
    Column("canonical_team_id", String(36), ForeignKey("canonical_teams.id"), primary_key=True),
    Column("verified", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

_NAMESPACE = uuid.UUID("96d963e3-fb2c-4d9b-a646-b26cf262c1bf")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid(kind: str, *parts) -> str:
    material = "|".join(str(part or "").strip().casefold() for part in parts)
    return str(uuid.uuid5(_NAMESPACE, f"{kind}|{material}"))


def _utc(value) -> datetime:
    dt = canonical_identity._kickoff(value)
    if dt is None:
        raise ValueError("kickoff is required for canonical fixture identity")
    return dt


def _insert_once(bind, table: Table, values: dict) -> None:
    try:
        with bind.begin() as conn:
            conn.execute(insert(table).values(**values))
    except IntegrityError:
        # Deterministic IDs and provider mapping PKs make concurrent/repeated
        # shadow reconciliation idempotent. Existing rows win.
        pass


def ensure_canonical_team(
    name: str, *, country: str = "", squad: str = "", bind=None
) -> str:
    bind = bind or default_engine
    normalized = canonical_identity.normalize_team(name)
    if not normalized:
        raise ValueError("team name is required")
    country = (country or "").strip()
    squad = (squad or "").strip()
    team_id = _uuid("team", normalized, country, squad)
    now = _now()
    _insert_once(bind, canonical_teams, {
        "id": team_id,
        "canonical_name": str(name).strip(),
        "normalized_name": normalized,
        "country": country or None,
        "squad": squad,
        "created_at": now,
        "updated_at": now,
    })
    return team_id


def ensure_canonical_competition(
    name: str, *, country: str = "", competition_type: str = "", bind=None
) -> str | None:
    bind = bind or default_engine
    normalized = canonical_identity.normalize_competition(name)
    if not normalized:
        return None
    country = (country or "").strip()
    competition_id = _uuid("competition", normalized, country)
    now = _now()
    _insert_once(bind, canonical_competitions, {
        "id": competition_id,
        "canonical_name": str(name).strip(),
        "normalized_name": normalized,
        "country": country or None,
        "competition_type": (competition_type or "").strip() or None,
        "created_at": now,
        "updated_at": now,
    })
    return competition_id


def ensure_canonical_fixture(
    fixture: dict, *, bind=None
) -> dict:
    bind = bind or default_engine
    home_name = str(fixture.get("home_team") or "").strip()
    away_name = str(fixture.get("away_team") or "").strip()
    if not home_name or not away_name:
        raise ValueError("home_team and away_team are required")
    home_squad = canonical_identity.sportybet._squad(home_name)
    away_squad = canonical_identity.sportybet._squad(away_name)
    country = str(fixture.get("country") or "").strip()

    home_id = ensure_canonical_team(
        home_name, country=country, squad=home_squad, bind=bind
    )
    away_id = ensure_canonical_team(
        away_name, country=country, squad=away_squad, bind=bind
    )
    if home_id == away_id:
        raise ValueError("canonical fixture teams must be distinct")

    competition_id = ensure_canonical_competition(
        str(fixture.get("competition") or ""),
        country=country,
        competition_type=str(fixture.get("competition_type") or ""),
        bind=bind,
    )
    kickoff = _utc(fixture.get("kickoff"))
    fixture_id = _uuid(
        "fixture",
        home_id,
        away_id,
        competition_id or "",
        kickoff.isoformat(),
    )
    now = _now()
    _insert_once(bind, canonical_fixtures, {
        "id": fixture_id,
        "home_team_id": home_id,
        "away_team_id": away_id,
        "competition_id": competition_id,
        "kickoff": kickoff,
        "status": str(fixture.get("status") or "SCHEDULED"),
        "created_at": now,
        "updated_at": now,
    })
    return {
        "id": fixture_id,
        "home_team_id": home_id,
        "away_team_id": away_id,
        "competition_id": competition_id,
        "home_team": home_name,
        "away_team": away_name,
        "competition": fixture.get("competition") or "",
        "country": country,
        "kickoff": kickoff,
    }


def save_verified_fixture_mapping(
    provider: str,
    provider_fixture_id: str,
    canonical_fixture_id: str,
    *,
    match_method: str,
    confidence: float,
    bind=None,
) -> None:
    bind = bind or default_engine
    provider = str(provider or "").strip().casefold()
    provider_fixture_id = str(provider_fixture_id or "").strip()
    if not provider or not provider_fixture_id or not canonical_fixture_id:
        raise ValueError("provider, provider_fixture_id and canonical_fixture_id are required")
    values = {
        "provider": provider,
        "provider_fixture_id": provider_fixture_id,
        "canonical_fixture_id": str(canonical_fixture_id),
        "match_method": str(match_method or "verified"),
        "confidence": float(confidence),
        "verified": True,
        "matched_at": _now(),
    }
    with bind.begin() as conn:
        updated = conn.execute(
            update(provider_fixture_mappings)
            .where(and_(
                provider_fixture_mappings.c.provider == provider,
                provider_fixture_mappings.c.provider_fixture_id == provider_fixture_id,
            ))
            .values(**values)
        ).rowcount
        if not updated:
            conn.execute(insert(provider_fixture_mappings).values(**values))


def load_verified_fixture_mapping(
    provider: str, provider_fixture_id: str, *, bind=None
) -> str | None:
    bind = bind or default_engine
    provider = str(provider or "").strip().casefold()
    provider_fixture_id = str(provider_fixture_id or "").strip()
    if not provider or not provider_fixture_id:
        return None
    with bind.begin() as conn:
        row = conn.execute(
            select(provider_fixture_mappings.c.canonical_fixture_id)
            .where(and_(
                provider_fixture_mappings.c.provider == provider,
                provider_fixture_mappings.c.provider_fixture_id == provider_fixture_id,
                provider_fixture_mappings.c.verified.is_(True),
            ))
        ).fetchone()
    return str(row[0]) if row else None


def save_verified_team_mapping(
    provider: str,
    provider_team_id: str,
    provider_name: str,
    canonical_team_id: str,
    *,
    match_method: str,
    confidence: float,
    bind=None,
) -> None:
    bind = bind or default_engine
    values = {
        "provider": str(provider).strip().casefold(),
        "provider_team_id": str(provider_team_id).strip(),
        "provider_name": str(provider_name).strip(),
        "canonical_team_id": str(canonical_team_id),
        "match_method": str(match_method or "verified"),
        "confidence": float(confidence),
        "verified": True,
        "matched_at": _now(),
    }
    with bind.begin() as conn:
        updated = conn.execute(
            update(provider_team_mappings)
            .where(and_(
                provider_team_mappings.c.provider == values["provider"],
                provider_team_mappings.c.provider_team_id == values["provider_team_id"],
            ))
            .values(**values)
        ).rowcount
        if not updated:
            conn.execute(insert(provider_team_mappings).values(**values))


def save_verified_competition_mapping(
    provider: str,
    provider_competition_id: str,
    provider_name: str,
    canonical_competition_id: str,
    *,
    match_method: str,
    confidence: float,
    bind=None,
) -> None:
    bind = bind or default_engine
    values = {
        "provider": str(provider).strip().casefold(),
        "provider_competition_id": str(provider_competition_id).strip(),
        "provider_name": str(provider_name).strip(),
        "canonical_competition_id": str(canonical_competition_id),
        "match_method": str(match_method or "verified"),
        "confidence": float(confidence),
        "verified": True,
        "matched_at": _now(),
    }
    with bind.begin() as conn:
        updated = conn.execute(
            update(provider_competition_mappings)
            .where(and_(
                provider_competition_mappings.c.provider == values["provider"],
                provider_competition_mappings.c.provider_competition_id == values["provider_competition_id"],
            ))
            .values(**values)
        ).rowcount
        if not updated:
            conn.execute(insert(provider_competition_mappings).values(**values))


def canonical_candidates(*, bind=None) -> list[dict]:
    bind = bind or default_engine
    home = canonical_teams.alias("home_team")
    away = canonical_teams.alias("away_team")
    comp = canonical_competitions.alias("competition")
    query = (
        select(
            canonical_fixtures.c.id,
            canonical_fixtures.c.kickoff,
            canonical_fixtures.c.status,
            home.c.canonical_name.label("home_team"),
            away.c.canonical_name.label("away_team"),
            comp.c.canonical_name.label("competition"),
            comp.c.country.label("country"),
        )
        .select_from(
            canonical_fixtures
            .join(home, canonical_fixtures.c.home_team_id == home.c.id)
            .join(away, canonical_fixtures.c.away_team_id == away.c.id)
            .outerjoin(comp, canonical_fixtures.c.competition_id == comp.c.id)
        )
    )
    with bind.begin() as conn:
        rows = conn.execute(query).mappings().all()
    return [dict(row) for row in rows]


def _prepared_fixture(fixture: dict) -> dict | None:
    home = fixture.get("home") or {}
    away = fixture.get("away") or {}
    home_name = home.get("name") or fixture.get("home_team")
    away_name = away.get("name") or fixture.get("away_team")
    kickoff = fixture.get("commence_time") or fixture.get("kickoff")
    provider_id = fixture.get("match_id") or fixture.get("event_id") or fixture.get("fixture_id")
    if not home_name or not away_name or not kickoff or provider_id in (None, ""):
        return None
    competition = (
        fixture.get("league")
        or (fixture.get("competition") or {}).get("name")
        or fixture.get("competition_name")
        or ""
    )
    return {
        "provider_fixture_id": str(provider_id),
        "home_team": str(home_name),
        "away_team": str(away_name),
        "home_team_id": home.get("id"),
        "away_team_id": away.get("id"),
        "competition": str(competition),
        "competition_id": fixture.get("league_slug"),
        "competition_type": fixture.get("competition_type") or "",
        "country": (
            (fixture.get("venue") or {}).get("country")
            or fixture.get("country")
            or ""
        ),
        "kickoff": kickoff,
        "status": "SCHEDULED",
    }


def seed_prepared_fixture(
    fixture: dict, *, provider: str = "prepared", bind=None
) -> dict | None:
    """Persist one already-prepared production fixture as canonical identity."""
    bind = bind or default_engine
    normalized = _prepared_fixture(fixture)
    if not normalized:
        return None

    canonical = ensure_canonical_fixture(normalized, bind=bind)
    save_verified_fixture_mapping(
        provider,
        normalized["provider_fixture_id"],
        canonical["id"],
        match_method="prepared_authoritative",
        confidence=1.0,
        bind=bind,
    )

    if normalized.get("home_team_id") not in (None, ""):
        save_verified_team_mapping(
            provider,
            str(normalized["home_team_id"]),
            normalized["home_team"],
            canonical["home_team_id"],
            match_method="prepared_authoritative",
            confidence=1.0,
            bind=bind,
        )
    if normalized.get("away_team_id") not in (None, ""):
        save_verified_team_mapping(
            provider,
            str(normalized["away_team_id"]),
            normalized["away_team"],
            canonical["away_team_id"],
            match_method="prepared_authoritative",
            confidence=1.0,
            bind=bind,
        )
    if normalized.get("competition_id") and canonical.get("competition_id"):
        save_verified_competition_mapping(
            provider,
            str(normalized["competition_id"]),
            normalized["competition"],
            canonical["competition_id"],
            match_method="prepared_authoritative",
            confidence=1.0,
            bind=bind,
        )
    return canonical


def resolve_and_optionally_persist(
    provider: str,
    provider_fixture: dict,
    *,
    candidates: list[dict],
    persist_verified: bool = False,
    bind=None,
) -> dict:
    """Reuse a verified mapping first; persist only explicit high-confidence success."""
    bind = bind or default_engine
    provider_fixture_id = str(
        provider_fixture.get("sportybet_event_id")
        or provider_fixture.get("event_id")
        or provider_fixture.get("provider_fixture_id")
        or ""
    )
    existing = load_verified_fixture_mapping(
        provider, provider_fixture_id, bind=bind
    )
    mapping = {provider_fixture_id: existing} if existing else {}
    result = canonical_identity.resolve_fixture(
        provider_fixture,
        candidates,
        provider_mapping=mapping,
    )

    if (
        persist_verified
        and result.get("canonical_fixture_id")
        and result.get("state") in {
            canonical_identity.EXACT_ALIAS,
            canonical_identity.TEAM_KICKOFF,
            canonical_identity.FUZZY_VERIFIED,
        }
    ):
        save_verified_fixture_mapping(
            provider,
            provider_fixture_id,
            result["canonical_fixture_id"],
            match_method=result.get("method") or result["state"],
            confidence=float(result.get("confidence") or 0.0),
            bind=bind,
        )
    return result


def reconcile_snapshot(
    inventory: dict,
    prepared_fixtures: list[dict],
    *,
    bind=None,
) -> dict:
    """Explicit maintenance job: seed prepared identities, then persist verified SportyBet matches.

    This is intentionally not called by any request endpoint.
    """
    bind = bind or default_engine
    seeded = 0
    for fixture in prepared_fixtures or []:
        if seed_prepared_fixture(fixture, bind=bind):
            seeded += 1

    candidates = canonical_candidates(bind=bind)
    states: dict[str, int] = {}
    persisted = 0
    for fixture in inventory.get("fixtures") or []:
        before = load_verified_fixture_mapping(
            "sportybet",
            str(fixture.get("sportybet_event_id") or ""),
            bind=bind,
        )
        result = resolve_and_optionally_persist(
            "sportybet",
            fixture,
            candidates=candidates,
            persist_verified=True,
            bind=bind,
        )
        states[result["state"]] = states.get(result["state"], 0) + 1
        after = load_verified_fixture_mapping(
            "sportybet",
            str(fixture.get("sportybet_event_id") or ""),
            bind=bind,
        )
        if after and not before:
            persisted += 1

    return {
        "status": "success",
        "shadow_only": True,
        "prepared_seeded": seeded,
        "canonical_fixture_count": len(candidates),
        "sportybet_fixture_count": len(inventory.get("fixtures") or []),
        "new_verified_fixture_mappings": persisted,
        "identity_states": states,
    }
