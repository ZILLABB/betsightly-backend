"""Staging rolling preview refresh is explicitly authorized and fail-closed."""
from datetime import datetime, timedelta

import pytest

from scripts import preview_staging_live_refill as preview


def _target_day() -> str:
    return (datetime.now(preview.WAT).date() + timedelta(days=1)).isoformat()


def _stale_status():
    return {"ready": True, "stale": True, "age_seconds": 4200}


def test_stale_preview_refuses_without_explicit_refresh(monkeypatch):
    from leagues import engine
    monkeypatch.setattr(preview, "preflight", lambda: "betsightly_db_staging")
    monkeypatch.setattr(
        engine, "prepared_board",
        lambda days_ahead: ([], [], _stale_status()),
    )
    with pytest.raises(RuntimeError, match="--refresh-if-stale"):
        preview.simulate(_target_day())


def test_explicit_refresh_reloads_board_before_read_only_simulation(monkeypatch):
    from leagues import engine, daily_feed
    from scripts import prepare_staging_board_once

    monkeypatch.setattr(preview, "preflight", lambda: "betsightly_db_staging")
    checks = []
    refreshed = []

    def get_board(days_ahead):
        checks.append(days_ahead)
        if len(checks) == 1:
            return [], [], _stale_status()
        return (
            [{"match_id": "f-1"}], [{"match_id": "f-1"}],
            {"ready": True, "stale": False, "age_seconds": 1, "board_snapshot_id": "s1"},
        )

    def refresh():
        refreshed.append(True)
        return {"board_ready": True, "board_stale": False}

    def make_live(*, all_picks, now, preview_only):
        assert preview_only
        assert all_picks == [{"match_id": "f-1"}]
        return {
            "preview_only": True,
            "booking_codes_created": False,
            "published_record_unchanged": True,
            "accumulators": {},
            "_portfolio": {"portfolio_validation": {"valid": True}},
            "kickoffs_remaining": 1,
            "window_ends_at": now.isoformat(),
        }

    monkeypatch.setattr(engine, "prepared_board", get_board)
    monkeypatch.setattr(prepare_staging_board_once, "prepare_once", refresh)
    monkeypatch.setattr(daily_feed, "build_bookable_now", make_live)

    result = preview.simulate(_target_day(), refresh_if_stale=True)
    assert refreshed == [True]
    assert checks == [7, 7]
    assert result["board_refreshed"] is True
    assert len(result["snapshots"]) == len(preview.TIMES_WAT)
    assert result["official_publication"] is False
    assert result["booking_codes_created"] is False


def test_refresh_still_rejects_stale_second_board(monkeypatch):
    from leagues import engine
    from scripts import prepare_staging_board_once
    monkeypatch.setattr(preview, "preflight", lambda: "betsightly_db_staging")
    monkeypatch.setattr(
        engine, "prepared_board",
        lambda days_ahead: ([], [], _stale_status()),
    )
    monkeypatch.setattr(
        prepare_staging_board_once,
        "prepare_once",
        lambda: {"board_ready": False},
    )
    with pytest.raises(RuntimeError, match="unusable"):
        preview.simulate(_target_day(), refresh_if_stale=True)
