"""Hourly recovery scheduling tests."""
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from leagues import same_day_refill

def _setup(monkeypatch):
    from leagues import daily_feed
    import database
    eng = create_engine("sqlite://")
    monkeypatch.setattr(database, "engine", eng)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ENABLE_BACKGROUND_JOBS", "true")
    monkeypatch.setenv("BETSIGHTLY_PROCESS_ROLE", "worker")
    monkeypatch.setenv("BETSIGHTLY_SAME_DAY_REFILL_ENABLED", "true")
    monkeypatch.setattr(daily_feed, "_load_locked", lambda date: {
        "10_odds": {"selected": False, "games": []},
    })
    return eng

def test_hourly_refill_is_idempotent(monkeypatch):
    eng = _setup(monkeypatch)
    from leagues import daily_feed
    calls = []
    def recover():
        calls.append(1)
        return {"status": "COMPLETE", "tiers": {}}
    monkeypatch.setattr(daily_feed, "recover_today_empty_tiers", recover)
    now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
    assert same_day_refill.run_if_due(now)["status"] == "COMPLETE"
    assert same_day_refill.run_if_due(now)["status"] == "ALREADY_ATTEMPTED"
    assert len(calls) == 1
    with eng.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM same_day_refill_attempts")).scalar_one() == 1

def test_web_and_outside_window_cannot_run(monkeypatch):
    _setup(monkeypatch)
    at = datetime(2026, 10, 10, 6, 15, tzinfo=timezone.utc)
    assert same_day_refill.run_if_due(at)["status"] == "OUTSIDE_WINDOW"
    monkeypatch.setenv("BETSIGHTLY_PROCESS_ROLE", "web")
    assert same_day_refill.run_if_due(
        datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    )["status"] == "DISABLED"

def test_stale_board_retries_after_five_minutes_without_extra_bookings(monkeypatch):
    _setup(monkeypatch)
    from leagues import daily_feed, engine
    attempts = []
    def refill():
        attempts.append(1)
        if len(attempts) == 1:
            return {"status": "BOARD_UNAVAILABLE", "tiers": {},
                    "board": {"ready": True, "stale": True}}
        return {"status": "COMPLETE", "tiers": {
            "10_odds": {"status": "UNREACHABLE"}}}
    monkeypatch.setattr(daily_feed, "recover_today_empty_tiers", refill)
    monkeypatch.setattr(engine, "start_prepared_board_refresh",
                        lambda **kwargs: True)
    first = datetime(2026, 10, 10, 12, 10, tzinfo=timezone.utc)
    assert same_day_refill.run_if_due(first)["status"] == "BOARD_UNAVAILABLE"
    early = datetime(2026, 10, 10, 12, 12, tzinfo=timezone.utc)
    assert same_day_refill.run_if_due(early)["status"] == "ALREADY_ATTEMPTED"
    ready = datetime(2026, 10, 10, 12, 16, tzinfo=timezone.utc)
    assert same_day_refill.run_if_due(ready)["status"] == "COMPLETE"
    assert len(attempts) == 2
    assert same_day_refill.run_if_due(ready)["status"] == "ALREADY_ATTEMPTED"
