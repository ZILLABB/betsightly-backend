"""Offline EuroLeague/EuroCup candidate guards. No network or NBA writes."""
import pytest
from basketball.research_europe_sources import (
    EUROPE, audit_season_response, probe_season, source_url,
)


def test_fixed_europe_source_paths_are_bounded():
    assert EUROPE == {"euroleague": "E", "eurocup": "U"}
    assert source_url("euroleague", 2025) == (
        "https://api-live.euroleague.net/v2/competitions/E/seasons/E2025/games"
    )
    assert source_url("eurocup", 2026).endswith("/U/seasons/U2026/games")
    for league, year in (("nba", 2025), ("euroleague", True),
                         ("eurocup", 1000), ("eurocup", 2036)):
        with pytest.raises(ValueError):
            source_url(league, year)


def test_identity_completeness_is_not_prediction_clearance():
    result = audit_season_response("euroleague", 2025, {
        "total": 3, "data": [{"id": "a"}, {"id": "b"}],
    })
    assert result["page_identities_checked"] == 2
    assert result["page_complete"] is False
    for key in ("approved_for_training", "approved_for_settlement",
                "approved_for_public_predictions", "license_cleared",
                "cross_source_finals_verified"):
        assert result[key] is False
    assert result["not_bookable"] is True


@pytest.mark.parametrize("body", [
    None, [], {"data": []}, {"total": True, "data": []},
    {"total": -1, "data": []}, {"total": 751, "data": []},
    {"total": 0, "data": [{"id": "a"}]},
    {"total": 1, "data": "garbage"},
    {"total": 2, "data": [{"id": 22}, {"id": "22"}]},
    {"total": 1, "data": [{}]},
    {"total": 1, "data": [{"id": True}]},
])
def test_source_incomplete_or_ambiguous_fails_closed(body):
    with pytest.raises(ValueError):
        audit_season_response("eurocup", 2025, body)


def test_one_read_only_network_request_no_betting():
    seen = []
    class Fake:
        status_code = 200
        content = b'{"total":1,"data":[{"id":"g1"}]}'
        def json(self):
            return {"total": 1, "data": [{"id": "g1"}]}
    def get(url, *, timeout, allow_redirects, headers):
        seen.append((url, timeout, allow_redirects, headers))
        return Fake()
    receipt = probe_season("euroleague", 2025, get=get)
    assert len(seen) == 1 and seen[0][2] is False
    assert receipt["page_complete"] is True
    assert receipt["approved_for_settlement"] is False


def test_network_failure_is_never_reported_as_coverage():
    class Fail:
        status_code = 403
        content = b""
    with pytest.raises(ValueError, match="UNAVAILABLE"):
        probe_season("eurocup", 2025, get=lambda *a, **kw: Fail())
