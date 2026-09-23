"""Disposable PostgreSQL coordination test; set HISTORY_TEST_DATABASE_URL."""

import multiprocessing as mp
import os
import time

import pytest
from sqlalchemy import create_engine, text

from leagues import shared_history_store as store


def _owner_process(url, ready, release, result):
    engine = create_engine(url)
    with store.claim("pg_process_test", 2, engine=engine) as owner:
        result.put(bool(owner))
        ready.set()
        release.wait(15)
        if owner:
            result.put(store.promote(
                "pg_process_test", 2,
                {"_cache_schema": 2, "_priors": {"generation": 1}},
                owner, required="_priors", engine=engine))
    engine.dispose()


@pytest.mark.skipif(not os.getenv("HISTORY_TEST_DATABASE_URL"),
                    reason="disposable PostgreSQL URL not provided")
def test_two_postgres_processes_and_expired_owner():
    url = os.environ["HISTORY_TEST_DATABASE_URL"]
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM history_artifacts "
                          "WHERE cache_key = 'pg_process_test'"))
    ctx = mp.get_context("spawn")
    ready, release, result = ctx.Event(), ctx.Event(), ctx.Queue()
    process = ctx.Process(target=_owner_process, args=(url, ready, release, result))
    process.start()
    try:
        assert ready.wait(15)
        assert result.get(timeout=5) is True
        with store.claim("pg_process_test", 2, engine=engine) as contender:
            assert contender is None
        assert store.read("pg_process_test", 2, required="_priors",
                          engine=engine) is None
        release.set()
        assert result.get(timeout=5) is True
        process.join(10)
        assert process.exitcode == 0
        first = store.read("pg_process_test", 2, required="_priors",
                           engine=engine)
        assert first["_priors"]["generation"] == 1
        assert store.read("pg_process_test", 3, required="_priors",
                          engine=engine) is None
        with store.claim("pg_process_test", 3, engine=engine) as wrong_schema:
            assert wrong_schema is None
        with store.claim("pg_process_test", 2, engine=engine) as stale_owner:
            assert stale_owner
            assert store.read("pg_process_test", 2, required="_priors",
                              engine=engine) == first
            with engine.begin() as conn:
                conn.execute(text("UPDATE history_artifacts SET lease_until = "
                                  "EXTRACT(EPOCH FROM clock_timestamp()) - 1 "
                                  "WHERE cache_key = 'pg_process_test'"))
            with store.claim("pg_process_test", 2, engine=engine) as new_owner:
                assert new_owner and new_owner != stale_owner
                with pytest.raises(ValueError):
                    store.promote("pg_process_test", 2,
                                  {"_cache_schema": 2, "_priors": {},
                                   "_failed_leagues": ["partial"]},
                                  new_owner, required="_priors", engine=engine)
                assert not store.promote("pg_process_test", 2, first,
                                         stale_owner, required="_priors",
                                         engine=engine)
                second = {"_cache_schema": 2, "_priors": {"generation": 2}}
                assert store.promote("pg_process_test", 2, second, new_owner,
                                     required="_priors", engine=engine)
                assert store.read("pg_process_test", 2, required="_priors",
                                  engine=engine) == second
        assert store.read("pg_process_test", 2, required="_priors",
                          engine=engine)["_priors"]["generation"] == 2
    finally:
        release.set()
        process.join(2)
        engine.dispose()


@pytest.mark.skipif(not os.getenv("HISTORY_TEST_DATABASE_URL"),
                    reason="disposable PostgreSQL URL not provided")
def test_cold_start_stale_artifact_and_failed_refresh(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from leagues import base_rates, history_readiness, team_history

    db = create_engine(os.environ["HISTORY_TEST_DATABASE_URL"])
    with db.begin() as conn:
        conn.execute(text("DELETE FROM history_artifacts WHERE cache_key "
                          "IN ('base_rates', 'team_history')"))
    monkeypatch.setattr(base_rates, "CACHE_PATH", tmp_path / "base.json")
    monkeypatch.setattr(team_history, "CACHE_PATH", tmp_path / "teams.json")
    monkeypatch.setattr(store, "production_shared", lambda: True)
    monkeypatch.setattr(store, "_engine", lambda engine=None: engine or db)
    assert history_readiness.status()["state"] == "ABSENT"
    assert not history_readiness.status()["usable"]
    monkeypatch.setenv("ENVIRONMENT", "production")
    from leagues import engine as prediction_engine
    with pytest.raises(history_readiness.HistoryNotReady):
        prediction_engine._build_pipeline(
            4, False, time.time(), datetime.now(timezone.utc))

    old = "2020-01-01T00:00:00+00:00"
    base = {"_cache_schema": base_rates.HISTORY_CACHE_SCHEMA,
            "_built_at": old, "_priors": {"global": {"matches": 42}}}
    team = {"_cache_schema": team_history.HISTORY_CACHE_SCHEMA,
            "built_at": old, "matches": []}
    for key, schema, required, payload in (
            ("base_rates", base_rates.HISTORY_CACHE_SCHEMA, "_priors", base),
            ("team_history", team_history.HISTORY_CACHE_SCHEMA, "matches", team)):
        with store.claim(key, schema, engine=db) as owner:
            assert owner
            assert store.promote(key, schema, payload, owner,
                                 required=required, engine=db)
    assert history_readiness.status()["state"] == "STALE_COMPLETE"
    assert history_readiness.status()["usable"]
    with store.claim("base_rates", base_rates.HISTORY_CACHE_SCHEMA,
                     engine=db) as owner:
        assert owner
        assert history_readiness.status()["usable"]
        with pytest.raises(ValueError):
            store.promote("base_rates", base_rates.HISTORY_CACHE_SCHEMA,
                          {**base, "_failed_leagues": ["interrupted"]}, owner,
                          required="_priors", engine=db)
    assert store.read("base_rates", base_rates.HISTORY_CACHE_SCHEMA,
                      required="_priors", engine=db) == base
    current = {**base, "_built_at": datetime.now(timezone.utc).isoformat()}
    with store.claim("base_rates", base_rates.HISTORY_CACHE_SCHEMA,
                     engine=db) as owner:
        assert store.promote("base_rates", base_rates.HISTORY_CACHE_SCHEMA,
                             current, owner, required="_priors", engine=db)
    assert store.read("base_rates", base_rates.HISTORY_CACHE_SCHEMA,
                      required="_priors", engine=db) == current
    db.dispose()
