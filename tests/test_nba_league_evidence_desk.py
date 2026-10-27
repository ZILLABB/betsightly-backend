"""Read-only, protected WNBA/NCAA probe acceptance; never uses network."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException, Response


def _date(days):
    return (datetime.now(timezone.utc).date() + timedelta(days=days)).strftime("%Y%m%d")


def test_league_probe_refuses_disabled_stage(monkeypatch):
    from growth import api
    monkeypatch.setattr(api, "_nba_health_enabled", lambda: False)
    with pytest.raises(HTTPException) as error:
        api.nba_private_league_sources(Response(), "wnba", _date(-1))
    assert error.value.status_code == 404


@pytest.mark.parametrize("league,day", [
    ("nba", "20261026"), ("euroleague", "20261026"),
    ("wnba", "2026-10-26"), ("wnba", "20260230"),
    ("wnba", "20261301"), ("wnba", "00000000"),
])
def test_league_probe_refuses_unlisted_or_malformed_inputs(monkeypatch, league, day):
    from growth import api
    monkeypatch.setattr(api, "_nba_health_enabled", lambda: True)
    with pytest.raises(HTTPException) as error:
        api.nba_private_league_sources(Response(), league, day)
    assert error.value.status_code == 422


def test_league_probe_rejects_future_and_unbounded_history(monkeypatch):
    from growth import api
    monkeypatch.setattr(api, "_nba_health_enabled", lambda: True)
    for day in (_date(1), _date(-371)):
        with pytest.raises(HTTPException) as error:
            api.nba_private_league_sources(Response(), "ncaa_men", day)
        assert error.value.status_code == 422


def test_league_probe_one_day_provenance_without_writes(monkeypatch):
    from growth import api
    from basketball import research_other_league_sources as sources
    monkeypatch.setattr(api, "_nba_health_enabled", lambda: True)
    observed = []
    def fake_probe(league, day):
        observed.append((league, day))
        return {"league": league, "requested_date": day, "source_status": "one_day_probed",
                "candidate_finals": [], "research_only": True, "not_bookable": True,
                "approved_for_model_training": False,
                "approved_for_non_nba_booking_settlement": False}
    monkeypatch.setattr(sources, "probe_candidate_source", fake_probe)
    response = Response()
    report = api.nba_private_league_sources(response, "ncaa_women", _date(-2))
    assert observed == [("ncaa_women", _date(-2))]
    assert report["not_bookable"] is True
    assert report["approved_for_model_training"] is False
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"


def test_provider_rejection_stays_fail_closed(monkeypatch):
    from growth import api
    from basketball import research_other_league_sources as sources
    monkeypatch.setattr(api, "_nba_health_enabled", lambda: True)
    monkeypatch.setattr(sources, "probe_candidate_source", lambda *_: (_ for _ in ()).throw(ValueError("provider")))
    with pytest.raises(HTTPException) as error:
        api.nba_private_league_sources(Response(), "wnba", _date(-4))
    assert error.value.status_code == 503
