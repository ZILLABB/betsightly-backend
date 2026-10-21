"""LiveScore may settle only under explicit commercial + FT-field authorisation."""
from datetime import datetime, timezone

from leagues.licensed_livescore_settlement import (
    licensed_for_settlement, licensed_livescore_finals,
)

NOW = datetime(2026, 10, 21, 0, 15, tzinfo=timezone.utc)


def _pick():
    return {"home_team": "Roma", "away_team": "Slovan Bratislava",
            "kickoff": "2026-10-20T19:00:00+00:00", "market": "home_win"}


def _observation(**overrides):
    base = {
        "provider_event_id": "719923",
        "home_team": "AS Roma",
        "away_team": "Slovan Bratislava",
        "kickoff_utc": "2026-10-20T19:00:00+00:00",
        "home_score": 4, "away_score": 0,
        "regulation_home_score": 4, "regulation_away_score": 0,
        "date": "2026-10-20", "source": "livescore-cdn",
        "state": "post", "detail": "FT", "finished": True,
        "live": False, "provisional": True, "score_verified": False,
    }
    base.update(overrides)
    return base


def _authorize(monkeypatch):
    monkeypatch.setenv("LIVESCORE_CDN_ENABLED", "true")
    monkeypatch.setenv("LIVESCORE_CDN_USAGE_AUTHORIZED", "true")
    monkeypatch.setenv("LIVESCORE_SETTLEMENT_LICENSE_VERIFIED", "true")
    monkeypatch.setenv("LIVESCORE_90MIN_FIELDS_VERIFIED", "true")


def test_commercial_settlement_not_enabled_with_display_only_access(monkeypatch):
    from leagues import authorized_livescore
    monkeypatch.setenv("LIVESCORE_CDN_ENABLED", "true")
    monkeypatch.setenv("LIVESCORE_CDN_USAGE_AUTHORIZED", "true")
    monkeypatch.delenv("LIVESCORE_SETTLEMENT_LICENSE_VERIFIED", raising=False)
    monkeypatch.delenv("LIVESCORE_90MIN_FIELDS_VERIFIED", raising=False)
    monkeypatch.setattr(authorized_livescore, "snapshot", lambda _: 1 / 0)
    assert not licensed_for_settlement()
    assert licensed_livescore_finals([_pick()], now=NOW) == []


def test_explicitly_authorized_clean_regulation_ft_can_settle(monkeypatch):
    from leagues import authorized_livescore
    _authorize(monkeypatch)
    monkeypatch.setattr(authorized_livescore, "snapshot", lambda days: {
        "status": "ok", "matches": [_observation()], "dates": days,
    })
    rows = licensed_livescore_finals([_pick()], now=NOW)
    assert len(rows) == 1
    assert rows[0]["provider"] == "livescore-licensed"
    assert rows[0]["home_score"] == 4
    assert rows[0]["score_90"] == {"home": 4, "away": 0}


def test_extra_time_provisional_live_and_unknown_regulation_are_rejected(monkeypatch):
    from leagues import authorized_livescore
    _authorize(monkeypatch)
    observations = [
        _observation(provider_event_id="1", regulation_home_score=3),
        _observation(provider_event_id="2", regulation_home_score=None),
        _observation(provider_event_id="3", state="in", live=True, finished=False),
        _observation(provider_event_id="4", detail="AET"),
        _observation(provider_event_id="5", home_team="Roma Women"),
    ]
    monkeypatch.setattr(authorized_livescore, "snapshot", lambda days: {
        "status": "ok", "matches": observations,
    })
    assert licensed_livescore_finals([_pick()], now=NOW) == []


def test_same_team_distinct_event_ids_are_not_guessed(monkeypatch):
    from leagues import authorized_livescore
    _authorize(monkeypatch)
    monkeypatch.setattr(authorized_livescore, "snapshot", lambda dates: {
        "status": "ok", "matches": [
            _observation(provider_event_id="1"),
            _observation(provider_event_id="2"),
        ],
    })
    assert licensed_livescore_finals([_pick()], now=NOW) == []


def test_fast_collector_does_not_call_unlicensed_livescore(monkeypatch):
    from leagues import fast_settlement
    monkeypatch.delenv("LIVESCORE_SETTLEMENT_LICENSE_VERIFIED", raising=False)
    monkeypatch.setattr(fast_settlement, "collect_recent_verified_finals",
                        lambda *args, **kw: ({}, "espn-rapid"))
    scores, source = fast_settlement.collect_rapid_verified_finals(
        [_pick()], now=NOW,
    )
    assert scores == {}
    assert source == "espn-rapid"
