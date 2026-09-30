from datetime import datetime, timezone
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



def test_rest_context_reports_fixture_congestion_without_changing_form():
    from leagues.team_history import HistoryIndex

    history = HistoryIndex({
        "matches": [
            {
                "date": "2026-09-26T18:00:00Z",
                "home": "Arsenal",
                "away": "Leeds",
                "hs": 2,
                "as": 0,
                "team_type": "CLUB",
            },
            {
                "date": "2026-09-23T18:00:00Z",
                "home": "Everton",
                "away": "Arsenal",
                "hs": 1,
                "as": 1,
                "team_type": "CLUB",
            },
            {
                "date": "2026-09-20T18:00:00Z",
                "home": "Arsenal",
                "away": "Fulham",
                "hs": 3,
                "as": 1,
                "team_type": "CLUB",
            },
            {
                "date": "2026-09-17T18:00:00Z",
                "home": "Chelsea",
                "away": "Arsenal",
                "hs": 0,
                "as": 1,
                "team_type": "CLUB",
            },
        ]
    })

    result = history.rest_context(
        "Arsenal",
        "2026-09-30T18:00:00Z",
    )

    assert result["status"] == "AVAILABLE"
    assert result["days_since_last_match"] == 4.0
    assert result["matches_last_14_days"] == 4
    assert result["fixture_congestion"] is True
    assert result["short_rest"] is False


def test_context_shortlist_uses_only_bookable_fixtures():
    fixtures = [
        {
            "match_id": "m1",
            "commence_time": "2026-09-30T18:00:00Z",
        },
        {
            "match_id": "m2",
            "commence_time": "2026-09-30T19:00:00Z",
        },
    ]

    picks = [
        {
            "match_id": "m1",
            "bookable": True,
            "confidence": .76,
        },
        {
            "match_id": "m2",
            "bookable": False,
            "confidence": .99,
        },
    ]

    selected = match_context.shortlist_context_fixtures(
        fixtures,
        picks,
    )

    assert [
        fixture["match_id"]
        for fixture in selected
    ] == ["m1"]


def test_enrich_prepared_context_batches_provider_data_and_keeps_quality():
    fixtures = [
        {
            "match_id": "m1",
            "home": {"name": "Arsenal"},
            "away": {"name": "Chelsea"},
            "commence_time": "2026-09-30T18:00:00Z",
        },
        {
            "match_id": "m2",
            "home": {"name": "Liverpool"},
            "away": {"name": "Everton"},
            "commence_time": "2026-09-30T19:00:00Z",
        },
    ]

    picks = [
        {
            "selection_id": "s1",
            "match_id": "m1",
            "bookable": True,
            "confidence": .82,
            "trust": {"trust_grade": "A"},
        },
        {
            "selection_id": "s2",
            "match_id": "m2",
            "bookable": True,
            "confidence": .80,
            "trust": {"trust_grade": "A"},
        },
    ]

    class FakeService:
        def __init__(self):
            self.details_calls = []
            self.injury_calls = []

        def get_daily_fixtures(self, target_date):
            assert target_date == "2026-09-30"

            return [
                {
                    "fixture_id": 9001,
                    "home_team": "Arsenal",
                    "away_team": "Chelsea",
                    "date": "2026-09-30T18:00:00+00:00",
                    "venue_name": "Emirates Stadium",
                    "venue_city": "London",
                },
                {
                    "fixture_id": 9002,
                    "home_team": "Liverpool",
                    "away_team": "Everton",
                    "date": "2026-09-30T19:00:00+00:00",
                    "venue_name": "Anfield",
                    "venue_city": "Liverpool",
                },
            ]

        def get_fixture_details(self, ids):
            self.details_calls.append(list(ids))

            return [
                {
                    "fixture": {"id": 9001},
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
                    ],
                },
                {
                    "fixture": {"id": 9002},
                    "lineups": [],
                },
            ]

        def get_fixtures_injuries(self, ids):
            self.injury_calls.append(list(ids))

            return {
                "response": [
                    {
                        "fixture": {"id": 9001},
                        "player": {
                            "id": 11,
                            "name": "Player One",
                        },
                        "team": {
                            "id": 1,
                            "name": "Arsenal",
                        },
                        "type": "Injury",
                        "reason": "Knock",
                    },
                ],
                "errors": {},
            }

    service = FakeService()

    summary = match_context.enrich_prepared_context(
        fixtures,
        picks,
        service=service,
    )

    assert summary["shadow_only"] is True
    assert summary["matched_fixture_count"] == 2

    assert service.details_calls == [
        [9001, 9002]
    ]

    assert service.injury_calls == [
        [9001, 9002]
    ]

    # Shadow context cannot rewrite prediction quality.
    assert picks[0]["confidence"] == .82
    assert picks[0]["trust"]["trust_grade"] == "A"

    assert (
        picks[0]["match_context"]["lineups"]["status"]
        == "AVAILABLE"
    )

    assert (
        picks[0]["match_context"]["injuries"]["status"]
        == "AVAILABLE"
    )


def test_decision_archive_keeps_shadow_context():
    from leagues.decision_archive import _compact_candidate

    context = match_context.empty_match_context(
        "test"
    )

    pick = {
        "match_id": "m1",
        "market": "over_1_5",
        "prediction": "Over 1.5",
        "match_context": context,
        "_fixture": {
            "home": {"name": "A"},
            "away": {"name": "B"},
            "league": "Test",
            "league_slug": "test",
            "commence_time": "2026-09-30T18:00:00Z",
        },
        "_model": {},
    }

    compact = _compact_candidate(
        pick
    )

    assert (
        compact["match_context"]["shadow_only"]
        is True
    )



def test_weather_at_kickoff_selects_nearest_forecast_hour():
    from services.weather_service import (
        weather_at_kickoff,
    )

    payload = {
        "location": {
            "name": "London",
        },
        "forecast": {
            "forecastday": [
                {
                    "date": "2026-09-30",
                    "hour": [
                        {
                            "time_epoch": 1790791200,
                            "temp_c": 18.0,
                            "feelslike_c": 17.5,
                            "precip_mm": 2.1,
                            "chance_of_rain": 70,
                            "chance_of_snow": 0,
                            "wind_kph": 22.0,
                            "gust_kph": 31.0,
                            "humidity": 81,
                            "condition": {
                                "text": "Light rain",
                                "code": 1183,
                            },
                        }
                    ],
                }
            ],
        },
    }

    kickoff = datetime.fromtimestamp(
        1790791200,
        timezone.utc,
    ).isoformat()

    result = weather_at_kickoff(
        payload,
        kickoff,
    )

    assert result["status"] == "AVAILABLE"
    assert result["temperature_c"] == 18.0
    assert result["precip_mm"] == 2.1
    assert result["wind_kph"] == 22.0
    assert result["condition"] == "Light rain"


def test_weather_outside_forecast_window_stays_unknown():
    from services.weather_service import (
        weather_at_kickoff,
    )

    payload = {
        "forecast": {
            "forecastday": []
        }
    }

    result = weather_at_kickoff(
        payload,
        "2026-10-06T18:00:00Z",
    )

    assert result["status"] == "UNKNOWN"
    assert (
        result["reason"]
        == "kickoff_outside_forecast_window"
    )


def test_context_coverage_counts_only_available_sections():
    fixtures = [
        {
            "match_context": {
                "injuries": {
                    "status": "AVAILABLE",
                },
                "suspensions": {
                    "status": "AVAILABLE",
                },
                "lineups": {
                    "status": "UNKNOWN",
                },
                "rest": {
                    "status": "AVAILABLE",
                },
                "weather": {
                    "status": "AVAILABLE",
                },
                "venue": {
                    "status": "AVAILABLE",
                },
            }
        },
        {
            "match_context": {
                "injuries": {
                    "status": "UNKNOWN",
                },
                "suspensions": {
                    "status": "UNKNOWN",
                },
                "lineups": {
                    "status": "AVAILABLE",
                },
                "rest": {
                    "status": "AVAILABLE",
                },
                "weather": {
                    "status": "UNKNOWN",
                },
                "venue": {
                    "status": "AVAILABLE",
                },
            }
        },
    ]

    result = match_context._context_coverage(
        fixtures
    )

    assert result["fixture_count"] == 2

    assert (
        result["available_counts"]["rest"]
        == 2
    )

    assert (
        result["coverage"]["weather"]
        == .5
    )

    assert (
        result["coverage"]["lineups"]
        == .5
    )


def test_enrichment_weather_remains_shadow_only():
    fixtures = [
        {
            "match_id": "m-weather",
            "home": {"name": "Arsenal"},
            "away": {"name": "Chelsea"},
            "commence_time": "2026-09-30T18:00:00Z",
        }
    ]

    picks = [
        {
            "selection_id": "s-weather",
            "match_id": "m-weather",
            "bookable": True,
            "confidence": .84,
            "selection_probability": .79,
            "quality_score": 91.0,
            "trust": {
                "trust_grade": "A",
            },
        }
    ]

    class Football:
        def get_daily_fixtures(self, date):
            return [
                {
                    "fixture_id": 5001,
                    "home_team": "Arsenal",
                    "away_team": "Chelsea",
                    "date": "2026-09-30T18:00:00+00:00",
                    "venue_city": "London",
                    "country_name": "England",
                }
            ]

        def get_fixture_details(self, ids):
            return []

        def get_fixtures_injuries(self, ids):
            return {
                "response": [],
                "errors": {},
            }

    class Weather:
        def forecast(self, location, days=3):
            assert location == "London, England"
            assert days == 3

            kickoff_epoch = int(
                datetime(
                    2026,
                    9,
                    30,
                    18,
                    tzinfo=timezone.utc,
                ).timestamp()
            )

            return {
                "forecast": {
                    "forecastday": [
                        {
                            "hour": [
                                {
                                    "time_epoch": kickoff_epoch,
                                    "temp_c": 13.0,
                                    "wind_kph": 35.0,
                                    "gust_kph": 48.0,
                                    "precip_mm": 4.0,
                                    "chance_of_rain": 90,
                                    "humidity": 88,
                                    "condition": {
                                        "text": "Heavy rain",
                                        "code": 1195,
                                    },
                                }
                            ]
                        }
                    ]
                }
            }

    summary = match_context.enrich_prepared_context(
        fixtures,
        picks,
        service=Football(),
        weather_service=Weather(),
    )

    assert (
        picks[0]["match_context"]["weather"]["status"]
        == "AVAILABLE"
    )

    # Severe-looking weather is still observation only.
    assert picks[0]["confidence"] == .84
    assert picks[0]["selection_probability"] == .79
    assert picks[0]["quality_score"] == 91.0
    assert picks[0]["trust"]["trust_grade"] == "A"

    assert (
        summary["coverage"]["coverage"]["weather"]
        == 1.0
    )

