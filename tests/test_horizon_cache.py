import json
import asyncio
import os
import time
from datetime import datetime, timedelta, timezone

from leagues import engine, espn_source


def _fixture(now, offset_hours, suffix):
    return {
        "match_id": suffix,
        "commence_time": (now + timedelta(hours=offset_hours)).isoformat(),
        "home": {"name": f"Home {suffix}"},
        "away": {"name": f"Away {suffix}"},
        "odds": {},
    }


def test_engine_cache_one_then_seven_does_not_reuse_short_horizon(monkeypatch):
    monkeypatch.setattr(engine, "_CACHE", {"entries": {}})
    calls = []

    def build(days, force, now_ts, now_dt):
        calls.append((days, force))
        fixtures = [_fixture(now_dt, 1, f"{days}-near")]
        if days >= 7:
            fixtures.append(_fixture(now_dt, 120, "wide"))
        picks = [{"match_id": fixture["match_id"]} for fixture in fixtures]
        engine._store_cache_entry(
            days, picks, fixtures, now_ts, now_dt, {"complete": True}
        )
        return picks, fixtures

    monkeypatch.setattr(engine, "_build_pipeline", build)
    engine.run_pipeline(days_ahead=1)
    _, fixtures = engine.run_pipeline(days_ahead=7)

    assert calls == [(1, False), (7, False)]
    assert {fixture["match_id"] for fixture in fixtures} == {"7-near", "wide"}


def test_engine_cache_three_then_seven_does_not_reuse_short_horizon(monkeypatch):
    monkeypatch.setattr(engine, "_CACHE", {"entries": {}})
    calls = []

    def build(days, force, now_ts, now_dt):
        calls.append(days)
        fixtures = [_fixture(now_dt, 1, str(days))]
        engine._store_cache_entry(
            days, [], fixtures, now_ts, now_dt, {"complete": True}
        )
        return [], fixtures

    monkeypatch.setattr(engine, "_build_pipeline", build)
    engine.run_pipeline(days_ahead=3)
    engine.run_pipeline(days_ahead=7)

    assert calls == [3, 7]


def test_engine_wide_cache_can_serve_narrower_window(monkeypatch):
    monkeypatch.setattr(engine, "_CACHE", {"entries": {}})
    calls = []

    def build(days, force, now_ts, now_dt):
        calls.append(days)
        fixtures = [
            _fixture(now_dt, 2, "today"),
            _fixture(now_dt, 48, "later"),
        ]
        picks = [{"match_id": fixture["match_id"]} for fixture in fixtures]
        engine._store_cache_entry(
            days, picks, fixtures, now_ts, now_dt, {"complete": True}
        )
        return picks, fixtures

    monkeypatch.setattr(engine, "_build_pipeline", build)
    engine.run_pipeline(days_ahead=7)
    picks, fixtures = engine.run_pipeline(days_ahead=1)

    assert calls == [7]
    assert [fixture["match_id"] for fixture in fixtures] == ["today"]
    assert [pick["match_id"] for pick in picks] == ["today"]


def test_engine_force_refresh_bypasses_covering_cache(monkeypatch):
    monkeypatch.setattr(engine, "_CACHE", {"entries": {}})
    calls = []

    def build(days, force, now_ts, now_dt):
        calls.append(force)
        engine._store_cache_entry(
            days, [], [], now_ts, now_dt, {"complete": True}
        )
        return [], []

    monkeypatch.setattr(engine, "_build_pipeline", build)
    engine.run_pipeline(days_ahead=7)
    engine.run_pipeline(days_ahead=7, force=True)

    assert calls == [False, True]


def _configure_espn(monkeypatch, tmp_path, now, failing=None):
    monkeypatch.setattr(espn_source, "CACHE_PATH", tmp_path / "fixtures.json")
    monkeypatch.setattr(espn_source, "ESPN_CLUB_LEAGUES", {"a": "A", "b": "B"})
    calls = []

    def fetch(slug, date_range):
        calls.append((slug, date_range))
        failed = failing and failing(slug)
        espn_source._FETCH_HEALTH[slug] = {
            "provider_active": not failed,
            "request_succeeded": not failed,
            "error": "timeout" if failed else None,
        }
        if failed:
            return []
        return [
            _fixture(now, 6, f"{slug}-near"),
            _fixture(now, 120, f"{slug}-wide"),
        ]

    monkeypatch.setattr(espn_source, "_fetch_league", fetch)
    return calls


def test_provider_cache_short_then_wide_refetches(monkeypatch, tmp_path):
    now = datetime(2099, 1, 1, tzinfo=timezone.utc)
    calls = _configure_espn(monkeypatch, tmp_path, now)

    short = espn_source.get_fixtures(days_ahead=3, now=now)
    wide = espn_source.get_fixtures(days_ahead=7, now=now)

    assert len(calls) == 4
    assert len(short) == 2
    assert len(wide) == 4


def test_provider_wide_cache_serves_narrow_window(monkeypatch, tmp_path):
    now = datetime(2099, 1, 1, tzinfo=timezone.utc)
    calls = _configure_espn(monkeypatch, tmp_path, now)

    espn_source.get_fixtures(days_ahead=7, now=now)
    narrow = espn_source.get_fixtures(days_ahead=1, now=now)

    assert len(calls) == 2
    assert len(narrow) == 2
    assert espn_source.cache_metadata()["cache_hit"] is True


def test_provider_expired_cache_and_force_both_refetch(monkeypatch, tmp_path):
    now = datetime(2099, 1, 1, tzinfo=timezone.utc)
    calls = _configure_espn(monkeypatch, tmp_path, now)

    espn_source.get_fixtures(days_ahead=7, now=now)
    stale = time.time() - espn_source.CACHE_TTL - 10
    os.utime(espn_source.CACHE_PATH, (stale, stale))
    espn_source.get_fixtures(days_ahead=7, now=now)
    espn_source.get_fixtures(days_ahead=7, force=True, now=now)

    assert len(calls) == 6


def test_partial_provider_failure_never_masquerades_as_complete(monkeypatch, tmp_path):
    now = datetime(2099, 1, 1, tzinfo=timezone.utc)
    attempt = {"failed": True}
    calls = _configure_espn(
        monkeypatch, tmp_path, now,
        failing=lambda slug: slug == "b" and attempt["failed"],
    )

    espn_source.get_fixtures(days_ahead=7, now=now)
    first = json.loads(espn_source.CACHE_PATH.read_text(encoding="utf-8"))
    assert first["metadata"]["complete"] is False
    assert first["metadata"]["failed_leagues"] == ["b"]

    attempt["failed"] = False
    espn_source.get_fixtures(days_ahead=7, now=now)

    # The failed league is retried twice on the first degraded fetch; the
    # subsequent complete refresh requests both leagues once.
    assert len(calls) == 6
    assert espn_source.cache_metadata()["complete"] is True


def test_provider_retries_only_failed_leagues_and_deduplicates(monkeypatch, tmp_path):
    now = datetime(2099, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(espn_source, "CACHE_PATH", tmp_path / "fixtures.json")
    monkeypatch.setattr(espn_source, "ESPN_CLUB_LEAGUES", {"ok": "OK", "retry": "Retry"})
    calls = []

    def fetch(slug, date_range):
        calls.append(slug)
        succeeded = slug == "ok" or calls.count("retry") >= 2
        espn_source._FETCH_HEALTH[slug] = {
            "request_succeeded": succeeded,
            "provider_active": succeeded,
            "error": None if succeeded else "timeout",
        }
        return [_fixture(now, 6, "same")] if succeeded else []

    monkeypatch.setattr(espn_source, "_fetch_league", fetch)
    fixtures = espn_source.get_fixtures(days_ahead=7, now=now)
    metadata = espn_source.cache_metadata()
    assert calls == ["ok", "retry", "retry"]
    assert len(fixtures) == 1
    assert metadata["complete"] is True
    assert metadata["successful_league_count"] == 2
    assert metadata["requested_league_count"] == 2
    assert metadata["failed_league_count"] == 0


def test_valid_empty_league_is_success_and_is_not_retried(monkeypatch, tmp_path):
    now = datetime(2099, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(espn_source, "CACHE_PATH", tmp_path / "fixtures.json")
    monkeypatch.setattr(espn_source, "ESPN_CLUB_LEAGUES", {"empty": "Empty"})
    calls = []

    def fetch(slug, date_range):
        calls.append(slug)
        espn_source._FETCH_HEALTH[slug] = {
            "request_succeeded": True, "provider_active": True, "error": None,
        }
        return []

    monkeypatch.setattr(espn_source, "_fetch_league", fetch)
    assert espn_source.get_fixtures(days_ahead=7, now=now) == []
    assert calls == ["empty"]
    assert espn_source.cache_metadata()["complete"] is True


def test_partial_evaluated_board_is_ready_but_explicitly_degraded(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(engine, "_CACHE", {"entries": {}})
    fixture = _fixture(now, 2, "partial")
    engine._store_cache_entry(
        7, [{"match_id": "partial"}], [fixture], time.time(), now,
        {
            "complete": False,
            "successful_leagues": ["available"],
            "leagues_requested": ["available", "temporarily.down"],
            "failed_leagues": ["temporarily.down"],
        },
    )

    status = engine.prepared_board_status(7)
    picks, fixtures = engine.prepared_pipeline(7)

    assert status["ready"] is True
    assert status["complete"] is False
    assert status["degraded"] is True
    assert status["fixture_count"] == 1
    assert status["successful_league_count"] == 1
    assert status["requested_league_count"] == 2
    assert status["failed_league_count"] == 1
    assert [pick["match_id"] for pick in picks] == ["partial"]
    assert [item["match_id"] for item in fixtures] == ["partial"]


def test_interactive_builder_keeps_last_safe_board_during_refresh(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(engine, "_CACHE", {"entries": {}})
    monkeypatch.setattr(engine, "_PREWARMING", True)
    fixture = _fixture(now, 2, "stale-safe")
    engine._store_cache_entry(
        7, [{"match_id": "stale-safe"}], [fixture], time.time(), now,
        {"complete": False, "successful_leagues": ["available"]},
    )
    engine._CACHE["entries"][7]["ts"] -= engine._TTL + 1

    status = engine.prepared_board_status(7)
    picks, fixtures = engine.prepared_pipeline(7)

    assert status["ready"] is True
    assert status["stale"] is True
    assert status["refreshing"] is True
    assert [pick["match_id"] for pick in picks] == ["stale-safe"]
    assert [item["match_id"] for item in fixtures] == ["stale-safe"]


def test_cold_builder_click_returns_controlled_refresh_state(monkeypatch):
    from leagues import api, slip_builder

    monkeypatch.setattr(
        engine, "prepared_board_status",
        lambda days_ahead=7: {"ready": False, "requested_days": days_ahead},
    )
    started = []
    monkeypatch.setattr(
        engine, "start_prepared_board_refresh",
        lambda days_ahead=7, force=True: started.append((days_ahead, force)) or True,
    )
    monkeypatch.setattr(
        slip_builder, "generate",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("cold request must not run the pipeline")
        ),
    )

    result = asyncio.run(api.slip_builder_generate(20, horizon="week"))

    assert result["status"] == "unavailable"
    assert result["reason"] == "board_refreshing"
    assert result["retryable"] is True
    assert started == [(7, True)]


def test_builder_refresh_reuses_ready_board(monkeypatch):
    from leagues import api, builder_runs, slip_builder

    async def run_inline(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(
        engine, "prepared_board_status",
        lambda days_ahead=7: {"ready": True, "requested_days": days_ahead},
    )
    calls = []
    monkeypatch.setattr(
        slip_builder, "generate",
        lambda target, horizon="week", force=False: (
            calls.append((target, horizon, force))
            or {"status": "success", "games": [], "requested_target": target}
        ),
    )
    monkeypatch.setattr(builder_runs, "record_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(asyncio, "to_thread", run_inline)

    result = asyncio.run(
        api.slip_builder_generate(20, horizon="week", refresh=True)
    )

    assert result["status"] == "success"
    assert calls == [(20, "week", False)]


def test_builder_serves_stale_board_while_starting_background_refresh(monkeypatch):
    from leagues import api, builder_runs, slip_builder

    async def run_inline(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(
        engine, "prepared_board_status",
        lambda days_ahead=7: {
            "ready": True, "stale": True, "requested_days": days_ahead,
        },
    )
    started = []
    monkeypatch.setattr(
        engine, "start_prepared_board_refresh",
        lambda days_ahead=7, force=True: (
            started.append((days_ahead, force)) or True
        ),
    )
    monkeypatch.setattr(
        slip_builder, "generate",
        lambda target, horizon="week", force=False: {
            "status": "success", "games": [], "requested_target": target,
        },
    )
    monkeypatch.setattr(builder_runs, "record_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(asyncio, "to_thread", run_inline)

    result = asyncio.run(api.slip_builder_generate(100, horizon="week"))

    assert result["status"] == "success"
    assert started == [(7, True)]
