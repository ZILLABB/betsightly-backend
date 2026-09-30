from leagues import match_context
from services.apifootball_service import APIFootballService


def _source(
    *,
    home="Arsenal",
    away="Chelsea",
    kickoff="2026-09-30T18:00:00Z",
):
    return {
        "match_id": "espn-1",
        "confidence": .82,
        "trust": {
            "trust_grade": "A",
        },
        "_fixture": {
            "home": {
                "name": home,
            },
            "away": {
                "name": away,
            },
            "commence_time": kickoff,
        },
    }


def _provider(
    *,
    fixture_id=9001,
    home="Arsenal",
    away="Chelsea",
    kickoff="2026-09-30T18:00:00+00:00",
):
    return {
        "fixture_id": fixture_id,
        "home_team": home,
        "away_team": away,
        "date": kickoff,
        "venue_id": 10,
        "venue_name": "Test Stadium",
        "venue_city": "London",
    }


def test_match_provider_fixture_requires_team_and_kickoff_agreement():
    source = _source()

    good = _provider()

    wrong_time = _provider(
        fixture_id=9002,
        kickoff="2026-09-30T23:00:00+00:00",
    )

    match = match_context.match_provider_fixture(
        source,
        [wrong_time, good],
    )

    assert match["fixture_id"] == 9001


def test_ambiguous_provider_fixture_fails_closed():
    source = _source()

    first = _provider(
        fixture_id=9001,
    )

    second = _provider(
        fixture_id=9002,
    )

    assert (
        match_context.match_provider_fixture(
            source,
            [first, second],
        )
        is None
    )


def test_unknown_context_is_neutral_shadow_state():
    source = _source()

    context = match_context.empty_match_context()

    attached = match_context.attach_shadow_context(
        source,
        context,
    )

    assert attached["confidence"] == .82
    assert attached["trust"]["trust_grade"] == "A"

    assert context["shadow_only"] is True
    assert context["match_status"] == "UNMATCHED"

    assert context["injuries"]["status"] == "UNKNOWN"
    assert context["lineups"]["status"] == "UNKNOWN"
    assert context["weather"]["status"] == "UNKNOWN"
    assert context["rest"]["status"] == "UNKNOWN"


def test_shadow_context_normalizes_injury_suspension_and_lineup_data():
    provider = _provider()

    details = {
        "lineups": [
            {
                "team": {
                    "id": 1,
                    "name": "Arsenal",
                },
                "formation": "4-3-3",
                "startXI": [{} for _ in range(11)],
            },
            {
                "team": {
                    "id": 2,
                    "name": "Chelsea",
                },
                "formation": "4-2-3-1",
                "startXI": [{} for _ in range(11)],
            },
        ]
    }

    injuries = {
        "response": [
            {
                "player": {
                    "id": 100,
                    "name": "Player A",
                },
                "team": {
                    "id": 1,
                    "name": "Arsenal",
                },
                "type": "Injury",
                "reason": "Hamstring",
            },
            {
                "player": {
                    "id": 200,
                    "name": "Player B",
                },
                "team": {
                    "id": 2,
                    "name": "Chelsea",
                },
                "type": "Suspension",
                "reason": "Suspended",
            },
        ],
        "errors": {},
    }

    context = match_context.build_shadow_context(
        provider,
        fixture_details=details,
        injuries_payload=injuries,
    )

    assert context["shadow_only"] is True
    assert context["match_status"] == "MATCHED"

    assert context["injuries"]["status"] == "AVAILABLE"
    assert context["injuries"]["count"] == 1

    assert context["suspensions"]["status"] == "AVAILABLE"
    assert context["suspensions"]["count"] == 1

    assert context["lineups"]["status"] == "AVAILABLE"
    assert context["lineups"]["confirmed"] is True

    assert context["venue"]["status"] == "AVAILABLE"


def test_empty_injury_response_does_not_mean_zero_injuries():
    context = match_context.build_shadow_context(
        _provider(),
        injuries_payload={
            "response": [],
            "errors": {},
        },
    )

    assert context["injuries"]["status"] == "UNKNOWN"
    assert context["suspensions"]["status"] == "UNKNOWN"


def test_fixture_details_are_batched_at_twenty(monkeypatch):
    service = object.__new__(
        APIFootballService
    )

    calls = []

    def fake_get(endpoint, params, use_cache=True):
        calls.append(
            (
                endpoint,
                dict(params),
            )
        )

        ids = [
            int(value)
            for value in params["ids"].split("-")
        ]

        return {
            "response": [
                {
                    "fixture": {
                        "id": value,
                    }
                }
                for value in ids
            ]
        }

    monkeypatch.setattr(
        service,
        "_get",
        fake_get,
    )

    result = service.get_fixture_details(
        list(range(1, 26))
    )

    assert len(result) == 25
    assert len(calls) == 2

    assert len(
        calls[0][1]["ids"].split("-")
    ) == 20

    assert len(
        calls[1][1]["ids"].split("-")
    ) == 5
