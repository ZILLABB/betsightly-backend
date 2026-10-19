"""Football-data.org v4 crest fields are retained for fixture rendering."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

from services.fixture_service import FixtureService


def _service():
    # Skip network, secrets and filesystem; exercise only the response adapter.
    service = object.__new__(FixtureService)
    service.fdo_api_key = "test-only"
    service.resolver = SimpleNamespace(resolve=lambda team: None)
    return service


def test_fdo_fixture_preserves_verified_home_and_away_crests():
    response = Mock(status_code=200)
    response.json.return_value = {
        "matches": [{
            "status": "SCHEDULED",
            "utcDate": "2026-10-19T18:00:00Z",
            "competition": {"code": "PL", "name": "Premier League"},
            "homeTeam": {
                "name": "Arsenal FC",
                "crest": "https://crests.football-data.org/57.png",
            },
            "awayTeam": {
                "name": "Chelsea FC",
                "crest": "https://crests.football-data.org/61.png",
            },
        }]
    }
    with patch("services.fixture_service.requests.get", return_value=response):
        fixtures = _service()._fetch_from_football_data_org("2026-10-19")
    assert len(fixtures) == 1
    assert fixtures[0]["home_team_logo"] == "https://crests.football-data.org/57.png"
    assert fixtures[0]["away_team_logo"] == "https://crests.football-data.org/61.png"


def test_fdo_fixture_without_crest_keeps_empty_url_without_guessing_identity():
    response = Mock(status_code=200)
    response.json.return_value = {
        "matches": [{
            "status": "SCHEDULED",
            "utcDate": "2026-10-19T19:00:00Z",
            "competition": {"code": "PL", "name": "Premier League"},
            "homeTeam": {"name": "Unknown Club", "crest": None},
            "awayTeam": {"name": "Other Club"},
        }]
    }
    with patch("services.fixture_service.requests.get", return_value=response):
        fixtures = _service()._fetch_from_football_data_org("2026-10-19")
    assert len(fixtures) == 1
    assert fixtures[0]["home_team_logo"] == ""
    assert fixtures[0]["away_team_logo"] == ""
