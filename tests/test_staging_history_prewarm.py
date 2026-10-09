"""Safe staged board prewarm preserves existing proven historical inputs."""
import pytest

from leagues import base_rates, history_readiness, team_history
from scripts import prepare_staging_board_once as prepare


def _status(*, base=True, team=True):
    return {
        "usable": base and team,
        "state": "READY" if base and team else "ABSENT",
        "artifacts": {
            "base_rates": {"complete": base},
            "team_history": {"complete": team},
        },
    }


def test_old_complete_cache_is_kept_while_explicit_backfill_refreshes(monkeypatch):
    cache = {"_cache_schema": 2, "_priors": {"global": {"matches": 41}}}
    calls = []

    def get_rates(*, force=False, allow_refresh=True):
        if force:
            calls.append("attempt_backfill")
            # Network's unavailable, but old cache is still intact.
        return cache

    monkeypatch.setattr(base_rates, "get_base_rates", get_rates)
    monkeypatch.setattr(history_readiness, "status", lambda: _status())
    monkeypatch.setattr(team_history, "load", lambda **kwargs: pytest.fail(
        "Existing team history should not be overwritten"
    ))
    report = prepare.warm_staging_history()
    assert report["usable"] is True
    assert report["backfill_refresh_requested"] is True
    assert report["backfill_policy_applied"] is False
    assert calls == ["attempt_backfill"]


def test_fresh_complete_cache_needs_no_refetch(monkeypatch):
    cache = {
        "_cache_schema": base_rates.HISTORY_CACHE_SCHEMA,
        "_history_backfill_version": base_rates.HISTORY_BACKFILL_VERSION,
    }
    monkeypatch.setattr(base_rates, "get_base_rates", lambda **kwargs: cache)
    monkeypatch.setattr(history_readiness, "status", lambda: _status())
    monkeypatch.setattr(team_history, "load", lambda **kwargs: pytest.fail(
        "No team refresh necessary"
    ))
    report = prepare.warm_staging_history()
    assert report["usable"] is True
    assert report["backfill_refresh_requested"] is False
    assert report["backfill_policy_applied"] is True


def test_missing_history_must_fail_instead_of_synthesizing_board(monkeypatch):
    monkeypatch.setattr(base_rates, "get_base_rates", lambda **kwargs: {})
    monkeypatch.setattr(history_readiness, "status", lambda: _status(base=False))
    monkeypatch.setattr(team_history, "load", lambda **kwargs: None)
    with pytest.raises(RuntimeError, match="incomplete"):
        prepare.warm_staging_history()


def test_preflight_guards_history_refresh_before_any_work(monkeypatch):
    monkeypatch.setattr(prepare, "preflight", lambda: (_ for _ in ()).throw(
        RuntimeError("Refusing wrong database")
    ))
    monkeypatch.setattr(prepare, "warm_staging_history", lambda: pytest.fail(
        "No warmup before preflight"
    ))
    with pytest.raises(RuntimeError, match="wrong database"):
        prepare.prepare_once()
