"""A/B rollout: no uncontrolled new markets; source outages never count as finals."""
import pytest
from growth import basketball_scheduler as scheduler
from growth import basketball_markets as markets


def test_legacy_basketball_market_scope_unmodified_without_optin(monkeypatch):
    monkeypatch.delenv("BASKETBALL_EXTENDED_MARKETS_ENABLED", raising=False)
    assert markets.market_ids() == ("219", "225")
    assert markets.parse_extended({"id": "223", "specifier": "hcp=-5.5"},
                                  "Boston Celtics", "New York Knicks") is None


def test_extended_market_stays_off_with_unknown_values(monkeypatch):
    monkeypatch.setenv("BASKETBALL_EXTENDED_MARKETS_ENABLED", "maybe")
    assert markets.market_ids() == ("219", "225")


def test_valid_handicap_research_requires_verifiable_labels(monkeypatch):
    monkeypatch.setenv("BASKETBALL_EXTENDED_MARKETS_ENABLED", "true")
    raw = {"id": "223", "desc": "Handicap incl. overtime",
           "specifier": "hcp=-5.5", "outcomes": [
               {"id": "14", "desc": "Boston Celtics", "odds": "1.93"},
               {"id": "15", "desc": "New York Knicks", "odds": "1.87"},
           ]}
    output = markets.parse_extended(raw, "Boston Celtics", "New York Knicks")
    assert output and {o["side"] for o in output["outcomes"]} == {"home", "away"}
    assert output["market_id"] == "223"
    assert markets.parse_extended({**raw, "specifier": "hcp=unpriced"},
                                  "Boston Celtics", "New York Knicks") is None
    bad = {**raw, "outcomes": [
        {"id": "14", "desc": "Boston Celtics", "odds": "1.93"},
        {"id": "15", "desc": "Boston Celtics", "odds": "1.87"},
    ]}
    assert markets.parse_extended(bad, "Boston Celtics", "New York Knicks") is None


def test_team_totals_require_correct_team_and_market_description(monkeypatch):
    monkeypatch.setenv("BASKETBALL_EXTENDED_MARKETS_ENABLED", "true")
    raw = {"id": "227", "desc": "Home Team Total Points incl. overtime",
           "specifier": "total=113.5", "outcomes": [
               {"id": "12", "desc": "Over", "odds": "1.94"},
               {"id": "13", "desc": "Under", "odds": "1.85"},
           ]}
    assert markets.parse_extended(raw, "Boston Celtics", "New York Knicks")
    assert markets.parse_extended({**raw, "desc": "Away Team Total Points"},
                                  "Boston Celtics", "New York Knicks") is None
    assert markets.parse_extended({**raw, "specifier": "total=999.5"},
                                  "Boston Celtics", "New York Knicks") is None


def test_scheduler_success_zero_and_changed_tickets():
    assert scheduler.tick(settle=lambda: {"status": "success",
                    "nba_final_legs": 0, "tickets_updated": 0})["status"] == "success"
    result = scheduler.tick(settle=lambda: {"status": "success",
                    "nba_final_legs": 2, "tickets_updated": 1})
    assert result["tickets_updated"] == 1


def test_scheduler_failure_and_partial_provider_fail_closed():
    for action in (
        lambda: (_ for _ in ()).throw(TimeoutError("provider")),
        lambda: {"status": "SCORE_PROVIDER_PARTIAL", "failures": ["yesterday"]},
        lambda: {"status": "success", "nba_final_legs": -1,
                 "tickets_updated": 1},
        lambda: {"status": "success", "nba_final_legs": True,
                 "tickets_updated": 1},
    ):
        assert scheduler.tick(settle=action)["status"] == "unavailable"
