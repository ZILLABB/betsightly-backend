"""Non-NBA source candidates never become approved predictions or bookings."""
import pytest
from basketball.research_other_league_sources import (
    CANDIDATES, audit_candidate_payload, parse_candidate_final, source_url,
)


def fixture():
    return {
        "id": "445566",
        "date": "2026-06-05T23:30:00Z",
        "status": {"type": {"completed": True}},
        "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": "12", "displayName": "Las Vegas Aces"}, "score": "89"},
            {"homeAway": "away", "team": {"id": "13", "displayName": "New York Liberty"}, "score": "85"},
        ]}],
    }


def test_candidate_url_is_fixed_espn_host_and_only_whitelisted_leagues():
    assert len(CANDIDATES) == 4
    for league in CANDIDATES:
        assert source_url(league, "20261027").startswith("https://site.api.espn.com/")
    with pytest.raises(ValueError):
        source_url("football", "20261027")
    with pytest.raises(ValueError):
        source_url("wnba", "20261027&secret=http://other")


def test_womens_basketball_final_is_research_only_candidate():
    obj = parse_candidate_final("wnba", fixture())
    assert obj and obj["total"] == 174
    assert obj["research_only"] is True
    assert obj["not_bookable"] is True
    assert obj["validation_status"] == "source_candidate_not_model_approved"
    report = audit_candidate_payload("wnba", {"events": [fixture()]})
    assert report["exact_completed"] == 1
    assert report["approved_for_model_training"] is False
    assert report["approved_for_non_nba_booking_settlement"] is False


@pytest.mark.parametrize("change", [
    {"status": {"type": {"completed": False}}},
    {"date": "garbage"},
    {"id": "invalid-id"},
    {"competitions": []},
    {"competitions": [{"competitors": []}]},
])
def test_unverified_game_is_not_final(change):
    assert parse_candidate_final("wnba", {**fixture(), **change}) is None


def test_missing_score_and_duplicate_ids_fail_closed():
    data = fixture()
    data["competitions"][0]["competitors"][0]["score"] = "unknown"
    assert parse_candidate_final("ncaa_women", data) is None
    with pytest.raises(ValueError, match="DUPLICATED"):
        audit_candidate_payload("ncaa_men", {"events": [fixture(), fixture()]})


def test_oversized_and_missing_provider_pages_not_claimed():
    with pytest.raises(ValueError):
        audit_candidate_payload("wnba", {"events": None})
    with pytest.raises(ValueError):
        audit_candidate_payload("wnba", {"events": [fixture()] * 101})


def test_single_day_source_probe_uses_only_fixed_host_and_no_storage():
    from basketball.research_other_league_sources import probe_candidate_source
    seen = []
    class Response:
        status_code = 200
        content = b'{"events":[]}'
        def json(self):
            return {"events": [fixture()]}
    def get(url, *, timeout, allow_redirects):
        seen.append((url, timeout, allow_redirects))
        return Response()
    result = probe_candidate_source("wnba", "20261027", get=get)
    assert result["exact_completed"] == 1
    assert result["approved_for_model_training"] is False
    assert len(seen) == 1
    assert seen[0][0] == source_url("wnba", "20261027")
    assert seen[0][2] is False


def test_provider_failure_does_not_approve_other_leagues():
    from basketball.research_other_league_sources import probe_candidate_source
    class Unavailable:
        status_code = 503
        content = b''
    with pytest.raises(ValueError, match="UNAVAILABLE"):
        probe_candidate_source("ncaa_men", "20261027",
            get=lambda *args, **kwargs: Unavailable())
