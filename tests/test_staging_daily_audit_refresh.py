"""Explicit staging refresh for market-supply audit (never production)."""
from datetime import datetime, timedelta

import pytest

from scripts import audit_staging_daily_fixture_supply as audit
from scripts import prepare_staging_board_once as staging


def tomorrow_wat():
    return (datetime.now(audit.WAT).date() + timedelta(days=1)).isoformat()


def stale_board():
    return [], [], {"ready": True, "stale": True, "age_seconds": 4500}


def test_supply_audit_fails_closed_on_stale_board(monkeypatch):
    from leagues import engine
    monkeypatch.setattr(audit, "preflight", lambda: "betsightly_db_staging")
    monkeypatch.setattr(engine, "prepared_board", lambda days_ahead: stale_board())
    with pytest.raises(RuntimeError, match="--refresh-if-stale"):
        audit.audit(tomorrow_wat())


def test_supply_audit_explicit_refresh_reloads_then_evaluates(monkeypatch):
    from leagues import engine, sportybet, forecast_coverage
    monkeypatch.setattr(audit, "preflight", lambda: "betsightly_db_staging")
    calls = []
    refreshed = []

    def prepared(days_ahead):
        calls.append(days_ahead)
        if len(calls) == 1:
            return stale_board()
        return (
            [{"match_id": "m-1"}], [{"match_id": "m-1"}],
            {"ready": True, "stale": False, "age_seconds": 0,
             "board_snapshot_id": "new", "provider": {}},
        )

    monkeypatch.setattr(engine, "prepared_board", prepared)
    monkeypatch.setattr(staging, "prepare_once", lambda: refreshed.append(True))
    monkeypatch.setattr(sportybet, "_db_get", lambda key: {
        "fixtures": {"one": [{"event_id": "m-1"}]},
        "metadata": {"is_complete": True, "snapshot_id": "sb1"},
    })
    monkeypatch.setattr(sportybet, "_snapshot", lambda fixtures, meta: {})
    monkeypatch.setattr(audit, "inventory_for_day",
                        lambda *args: {"sportybet_fixture_count": 1})
    monkeypatch.setattr(audit, "diagnose_supply",
                        lambda *args: {"products": {}})
    monkeypatch.setattr(
        audit, "historical_coverage_from_staging",
        lambda *args: {"status": "HISTORY_NOT_INGESTED"},
    )
    monkeypatch.setattr(forecast_coverage, "coverage_funnel",
                        lambda *args, **kwargs: {"fixture_count": 1})

    report = audit.audit(tomorrow_wat(), refresh_if_stale=True)
    assert calls == [7, 7]
    assert refreshed == [True]
    assert report["database"] == "betsightly_db_staging"
    assert report["board_refreshed"] is True
    assert report["read_only"] is False
    assert report["publication_changed"] is False
    assert report["booking_codes_created"] is False
    assert report["forecast_and_model_value_diagnostics"]["fixture_count"] == 1


def test_refresh_must_produce_fresh_board(monkeypatch):
    from leagues import engine
    monkeypatch.setattr(audit, "preflight", lambda: "betsightly_db_staging")
    monkeypatch.setattr(engine, "prepared_board", lambda days_ahead: stale_board())
    monkeypatch.setattr(staging, "prepare_once", lambda: None)
    with pytest.raises(RuntimeError, match="unusable"):
        audit.audit(tomorrow_wat(), refresh_if_stale=True)


def test_preflight_happens_before_any_board_read(monkeypatch):
    from leagues import engine
    monkeypatch.setattr(audit, "preflight", lambda: (_ for _ in ()).throw(
        RuntimeError("wrong database")
    ))
    monkeypatch.setattr(engine, "prepared_board", lambda **kwargs: pytest.fail(
        "did not fail closed before reading the board"
    ))
    with pytest.raises(RuntimeError, match="wrong database"):
        audit.audit(tomorrow_wat(), refresh_if_stale=True)
