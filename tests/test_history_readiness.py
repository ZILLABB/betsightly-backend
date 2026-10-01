import json
import time
from datetime import datetime, timezone

from leagues import base_rates, team_history, history_readiness


def _paths(tmp_path, monkeypatch):
    monkeypatch.setattr(base_rates, "CACHE_PATH", tmp_path / "rates.json")
    monkeypatch.setattr(team_history, "CACHE_PATH", tmp_path / "teams.json")
    monkeypatch.setattr(history_readiness.shared_history_store,
                        "production_shared", lambda: False)


def _write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def test_clean_ready_stale_and_absent_startup(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    assert history_readiness.status()["state"] == "ABSENT"
    assert not history_readiness.status()["usable"]
    _write(base_rates.CACHE_PATH, {"_cache_schema": 2,
                                   "_built_at": datetime.now(timezone.utc).isoformat(),
                                   "_priors": {"global": {"matches": 100}}})
    _write(team_history.CACHE_PATH, {"_cache_schema": 2,
                                     "built_at": datetime.now(timezone.utc).isoformat(),
                                     "matches": []})
    assert history_readiness.status()["state"] == "READY"
    assert history_readiness.status()["usable"]
    _write(team_history.CACHE_PATH, {"_cache_schema": 2,
                                     "built_at": "2020-01-01T00:00:00+00:00",
                                     "matches": []})
    assert history_readiness.status()["state"] == "STALE_COMPLETE"
    assert history_readiness.status()["usable"]
    lock = team_history.CACHE_PATH.with_name("teams.json.refresh.lock")
    lock.write_text("owner", encoding="utf-8")
    state = history_readiness.status()
    assert state["usable"] and state["artifacts"]["team_history"]["refreshing"]
    team_history.CACHE_PATH.unlink()
    assert history_readiness.status()["state"] == "REFRESHING"
    assert not history_readiness.status()["usable"]


def test_no_history_fails_before_provider_and_prewarm_orders_board(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    from leagues import engine
    from leagues.history_readiness import HistoryNotReady
    try:
        engine._build_pipeline(4, False, time.time(), datetime.now(timezone.utc))
    except HistoryNotReady:
        pass
    else:
        raise AssertionError("public board built without history")

    # Exercise the background worker deterministically, with no provider I/O.
    order = []
    monkeypatch.setattr(base_rates, "get_base_rates", lambda: order.append("base"))
    monkeypatch.setattr(team_history, "load", lambda: order.append("team"))
    monkeypatch.setattr(history_readiness, "status",
                        lambda: {"usable": True, "state": "READY"})
    monkeypatch.setattr(engine, "prepared_board_status", lambda **kw: {"ready": False})
    monkeypatch.setattr(engine, "start_prepared_board_refresh",
                        lambda **kw: order.append("board"))

    class InlineThread:
        def __init__(self, target, **kw):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(engine.threading, "Thread", InlineThread)
    assert engine.start_history_prewarm()
    assert order == ["base", "team", "board"]
