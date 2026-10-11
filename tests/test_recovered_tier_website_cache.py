"""Recovered public tiers must not be invisible behind stale per-worker cache."""
import time

from leagues import daily_feed


def _payload(ten_selected: bool):
    return {
        "banker": {"selected": True, "games": [{"match_id": "b", "kickoff": "2099-01-01T12:00:00Z"}]},
        "2_odds": {"selected": True, "games": [{"match_id": "t", "kickoff": "2099-01-01T13:00:00Z"}]},
        "5_odds": {"selected": True, "games": [{"match_id": "f", "kickoff": "2099-01-01T14:00:00Z"}]},
        "10_odds": {"selected": ten_selected,
                    "games": ([{"match_id": "ten", "kickoff": "2099-01-01T15:00:00Z"}]
                              if ten_selected else []),
                    "total_odds": 10.17 if ten_selected else 0},
        "over_1_5": {"selected": True, "games": []},
        "rollover": {"selected": False, "games": []},
    }


def _setup(monkeypatch):
    monkeypatch.setattr(daily_feed, "_publish_date", lambda: "2026-10-11")
    monkeypatch.setattr(daily_feed, "_build_rollover",
                        lambda *a, **k: {"selected": False, "games": [], "chain_length": 0})
    monkeypatch.setattr(daily_feed, "_attach_bookings",
                        lambda _date, tiers, now=None: tiers)


def test_missing_tier_refreshes_from_locked_database_within_one_minute(monkeypatch):
    _setup(monkeypatch)
    observed = []
    monkeypatch.setattr(daily_feed, "_load_locked",
                        lambda _date: observed.append("db") or _payload(True))
    old = {"status": "success", "locked": True, "date": "2026-10-11",
           "publication_date": "2026-10-11", "accumulators": _payload(False)}
    monkeypatch.setattr(daily_feed, "_accum_cache",
                        {"result": old, "ts": time.time() - 75})
    response = daily_feed.build_daily_accumulators(allow_generation=False)
    assert observed == ["db"]
    assert response["locked"] is True
    assert response["accumulators"]["10_odds"]["selected"] is True
    assert response["accumulators"]["10_odds"]["total_odds"] == 10.17


def test_complete_locked_card_retains_normal_fifteen_minute_cache(monkeypatch):
    _setup(monkeypatch)
    old = {"status": "success", "locked": True, "date": "2026-10-11",
           "publication_date": "2026-10-11", "accumulators": _payload(True)}
    monkeypatch.setattr(daily_feed, "_accum_cache",
                        {"result": old, "ts": time.time() - 75})
    monkeypatch.setattr(daily_feed, "_load_locked",
                        lambda _date: (_ for _ in ()).throw(
                            AssertionError("no database reread before cache TTL")))
    response = daily_feed.build_daily_accumulators(allow_generation=False)
    assert response is old


def test_incomplete_card_can_still_use_short_cache_before_sixty_seconds(monkeypatch):
    _setup(monkeypatch)
    old = {"status": "success", "locked": True, "date": "2026-10-11",
           "publication_date": "2026-10-11", "accumulators": _payload(False)}
    monkeypatch.setattr(daily_feed, "_accum_cache",
                        {"result": old, "ts": time.time() - 25})
    monkeypatch.setattr(daily_feed, "_load_locked",
                        lambda _date: (_ for _ in ()).throw(
                            AssertionError("cache not expired yet")))
    assert daily_feed.build_daily_accumulators(allow_generation=False) is old
