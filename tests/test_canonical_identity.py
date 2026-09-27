from datetime import datetime, timedelta, timezone

import pytest

from leagues import canonical_identity as ci


NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def canonical(
    fixture_id,
    home,
    away,
    *,
    kickoff=NOW,
    competition="Premier League",
):
    return {
        "id": fixture_id,
        "home_team": home,
        "away_team": away,
        "kickoff": kickoff,
        "competition": competition,
    }


def provider(
    event_id,
    home,
    away,
    *,
    kickoff=NOW,
    competition="Premier League",
):
    return {
        "sportybet_event_id": event_id,
        "home_team": home,
        "away_team": away,
        "kickoff": kickoff,
        "competition": competition,
    }


def test_verified_provider_mapping_wins():
    result = ci.resolve_fixture(
        provider("sp-1", "Anything", "Else"),
        [canonical("fx-1", "Arsenal", "Chelsea")],
        provider_mapping={"sp-1": "fx-1"},
    )

    assert result["state"] == ci.EXACT_ID
    assert result["canonical_fixture_id"] == "fx-1"
    assert result["confidence"] == 1.0


def test_exact_team_and_kickoff_match():
    result = ci.resolve_fixture(
        provider("sp-1", "Manchester United FC", "Chelsea FC"),
        [canonical("fx-1", "Man Utd", "Chelsea")],
    )

    assert result["state"] == ci.TEAM_KICKOFF
    assert result["canonical_fixture_id"] == "fx-1"


def test_verified_alias_can_resolve_different_provider_name():
    result = ci.resolve_fixture(
        provider("sp-1", "Old Trafford Reds", "Chelsea"),
        [canonical("fx-1", "Manchester United", "Chelsea")],
        aliases={
            ci.normalize_team("Old Trafford Reds"): "Manchester United",
        },
    )

    assert result["state"] == ci.EXACT_ALIAS
    assert result["canonical_fixture_id"] == "fx-1"


def test_youth_side_never_matches_senior_side():
    result = ci.resolve_fixture(
        provider("sp-1", "Ajax U19", "PSV U19"),
        [canonical("fx-1", "Ajax", "PSV")],
    )

    assert result["state"] == ci.UNMATCHED
    assert result["canonical_fixture_id"] is None


def test_wrong_orientation_does_not_match():
    result = ci.resolve_fixture(
        provider("sp-1", "Chelsea", "Arsenal"),
        [canonical("fx-1", "Arsenal", "Chelsea")],
    )

    assert result["state"] == ci.UNMATCHED


def test_kickoff_outside_tolerance_does_not_match():
    result = ci.resolve_fixture(
        provider("sp-1", "Arsenal", "Chelsea", kickoff=NOW),
        [
            canonical(
                "fx-1",
                "Arsenal",
                "Chelsea",
                kickoff=NOW + timedelta(hours=2),
            )
        ],
    )

    assert result["state"] == ci.UNMATCHED


def test_competition_mismatch_fails_closed():
    result = ci.resolve_fixture(
        provider(
            "sp-1",
            "Everton",
            "Liverpool",
            competition="Premier League",
        ),
        [
            canonical(
                "fx-1",
                "Everton",
                "Liverpool",
                competition="Friendly",
            )
        ],
    )

    assert result["state"] == ci.UNMATCHED


def test_duplicate_exact_candidates_are_ambiguous():
    fixture = provider("sp-1", "Arsenal", "Chelsea")
    result = ci.resolve_fixture(
        fixture,
        [
            canonical("fx-1", "Arsenal", "Chelsea"),
            canonical("fx-2", "Arsenal", "Chelsea"),
        ],
    )

    assert result["state"] == ci.AMBIGUOUS
    assert result["canonical_fixture_id"] is None
    assert set(result["candidates"]) == {"fx-1", "fx-2"}


def test_unmatched_fixture_is_not_forced():
    result = ci.resolve_fixture(
        provider("sp-1", "Completely Different", "Unknown Club"),
        [canonical("fx-1", "Arsenal", "Chelsea")],
    )

    assert result["state"] == ci.UNMATCHED
    assert result["canonical_fixture_id"] is None

@pytest.mark.parametrize(
    ("provider_competition", "canonical_competition"),
    [
        ("LALIGA HYPERMOTION", "LaLiga 2"),
        ("League Two", "EFL League Two"),
        ("Brasileiro Serie B", "Brasileirão Série B"),
        ("Liga DIMAYOR", "Categoría Primera A"),
        ("Primera Division", "Primera División Uruguay"),
        ("Int. Friendly Games", "International Friendly"),
        ("Primera LPF", "Liga Profesional Argentina"),
        ("League One", "EFL League One"),
        ("National Womens Soccer League", "NWSL"),
        ("Championship", "Scottish Championship"),
        ("Brasileiro Serie A", "Brasileirão Série A"),
        ("Division de Honor", "División Profesional Paraguay"),
        ("Liga Nacional", "Liga Nacional Guatemala"),
        ("Primera Division", "Primera División El Salvador"),
        ("Liga 1", "Liga 1 Perú"),
        ("Primera Division", "Primera División Chile"),
    ],
)
def test_verified_live_competition_name_equivalences(
    provider_competition,
    canonical_competition,
):
    result = ci.resolve_fixture(
        provider(
            "sp-1",
            "Example United",
            "Example City",
            competition=provider_competition,
        ),
        [
            canonical(
                "fx-1",
                "Example United",
                "Example City",
                competition=canonical_competition,
            )
        ],
    )

    assert result["state"] == ci.TEAM_KICKOFF
    assert result["canonical_fixture_id"] == "fx-1"


def test_generic_competition_label_is_not_a_wildcard():
    result = ci.resolve_fixture(
        provider(
            "sp-1",
            "Example United",
            "Example City",
            competition="Primera Division",
        ),
        [
            canonical(
                "fx-1",
                "Example United",
                "Example City",
                competition="Primera B Chile",
            )
        ],
    )

    assert result["state"] == ci.UNMATCHED
    assert result["canonical_fixture_id"] is None
