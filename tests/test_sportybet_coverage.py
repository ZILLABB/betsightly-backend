from datetime import (
    datetime,
    timedelta,
    timezone,
)

from leagues import sportybet


def _entry(
    event_id,
    home,
    away,
    kickoff,
    competition,
):
    return {
        "event_id": str(event_id),
        "home_team": home,
        "away_team": away,
        "home_squad": "",
        "away_squad": "",
        "kickoff_ms": int(
            kickoff.timestamp()
            * 1000
        ),
        "competition": competition,
        "prices": {},
        "margins": {},
        "market_refs": {},
    }


def _board(entries):
    fixtures = {}

    for entry in entries:
        key = (
            f"{sportybet._norm(entry['home_team'])}|"
            f"{sportybet._norm(entry['away_team'])}"
        )

        fixtures.setdefault(
            key,
            [],
        ).append(entry)

    return {
        "__meta__": {
            "snapshot_id": "coverage-board",
            "is_complete": True,
        },
        **fixtures,
    }


def test_registry_competition_match_requires_exact_normalized_mapping():
    exact = sportybet.registry_competition_match(
        "Premier League"
    )

    assert exact["status"] == "MAPPED_EXACT"
    assert exact["league_slug"] == "eng.1"

    unknown = sportybet.registry_competition_match(
        "Some Unverified Regional League"
    )

    assert unknown["status"] == "UNMAPPED"
    assert unknown["league_slug"] is None


def test_coverage_audit_finds_sportybet_only_fixture_without_publishing_it():
    now = datetime(
        2026,
        9,
        30,
        12,
        tzinfo=timezone.utc,
    )

    first = _entry(
        1,
        "Arsenal",
        "Chelsea",
        now + timedelta(hours=4),
        "Premier League",
    )

    missing = _entry(
        2,
        "Liverpool",
        "Everton",
        now + timedelta(hours=5),
        "Premier League",
    )

    outside = _entry(
        3,
        "Barcelona",
        "Real Madrid",
        now + timedelta(days=10),
        "LaLiga",
    )

    board = _board(
        [
            first,
            missing,
            outside,
        ]
    )

    fixtures = [{
        "match_id": "espn-1",
        "league": "Premier League",
        "league_slug": "eng.1",
        "commence_time": (
            now
            + timedelta(hours=4)
        ).isoformat(),
        "home": {
            "name": "Arsenal",
        },
        "away": {
            "name": "Chelsea",
        },
        "odds": {
            "sportybet_event_id": "1",
        },
    }]

    original = list(
        fixtures
    )

    report = sportybet.coverage_against_fixtures(
        fixtures,
        board,
        now=now,
        days_ahead=7,
    )

    assert report["publishing_changed"] is False
    assert report["model_inputs_changed"] is False

    assert report["sportybet_fixture_count"] == 2
    assert report["matched_fixture_count"] == 1
    assert report["sportybet_only_fixture_count"] == 1

    assert (
        report[
            "exact_registry_mapped_sportybet_only"
        ]
        == 1
    )

    assert (
        report[
            "sportybet_only_samples"
        ][0]["event_id"]
        == "2"
    )

    assert (
        report[
            "sportybet_only_samples"
        ][0]["mapped_league_slug"]
        == "eng.1"
    )

    # Audit is observational only.
    assert fixtures == original


def test_coverage_audit_keeps_unknown_competitions_unmapped():
    now = datetime(
        2026,
        9,
        30,
        12,
        tzinfo=timezone.utc,
    )

    unknown = _entry(
        99,
        "Alpha FC",
        "Beta FC",
        now + timedelta(hours=2),
        "Unknown Competition 123",
    )

    report = sportybet.coverage_against_fixtures(
        [],
        _board([unknown]),
        now=now,
        days_ahead=3,
    )

    assert report["sportybet_only_fixture_count"] == 1
    assert report["exact_registry_mapped_sportybet_only"] == 0
    assert report["unmapped_registry_sportybet_only"] == 1

    sample = report["sportybet_only_samples"][0]

    assert sample["competition_mapping_status"] == "UNMAPPED"
    assert sample["mapped_league_slug"] is None



def test_generic_cup_name_cannot_fake_an_exact_registry_match():
    result = sportybet.registry_competition_match(
        "NM Cup"
    )

    assert result["status"] == "UNMAPPED"
    assert result["league_slug"] is None

    # Similarity may remain visible diagnostically, but it cannot become
    # automatic identity.
    assert result["match_basis"] is None


def test_generic_liga_name_cannot_become_exact_from_token_similarity():
    result = sportybet.registry_competition_match(
        "2. Liga"
    )

    assert result["status"] != "MAPPED_EXACT"
    assert result["league_slug"] is None


def test_tournament_identity_metadata_is_preserved_when_available():
    metadata = (
        sportybet._tournament_identity_metadata({
            "id": "sr:tournament:123",
            "name": "Premier League",
            "category": {
                "id": "sr:category:1",
                "name": "England",
            },
            "country": {
                "id": "GB",
                "name": "England",
            },
        })
    )

    assert (
        metadata[
            "sportybet_tournament_id"
        ]
        == "sr:tournament:123"
    )

    assert (
        metadata[
            "sportybet_category"
        ]
        == "England"
    )

    assert (
        metadata[
            "sportybet_country"
        ]
        == "England"
    )



def test_provider_identity_disambiguates_same_competition_name():
    england = sportybet.registry_competition_match(
        "Premier League",
        tournament_id="sr:tournament:17",
        category_id="sr:category:1",
    )

    russia = sportybet.registry_competition_match(
        "Premier League",
        tournament_id="sr:tournament:203",
        category_id="sr:category:21",
    )

    assert england["status"] == "MAPPED_EXACT"
    assert england["league_slug"] == "eng.1"

    assert russia["status"] == "MAPPED_EXACT"
    assert russia["league_slug"] == "rus.1"

    assert (
        england["match_basis"]
        == "sportybet_provider_identity"
    )


def test_unknown_provider_identity_never_falls_back_to_name():
    result = sportybet.registry_competition_match(
        "Premier League",
        tournament_id="sr:tournament:unknown",
        category_id="sr:category:999",
    )

    assert result["status"] == "UNMAPPED"
    assert result["league_slug"] is None
    assert result["match_basis"] is None


def test_verified_provider_alias_can_map_different_display_name():
    result = sportybet.registry_competition_match(
        "LALIGA HYPERMOTION",
        tournament_id="sr:tournament:54",
        category_id="sr:category:32",
    )

    assert result["status"] == "MAPPED_EXACT"
    assert result["league_slug"] == "esp.2"
    assert result["league"] == "LaLiga 2"


def test_provider_identity_maps_verified_efl_levels():
    expectations = {
        ("sr:tournament:18", "sr:category:1"): "eng.2",
        ("sr:tournament:24", "sr:category:1"): "eng.3",
        ("sr:tournament:25", "sr:category:1"): "eng.4",
    }

    for (
        tournament_id,
        category_id,
    ), slug in expectations.items():
        result = sportybet.registry_competition_match(
            "different provider label",
            tournament_id=tournament_id,
            category_id=category_id,
        )

        assert result["status"] == "MAPPED_EXACT"
        assert result["league_slug"] == slug
