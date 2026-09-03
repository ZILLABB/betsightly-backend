from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from leagues import builder_runs as runs


def test_builder_runs_record_server_outcome_without_code(monkeypatch):
    db = create_engine("sqlite://", poolclass=StaticPool,
                       connect_args={"check_same_thread": False})
    monkeypatch.setattr(runs, "engine", db)
    runs.record_run(10, "today", False, {
        "status": "success", "legs": 4, "odds": 10.2,
        "booking": {"status": "active", "booking_status": "REBUILT_FULL",
                    "share_code": "SECRET-CODE", "actual_sportybet_odds": 10.1,
                    "readback_validation": "PASSED",
                    "sportybet_selection_fingerprint": "variant-1"},
    })
    result = runs.summary("2000-01-01", "2100-01-01")
    assert result["requests"] == 1
    assert result["tickets_produced"] == 1
    with db.begin() as conn:
        stored = conn.execute(runs.builder_runs.select()).mappings().one()
    assert "share_code" not in stored
    assert "SECRET-CODE" not in str(dict(stored))


def test_builder_runs_categorizes_no_code(monkeypatch):
    db = create_engine("sqlite://", poolclass=StaticPool,
                       connect_args={"check_same_thread": False})
    monkeypatch.setattr(runs, "engine", db)
    runs.record_run(50, "week", True, {
        "status": "success", "legs": 7,
        "booking": {"status": "unavailable", "booking_status": "UNAVAILABLE"},
    })
    result = runs.summary("2000-01-01", "2100-01-01")
    assert result["ticket_rate"] == 0
    assert result["failures"] == [{"category": "UNAVAILABLE", "count": 1}]
