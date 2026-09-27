from datetime import datetime, timezone

from sqlalchemy import create_engine, func, select

from leagues import canonical_identity
from leagues import canonical_mapping_store as store


NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def db():
    bind = create_engine("sqlite:///:memory:")
    store.metadata.create_all(bind)
    return bind


def prepared():
    return {
        "match_id": "espn-1",
        "event_id": "espn-1",
        "league": "Premier League",
        "league_slug": "eng.1",
        "competition_type": "league",
        "commence_time": NOW.isoformat(),
        "home": {"id": "42", "name": "Manchester United"},
        "away": {"id": "49", "name": "Chelsea"},
        "venue": {"country": "England"},
    }


def sporty():
    return {
        "sportybet_event_id": "sb-1",
        "home_team": "Man Utd",
        "away_team": "Chelsea",
        "competition": "Premier League",
        "kickoff": NOW.isoformat(),
    }


def test_seed_prepared_fixture_is_deterministic_and_idempotent():
    bind = db()
    first = store.seed_prepared_fixture(prepared(), bind=bind)
    second = store.seed_prepared_fixture(prepared(), bind=bind)

    assert first["id"] == second["id"]
    with bind.begin() as conn:
        assert conn.execute(
            select(func.count()).select_from(store.canonical_fixtures)
        ).scalar_one() == 1
        assert conn.execute(
            select(func.count()).select_from(store.canonical_teams)
        ).scalar_one() == 2
        assert conn.execute(
            select(func.count()).select_from(store.provider_fixture_mappings)
        ).scalar_one() == 1


def test_verified_fixture_mapping_round_trips():
    bind = db()
    canonical = store.seed_prepared_fixture(prepared(), bind=bind)

    store.save_verified_fixture_mapping(
        "sportybet",
        "sb-1",
        canonical["id"],
        match_method="TEAM_KICKOFF",
        confidence=1.0,
        bind=bind,
    )

    assert store.load_verified_fixture_mapping(
        "sportybet", "sb-1", bind=bind
    ) == canonical["id"]


def test_resolver_reuses_persisted_exact_id_mapping():
    bind = db()
    canonical = store.seed_prepared_fixture(prepared(), bind=bind)
    store.save_verified_fixture_mapping(
        "sportybet",
        "sb-1",
        canonical["id"],
        match_method="verified",
        confidence=1.0,
        bind=bind,
    )

    result = store.resolve_and_optionally_persist(
        "sportybet",
        {
            "sportybet_event_id": "sb-1",
            "home_team": "Completely Different",
            "away_team": "Names",
            "competition": "Unknown",
            "kickoff": NOW.isoformat(),
        },
        candidates=store.canonical_candidates(bind=bind),
        persist_verified=False,
        bind=bind,
    )

    assert result["state"] == canonical_identity.EXACT_ID
    assert result["canonical_fixture_id"] == canonical["id"]


def test_ambiguous_resolution_is_never_persisted():
    bind = db()
    first = store.ensure_canonical_fixture({
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "competition": "Premier League",
        "country": "England",
        "kickoff": NOW,
    }, bind=bind)
    # Same teams/time but deliberately distinct competition identity with the
    # same visible name and different country context; resolver sees both as
    # equivalent provider candidates and must fail closed.
    second = dict(first)
    second["id"] = "00000000-0000-0000-0000-000000000002"
    candidates = [first, second]

    result = store.resolve_and_optionally_persist(
        "sportybet",
        {
            "sportybet_event_id": "sb-amb",
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "competition": "Premier League",
            "kickoff": NOW,
        },
        candidates=candidates,
        persist_verified=True,
        bind=bind,
    )

    assert result["state"] == canonical_identity.AMBIGUOUS
    assert store.load_verified_fixture_mapping(
        "sportybet", "sb-amb", bind=bind
    ) is None


def test_reconcile_snapshot_persists_only_verified_match():
    bind = db()
    inventory = {
        "fixtures": [
            sporty(),
            {
                "sportybet_event_id": "sb-unmatched",
                "home_team": "Unknown Alpha",
                "away_team": "Unknown Beta",
                "competition": "Unknown League",
                "kickoff": NOW.isoformat(),
            },
        ]
    }

    result = store.reconcile_snapshot(
        inventory,
        [prepared()],
        bind=bind,
    )

    assert result["prepared_seeded"] == 1
    assert result["new_verified_fixture_mappings"] == 1
    assert store.load_verified_fixture_mapping(
        "sportybet", "sb-1", bind=bind
    ) is not None
    assert store.load_verified_fixture_mapping(
        "sportybet", "sb-unmatched", bind=bind
    ) is None
