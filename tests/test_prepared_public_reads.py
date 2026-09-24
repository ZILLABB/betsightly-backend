"""Public read paths must not rebuild the football universe."""

import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from leagues import api, engine, history_readiness


def _entry(monkeypatch, *, stale=False, degraded=False):
    now = datetime.now(timezone.utc)
    future = (now + timedelta(hours=3)).isoformat()
    past = (now - timedelta(hours=1)).isoformat()
    fixtures = [
        {"match_id": "future", "commence_time": future,
         "league_slug": "eng.1", "league": "Premier League"},
        {"match_id": "past", "commence_time": past,
         "league_slug": "eng.1", "league": "Premier League"},
    ]
    monkeypatch.setattr(engine, "_CACHE", {"entries": {}, "healthy_entries": {}})
    engine._store_cache_entry(
        7, [{"match_id": "future"}, {"match_id": "past"}], fixtures,
        time.time(), now, {"complete": not degraded},
        decision_snapshot_id="one-evaluated-board",
    )
    if stale:
        engine._CACHE["entries"][7]["ts"] -= engine._TTL + 1
    return fixtures


def _no_pipeline(monkeypatch):
    monkeypatch.setattr(engine, "run_pipeline", lambda **kw: pytest.fail(
        "public read rebuilt the pipeline"))


def test_warm_recommendations_and_fixtures_share_snapshot(monkeypatch):
    _entry(monkeypatch)
    _no_pipeline(monkeypatch)
    from leagues import recommendation_board
    monkeypatch.setattr(recommendation_board, "build_recommendation_board",
                        lambda picks, fixtures, **kw: {
                            "ids": [p["match_id"] for p in picks],
                            "fixtures": [f["match_id"] for f in fixtures],
                        })
    recommendations = api.get_fixture_recommendations(days_ahead=3)
    fixtures = asyncio.run(api.get_fixtures_list(days_ahead=3))
    assert recommendations["ids"] == ["future"]
    assert recommendations["fixtures"] == ["future"]
    assert recommendations["board"]["board_snapshot_id"] == "one-evaluated-board"
    assert fixtures["board"]["board_snapshot_id"] == "one-evaluated-board"
    assert fixtures["total"] == 1


def test_stale_degraded_board_served_and_refreshes_once(monkeypatch):
    _entry(monkeypatch, stale=True, degraded=True)
    _no_pipeline(monkeypatch)
    calls = []
    monkeypatch.setattr(engine, "start_prepared_board_refresh",
                        lambda **kw: calls.append(kw) or len(calls) == 1)
    from leagues import recommendation_board
    monkeypatch.setattr(recommendation_board, "build_recommendation_board",
                        lambda picks, fixtures, **kw: {"status": "success"})
    first = api.get_fixture_recommendations()
    assert first["board"]["stale"] is True
    assert first["board"]["degraded"] is True
    assert first["board"]["refresh_started"] is True
    assert calls == [{"days_ahead": 3, "force": True}]


def test_fresh_degraded_board_does_not_refresh_loop(monkeypatch):
    _entry(monkeypatch, degraded=True)
    _no_pipeline(monkeypatch)
    monkeypatch.setattr(engine, "start_prepared_board_refresh",
                        lambda **kw: pytest.fail("fresh degraded board refreshed"))
    from leagues import recommendation_board
    monkeypatch.setattr(recommendation_board, "build_recommendation_board",
                        lambda picks, fixtures, **kw: {"status": "success"})
    for _ in range(3):
        assert api.get_fixture_recommendations()["board"]["degraded"]


def test_cold_public_read_is_retryable_without_pipeline(monkeypatch):
    monkeypatch.setattr(engine, "_CACHE", {"entries": {}, "healthy_entries": {}})
    _no_pipeline(monkeypatch)
    monkeypatch.setattr(history_readiness, "status",
                        lambda: {"usable": True, "state": "READY"})
    started = []
    monkeypatch.setattr(engine, "start_prepared_board_refresh",
                        lambda **kw: started.append(kw) or len(started) == 1)
    for _ in range(3):
        with pytest.raises(HTTPException) as error:
            api.get_fixture_recommendations()
        assert error.value.status_code == 503
        assert error.value.detail["reason"] == "board_refreshing"
        assert error.value.detail["retryable"] is True
    assert len(started) == 3  # the helper is the single-flight boundary


def test_concurrent_cold_public_reads_start_one_pipeline(monkeypatch):
    monkeypatch.setattr(engine, "_CACHE", {"entries": {}, "healthy_entries": {}})
    monkeypatch.setattr(engine, "_PREWARMING", False)
    monkeypatch.setattr(history_readiness, "status",
                        lambda: {"usable": True, "state": "READY"})
    release = threading.Event()
    started = threading.Event()
    calls = []

    def blocked_pipeline(**kw):
        calls.append(kw)
        started.set()
        release.wait(5)
        return [], []

    monkeypatch.setattr(engine, "run_pipeline", blocked_pipeline)
    errors = []

    def request():
        try:
            api.get_fixture_recommendations()
        except HTTPException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=request) for _ in range(5)]
    try:
        for thread in threads:
            thread.start()
        assert started.wait(2)
        for thread in threads:
            thread.join(2)
        assert len(errors) == 5
        assert all(error.status_code == 503 for error in errors)
        assert len(calls) == 1
    finally:
        release.set()


def test_bookable_now_passes_only_prepared_future_picks(monkeypatch):
    _entry(monkeypatch)
    _no_pipeline(monkeypatch)
    from leagues import daily_feed
    monkeypatch.setattr(daily_feed, "build_bookable_now",
                        lambda all_picks: {"ids": [p["match_id"] for p in all_picks]})
    result = api.get_bookable_now()
    assert result["ids"] == ["future"]
    assert result["board"]["board_snapshot_id"] == "one-evaluated-board"


def test_builder_pool_has_no_implicit_cold_pipeline(monkeypatch):
    from leagues import slip_builder
    monkeypatch.setattr(engine, "_CACHE", {"entries": {}, "healthy_entries": {}})
    _no_pipeline(monkeypatch)
    assert slip_builder._pool("week") == []


def test_daily_public_read_does_not_generate_missing_card(monkeypatch):
    from leagues import daily_feed
    monkeypatch.setattr(daily_feed, "_accum_cache", {"result": None, "ts": 0})
    monkeypatch.setattr(daily_feed, "_load_locked", lambda day: None)
    _no_pipeline(monkeypatch)
    assert daily_feed.build_daily_accumulators(allow_generation=False) is None
    with pytest.raises(HTTPException) as error:
        api.get_daily_accumulators()
    assert error.value.status_code == 404


def test_diagnostics_reuses_snapshot_without_publishing(monkeypatch):
    _entry(monkeypatch)
    _no_pipeline(monkeypatch)
    from leagues import daily_feed, recommendation_board
    seen = []
    monkeypatch.setattr(recommendation_board, "build_recommendation_board",
                        lambda picks, fixtures, **kw: {
                            "date": "2026-09-24", "summary": {},
                            "market_distribution": {},
                        })
    monkeypatch.setattr(daily_feed, "build_daily_accumulators",
                        lambda **kw: seen.append(kw) or {"accumulators": {}})
    result = asyncio.run(api.recommendation_diagnostics())
    assert result["board"]["board_snapshot_id"] == "one-evaluated-board"
    assert len(seen) == 1 and "preview" in seen[0]
    assert [p["match_id"] for p in seen[0]["preview"]["picks"]] == ["future"]


def test_coverage_read_does_not_refresh_history_or_elo(monkeypatch):
    _entry(monkeypatch)
    _no_pipeline(monkeypatch)
    from leagues import base_rates, elo_engine
    monkeypatch.setattr(base_rates, "get_base_rates", lambda **kw: (
        {} if kw == {"allow_refresh": False} else pytest.fail("history refreshed")))
    monkeypatch.setattr(elo_engine, "get_ratings", lambda **kw: pytest.fail(
        "ELO refreshed"))
    monkeypatch.setattr(elo_engine, "cached_ratings", lambda: {})
    result = asyncio.run(api.competition_coverage(days_ahead=3))
    assert result["status"] == "success"
