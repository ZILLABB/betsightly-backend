"""Staging rolling ticket editions are immutable, versioned and expire closed."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine

from leagues import live_card_store


def _card(now, code="CODE-ONE", kickoff_hours=4):
    return {
        "status": "success", "available": True,
        "date": (now + timedelta(hours=1)).date().isoformat(),
        "accumulators": {
            "2_odds": {
                "selected": True,
                "games": [{
                    "match_id": "fixture-1", "market": "over_1_5",
                    "prediction": "Over 1.5",
                    "odds": 1.6,
                    "kickoff": (now + timedelta(hours=kickoff_hours)).isoformat(),
                }],
                "booking": {
                    "status": "active", "booking_status": "FULL",
                    "readback_validation": "PASSED", "share_code": code,
                },
            }
        },
    }


def test_stored_editions_refresh_without_unnecessary_revision(monkeypatch):
    import database
    engine = create_engine("sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(database, "engine", engine)
    now = datetime(2026, 10, 9, 10, tzinfo=timezone.utc)
    a = live_card_store.save(_card(now), now)
    assert a["revision"] == 1 and a["status"] == "new_revision"

    current = live_card_store.load(now + timedelta(minutes=5))
    assert current["available"] is True
    assert current["prevalidated_booking_edition"] is True
    assert current["live_revision"] == 1
    assert current["accumulators"]["2_odds"]["booking"]["share_code"] == "CODE-ONE"

    same = live_card_store.save(_card(now), now + timedelta(minutes=6))
    assert same["status"] == "refreshed" and same["revision"] == 1

    revised = live_card_store.save(_card(now, code="CODE-TWO"), now + timedelta(minutes=7))
    assert revised["status"] == "new_revision" and revised["revision"] == 2
    assert live_card_store.load(now + timedelta(minutes=8))["live_revision"] == 2

    expired = live_card_store.load(now + timedelta(minutes=28))
    assert expired["available"] is False
    assert "expired" in expired["reason"]


def test_read_only_load_does_not_create_table(monkeypatch):
    import database
    from sqlalchemy import inspect
    engine = create_engine("sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(database, "engine", engine)
    before = inspect(engine).get_table_names()
    result = live_card_store.load(datetime(2026, 10, 9, 10, tzinfo=timezone.utc))
    after = inspect(engine).get_table_names()
    assert result["available"] is False
    assert before == after == []


def test_worker_refresh_is_off_without_explicit_flag(monkeypatch):
    monkeypatch.delenv("BETSIGHTLY_LIVE_REFILL_ENABLED", raising=False)
    assert live_card_store.refresh() == {"status": "disabled"}


def test_snapshot_expiry_precedes_kickoff_buffer():
    now = datetime(2026, 10, 9, 10, tzinfo=timezone.utc)
    card = _card(now, kickoff_hours=1)
    assert live_card_store._expiry(card, now) == now + timedelta(minutes=20)
    card["accumulators"]["2_odds"]["games"][0]["kickoff"] = (
        now + timedelta(minutes=25)).isoformat()
    assert live_card_store._expiry(card, now) == now + timedelta(minutes=5)
