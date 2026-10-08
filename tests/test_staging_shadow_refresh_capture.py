"""Stage-only shadow refresh/capture is one guarded, ordered operation."""
from unittest.mock import Mock

import pytest

from scripts import staging_multimarket_shadow as runner


def test_refresh_capture_checks_staging_write_before_running_pipeline(monkeypatch):
    from leagues import engine, market_shadow_observations as shadow
    from scripts import prepare_staging_board_once as prep

    calls = []
    monkeypatch.setattr(runner, "preflight", lambda: "betsightly_db_staging")
    monkeypatch.setattr(
        shadow, "staging_write_gate",
        lambda **kw: calls.append("check_shadow_write") or "betsightly_db_staging",
    )
    monkeypatch.setattr(
        prep, "prepare_once",
        lambda: calls.append("refresh") or {
            "board_snapshot_id": "fresh-abc",
            "fixture_count": 1,
            "candidate_count": 2,
            "complete": False,
        },
    )
    fixture = {"commence_time": "2099-01-01T18:00:00Z"}
    monkeypatch.setattr(
        engine, "prepared_board",
        lambda days_ahead: (
            [{"match_id": "fx1"}], [fixture],
            {"ready": True, "stale": False, "board_snapshot_id": "fresh-abc"},
        ),
    )
    monkeypatch.setattr(
        shadow, "collect",
        lambda picks, snapshot_id, **kw: (
            calls.append("capture") or {"inserted": 1, "snapshot_id": snapshot_id}
        ),
    )
    result = runner.execute("refresh-capture")
    assert calls == ["check_shadow_write", "refresh", "capture"]
    assert result["operation"] == "refresh-capture"
    assert result["output"]["inserted"] == 1
    assert result["output"]["refresh"]["fixture_count"] == 1
    assert result["official_record_unchanged"] is True


def test_refresh_capture_cannot_refresh_without_shadow_write_authorization(monkeypatch):
    from leagues import market_shadow_observations as shadow
    from scripts import prepare_staging_board_once as prep

    monkeypatch.setattr(runner, "preflight", lambda: "betsightly_db_staging")
    monkeypatch.setattr(
        shadow, "staging_write_gate",
        Mock(side_effect=RuntimeError("confirmation missing")),
    )
    called = Mock(side_effect=AssertionError("should not refresh"))
    monkeypatch.setattr(prep, "prepare_once", called)
    with pytest.raises(RuntimeError, match="confirmation missing"):
        runner.execute("refresh-capture")
    called.assert_not_called()


def test_capture_only_does_not_trigger_network_refresh_on_stale_board(monkeypatch):
    from leagues import engine, market_shadow_observations as shadow
    from scripts import prepare_staging_board_once as prep

    monkeypatch.setattr(runner, "preflight", lambda: "betsightly_db_staging")
    monkeypatch.setattr(
        engine, "prepared_board",
        lambda days_ahead: ([], [], {"ready": True, "stale": True}),
    )
    not_called = Mock(side_effect=AssertionError("unexpected side effect"))
    monkeypatch.setattr(prep, "prepare_once", not_called)
    monkeypatch.setattr(shadow, "collect", not_called)
    with pytest.raises(RuntimeError, match="refresh-capture"):
        runner.execute("capture")
    not_called.assert_not_called()


def test_refresh_capture_rejects_different_persisted_snapshot(monkeypatch):
    from leagues import engine, market_shadow_observations as shadow
    from scripts import prepare_staging_board_once as prep

    monkeypatch.setattr(runner, "preflight", lambda: "betsightly_db_staging")
    monkeypatch.setattr(
        shadow, "staging_write_gate",
        lambda **kw: "betsightly_db_staging",
    )
    monkeypatch.setattr(
        prep, "prepare_once",
        lambda: {
            "board_snapshot_id": "A", "fixture_count": 2,
            "candidate_count": 3, "complete": True,
        },
    )
    monkeypatch.setattr(
        engine, "prepared_board",
        lambda days_ahead: (
            [{"match_id": "fx"}], [{"commence_time": "2099-01-01"}],
            {"ready": True, "stale": False, "board_snapshot_id": "B"},
        ),
    )
    not_called = Mock(side_effect=AssertionError("must not write"))
    monkeypatch.setattr(shadow, "collect", not_called)
    with pytest.raises(RuntimeError, match="snapshot changed"):
        runner.execute("refresh-capture")
    not_called.assert_not_called()
