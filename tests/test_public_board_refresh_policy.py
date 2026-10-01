"""A public request must never allocate the prediction pipeline in production."""

import time
from datetime import datetime, timedelta, timezone

from leagues import builder_v2, engine


def test_production_cold_builder_cannot_start_pipeline(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOW_INTERACTIVE_BOARD_REFRESH", "true")
    monkeypatch.setattr(engine, "_PERSISTENCE_HYDRATED", True)
    monkeypatch.setattr(engine, "_CACHE", {"entries": {}, "healthy_entries": {}})
    monkeypatch.setattr(engine, "run_pipeline", lambda *a, **k: (
        (_ for _ in ()).throw(AssertionError("pipeline started from web request"))
    ))
    monkeypatch.setattr(engine.threading, "Thread", lambda *a, **k: (
        (_ for _ in ()).throw(AssertionError("refresh thread started"))
    ))

    result = builder_v2.generate_v2({
        "mode": "game_count", "game_count": 5, "horizon": "7_days",
    })
    assert result["status"] == "unavailable"
    assert result["reason"] == "board_refreshing"
    assert result["retryable"] is True
    assert result["refresh_started"] is False
    assert engine.start_prepared_board_refresh() is False
    assert engine.start_history_prewarm(request_triggered=True) is False


def test_staging_interactive_refresh_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.delenv("ALLOW_INTERACTIVE_BOARD_REFRESH", raising=False)
    assert engine.interactive_refresh_allowed() is False
    monkeypatch.setenv("ALLOW_INTERACTIVE_BOARD_REFRESH", "true")
    assert engine.interactive_refresh_allowed() is True


def test_scheduler_history_prewarm_remains_available_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(engine, "_HISTORY_PREWARMING", False)
    launched = []

    class DeferredThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            launched.append(self.target)

    monkeypatch.setattr(engine.threading, "Thread", DeferredThread)
    assert engine.start_history_prewarm() is True
    assert len(launched) == 1
    assert engine.start_history_prewarm(request_triggered=True) is False


def test_one_seven_day_board_filters_all_public_horizons(monkeypatch):
    monkeypatch.setattr(engine, "_PERSISTENCE_HYDRATED", True)
    monkeypatch.setattr(engine, "_CACHE", {"entries": {}, "healthy_entries": {}})
    now = datetime.now(timezone.utc)
    fixtures = [
        {"match_id": str(day), "commence_time": (now + timedelta(days=day)).isoformat()}
        for day in (0.5, 2, 5)
    ]
    picks = [{"match_id": fixture["match_id"]} for fixture in fixtures]
    engine._store_cache_entry(7, picks, fixtures, time.time(), now,
                              {"complete": True})

    for horizon, expected in ((1, 1), (3, 2), (7, 3)):
        selected_picks, selected_fixtures, board = engine.prepared_board(horizon)
        assert len(selected_picks) == expected
        assert len(selected_fixtures) == expected
        assert board["ready"] is True
        assert board["requested_days"] == 7


def test_production_stale_board_remains_usable_without_refresh(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(engine, "_PERSISTENCE_HYDRATED", True)
    monkeypatch.setattr(engine, "_CACHE", {"entries": {}, "healthy_entries": {}})
    now = datetime.now(timezone.utc)
    fixtures = [
        {"match_id": "started", "commence_time": (now - timedelta(minutes=5)).isoformat()},
        {"match_id": "future", "commence_time": (now + timedelta(hours=2)).isoformat()},
    ]
    picks = [{"match_id": item["match_id"]} for item in fixtures]
    engine._store_cache_entry(7, picks, fixtures, time.time() - engine._TTL - 1,
                              now, {"complete": True})
    selected_picks, selected_fixtures, board = engine.prepared_board(1)
    assert [item["match_id"] for item in selected_fixtures] == ["future"]
    assert [item["match_id"] for item in selected_picks] == ["future"]
    assert board["stale"] is True
    assert engine.start_prepared_board_refresh() is False


def test_prepared_cache_retains_only_bounded_horizons(monkeypatch):
    monkeypatch.setattr(engine, "_PERSISTENCE_HYDRATED", True)
    monkeypatch.setattr(engine, "_CACHE", {"entries": {}, "healthy_entries": {}})
    now = datetime.now(timezone.utc)
    for horizon in range(1, 8):
        fixture = {"match_id": str(horizon),
                   "commence_time": (now + timedelta(hours=2)).isoformat()}
        engine._store_cache_entry(horizon, [], [fixture], time.time() + horizon,
                                  now, {"complete": True})
    assert len(engine._CACHE["entries"]) == engine._MAX_CACHED_HORIZONS
    assert len(engine._CACHE["healthy_entries"]) == engine._MAX_CACHED_HORIZONS
    assert 7 in engine._CACHE["entries"]
    for horizon in (8, 9):
        fixture = {"match_id": str(horizon),
                   "commence_time": (now + timedelta(hours=2)).isoformat()}
        engine._store_cache_entry(horizon, [], [fixture], time.time() + horizon,
                                  now, {"complete": True})
    assert 7 in engine._CACHE["entries"]


def test_public_prepared_read_cannot_launch_production_refresh(monkeypatch):
    from fastapi import HTTPException
    from leagues import api, history_readiness

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(engine, "_PERSISTENCE_HYDRATED", True)
    monkeypatch.setattr(engine, "_CACHE", {"entries": {}, "healthy_entries": {}})
    monkeypatch.setattr(history_readiness, "status",
                        lambda: {"usable": True, "state": "READY"})
    monkeypatch.setattr(engine, "run_pipeline", lambda *a, **k: (
        (_ for _ in ()).throw(AssertionError("pipeline started"))
    ))
    with __import__("pytest").raises(HTTPException) as error:
        api._public_prepared_board(3)
    assert error.value.status_code == 503
    assert error.value.detail["reason"] == "board_refreshing"
    assert error.value.detail["refresh_started"] is False


def test_builder_response_caches_are_bounded_without_dropping_active_lock():
    import asyncio
    from leagues import api

    cache = {index: {"ts": float(index), "result": {"games": [index]}}
             for index in range(api._MAX_BUILDER_CACHE_ENTRIES + 5)}
    active = asyncio.Lock()
    asyncio.run(active.acquire())
    locks = {0: active, 1: asyncio.Lock()}
    api._prune_builder_results(cache, locks, 100.0)
    assert len(cache) <= api._MAX_BUILDER_CACHE_ENTRIES
    assert locks.get(0) is active
    assert 1 not in locks


def test_production_coverage_report_cannot_force_pipeline(monkeypatch):
    import asyncio
    import pytest
    from fastapi import HTTPException
    from leagues import api

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(engine, "run_pipeline", lambda *a, **k: (
        (_ for _ in ()).throw(AssertionError("coverage request started pipeline"))
    ))
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.competition_coverage(refresh=True))
    assert error.value.status_code == 409
    assert error.value.detail["reason"] == "board_refresh_requires_worker"


def test_legacy_accumulator_get_reads_locked_card_without_generation(monkeypatch):
    from api.endpoints import accumulators
    from leagues import daily_feed

    class EmptyLegacyDb:
        def query(self, _model):
            return self

        def filter(self, _condition):
            return self

        def first(self):
            return None

    calls = []

    def read_only_card(*args, **kwargs):
        calls.append(kwargs)
        assert kwargs.get("allow_generation") is False
        return {"status": "success", "accumulators": {}}

    monkeypatch.setattr(daily_feed, "build_daily_accumulators", read_only_card)
    result = accumulators.get_todays_accumulators(EmptyLegacyDb())
    assert result["status"] == "success"
    assert calls == [{"allow_generation": False}]
