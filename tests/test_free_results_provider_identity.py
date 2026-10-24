"""No-cost API-Football *free-tier* fixture-ID bridge; offline tests only.

The actual API account is currently disabled in production, and this file
does not issue requests, change settlements or enable a paid plan.
"""
from services.independent_result_provider import (
    chunk_ids, normalize_observations, parse_api_football_fixture,
    readiness, unique_fixture_links, verified_final_for_link,
)
import pytest


def fixture(state="NS", *, date="2026-10-23T19:00:00Z",
            event=325982, home="Manchester United",
            away="Liverpool", fulltime=None, league=39):
    return {
        "fixture": {"id": event, "date": date, "status": {"short": state}},
        "league": {"id": league, "name": "Premier League"},
        "teams": {
            "home": {"id": 33, "name": home},
            "away": {"id": 40, "name": away},
        },
        "score": {"fulltime": fulltime},
        "goals": {"home": 5, "away": 4},
    }


def pick():
    return {
        "match_id": "sportybet:sr:match:554",
        "sportybet_event_id": "sr:match:554",
        "home_team": "Man Utd", "away_team": "Liverpool",
        "kickoff": "2026-10-23T19:00:00Z",
        "api_football_league_id": 39,
        "league": "Premier League", "status": "pending",
    }


def test_provider_id_link_can_be_created_from_pregame_fixture():
    pre = parse_api_football_fixture(fixture("NS"))
    assert pre["score_90"] is None and pre["completed"] is False
    links = unique_fixture_links([pick()], [pre])
    assert links["sportybet:sr:match:554"]["event_id"] == "325982"
    assert links["sportybet:sr:match:554"]["score_verified"] is False
    assert verified_final_for_link(
        pick(), links["sportybet:sr:match:554"], [pre]
    ) is None
    assert readiness([pick()], [pre])["strict_verified_90min_finals"] == 0


def test_only_explicit_90_minute_score_can_grade_a_link():
    pre = parse_api_football_fixture(fixture("NS"))
    link = unique_fixture_links([pick()], [pre])[pick()["match_id"]]
    final = parse_api_football_fixture(fixture(
        "FT", fulltime={"home": 2, "away": 1}
    ))
    evidence = verified_final_for_link(pick(), link, [final])
    assert evidence["provider"] == "api-football"
    assert evidence["score_90"] == {"home": 2, "away": 1}
    assert evidence["provider_event_id"] == "325982"


def test_extra_time_does_not_use_goals_instead_of_regulation():
    observed = parse_api_football_fixture(fixture(
        "AET", fulltime={"home": 1, "away": 1}
    ))
    assert observed["score_90"] == {"home": 1, "away": 1}
    no_90 = parse_api_football_fixture(fixture(
        "PEN", fulltime=None
    ))
    assert no_90["completed"] is False


def test_ambiguous_reversed_wrong_kickoff_or_wrong_league_not_linked():
    original = parse_api_football_fixture(fixture())
    for entry in (
        fixture(home="Liverpool", away="Manchester United"),
        fixture(date="2026-10-24T19:00:00Z"),
        fixture(league=48),
    ):
        assert unique_fixture_links([pick()], [
            parse_api_football_fixture(entry)
        ]) == {}
    assert unique_fixture_links([pick()], [
        original, parse_api_football_fixture(fixture(event=325983))
    ]) == {}


def test_conflicting_or_invalid_scores_must_not_settle():
    pre = parse_api_football_fixture(fixture())
    link = unique_fixture_links([pick()], [pre])[pick()["match_id"]]
    for state in ("NS", "1H", "PST", "ABD", "SUSP"):
        row = parse_api_football_fixture(fixture(
            state, fulltime={"home": 1, "away": 0}
        ))
        assert verified_final_for_link(pick(), link, [row]) is None
    wrong = parse_api_football_fixture(fixture(
        "FT", event=999, fulltime={"home": 1, "away": 0}
    ))
    assert verified_final_for_link(pick(), link, [wrong]) is None
    incomplete = parse_api_football_fixture(fixture(
        "FT", fulltime={"home": 2, "away": None}
    ))
    assert verified_final_for_link(pick(), link, [incomplete]) is None


def test_failed_quota_is_not_interpreted_as_no_games():
    with pytest.raises(ValueError):
        normalize_observations({"errors": {"quota": "exceeded"}, "response": []})
    assert normalize_observations({"errors": [], "response": []}) == []
    with pytest.raises(ValueError):
        normalize_observations({"response": None})


def test_free_tier_requests_are_bounded_into_batched_ids():
    assert chunk_ids(["12", "11", "12", "wrong"]) == ["11-12"]
    assert chunk_ids([str(i) for i in range(1, 26)]) == [
        "-".join(str(i) for i in range(1, 21)),
        "-".join(str(i) for i in range(21, 26)),
    ]
    with pytest.raises(ValueError):
        chunk_ids(["1"], size=21)
