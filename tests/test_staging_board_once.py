"""One-shot staging refresh is denied by default and never publishes."""
import sys
from types import ModuleType, SimpleNamespace

import pytest

from scripts import prepare_staging_board_once as board_once


def _authorize_staging(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("ENABLE_BACKGROUND_JOBS", "false")
    monkeypatch.setenv("PREPARED_BOARD_PERSISTENCE_ENABLED", "true")
    monkeypatch.setenv("BETSIGHTLY_STAGING_BOARD_ONCE", "CONFIRM_STAGING_ONLY")


def test_never_runs_without_explicit_staging_environment(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("BETSIGHTLY_STAGING_BOARD_ONCE", "CONFIRM_STAGING_ONLY")
    with pytest.raises(RuntimeError, match="ENVIRONMENT must be staging"):
        board_once.preflight()


def test_never_runs_without_explicit_one_shot_consent(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.delenv("BETSIGHTLY_STAGING_BOARD_ONCE", raising=False)
    with pytest.raises(RuntimeError, match="CONFIRM_STAGING_ONLY"):
        board_once.preflight()


def test_never_runs_with_background_jobs_enabled(monkeypatch):
    _authorize_staging(monkeypatch)
    monkeypatch.setenv("ENABLE_BACKGROUND_JOBS", "true")
    with pytest.raises(RuntimeError, match="background jobs enabled"):
        board_once.preflight()


def _fake_database(monkeypatch, name):
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def execute(self, *_):
            return SimpleNamespace(scalar=lambda: name)

    engine = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        connect=lambda: Connection(),
    )
    mod = ModuleType("database")
    mod.engine = engine
    monkeypatch.setitem(sys.modules, "database", mod)


def test_never_runs_against_production_database_even_with_staging_env(monkeypatch):
    _authorize_staging(monkeypatch)
    _fake_database(monkeypatch, "betsightly_db")
    with pytest.raises(RuntimeError, match="Refusing board refresh for database"):
        board_once.preflight()


def test_board_only_work_does_not_invoke_daily_scheduler(monkeypatch):
    _authorize_staging(monkeypatch)
    _fake_database(monkeypatch, "betsightly_db_staging")
    import leagues.engine as engine

    called = []
    monkeypatch.setattr(engine, "run_pipeline", lambda days_ahead, force: (
        called.append((days_ahead, force)) or ([{"id": "p"}], [{"id": "f"}])
    ))
    monkeypatch.setattr(engine, "prepared_board_status", lambda days_ahead: {
        "ready": True, "stale": False, "complete": True,
        "board_snapshot_id": "staging-test-123",
        "board_source": "cache", "age_seconds": 1,
    })
    result = board_once.prepare_once()
    assert called == [(7, True)]
    assert result["database"] == "betsightly_db_staging"
    assert result["board_ready"] and not result["board_stale"]
    assert result["candidate_count"] == result["fixture_count"] == 1


def test_board_only_fails_if_no_current_snapshot(monkeypatch):
    _authorize_staging(monkeypatch)
    _fake_database(monkeypatch, "betsightly_db_staging")
    import leagues.engine as engine

    monkeypatch.setattr(engine, "run_pipeline", lambda **_: ([], []))
    monkeypatch.setattr(engine, "prepared_board_status", lambda **_: {
        "ready": False, "stale": True,
    })
    with pytest.raises(RuntimeError, match="current usable snapshot"):
        board_once.prepare_once()


def test_never_succeeds_without_shared_board_persistence(monkeypatch):
    _authorize_staging(monkeypatch)
    monkeypatch.setenv("PREPARED_BOARD_PERSISTENCE_ENABLED", "false")
    with pytest.raises(RuntimeError, match="PREPARED_BOARD_PERSISTENCE_ENABLED"):
        board_once.preflight()


def test_one_shot_prevents_shadow_settlement_even_with_observation_table(monkeypatch):
    _authorize_staging(monkeypatch)
    from leagues import football_first_shadow_observations as observations

    def unwanted_query(*_args, **_kwargs):
        raise AssertionError("shadow settlement must not query the database")

    monkeypatch.setattr(observations, "table_exists", unwanted_query)
    result = observations.start_settlement_async()
    assert result == {
        "status": "SKIPPED",
        "reason": "staging_board_only",
        "shadow_only": True,
    }
