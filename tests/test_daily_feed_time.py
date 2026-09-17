from datetime import datetime, timezone

from leagues.availability import game_kickoff_lifecycle
from leagues.daily_feed import _wat_now
from leagues.picks_db import (
    DailyCard, SessionLocal, ensure_card_table, fill_empty_card_tiers,
    load_card, save_card,
)


def test_wat_date_rolls_over_before_utc_date():
    utc = datetime(2026, 9, 9, 23, 30, tzinfo=timezone.utc)
    assert _wat_now(utc).strftime("%Y-%m-%d %H:%M") == "2026-09-10 00:30"


def test_exact_twenty_minute_cutoff_is_not_actionable():
    now = datetime(2099, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert game_kickoff_lifecycle(
        {"kickoff": "2099-01-01T10:20:00Z"}, now
    ) == "kickoff_buffer"
    assert game_kickoff_lifecycle(
        {"kickoff": "2099-01-01T10:20:01Z"}, now
    ) == "actionable"


def test_locked_thin_day_preserves_publication_and_fixture_dates():
    day = "2099-01-02"
    ensure_card_table()
    db = SessionLocal()
    try:
        db.query(DailyCard).filter(DailyCard.publish_date == day).delete()
        db.commit()
    finally:
        db.close()
    card = {
        "banker": {"selected": True, "games": []},
        "_publication_date": day,
        "_fixture_target_date": "2099-01-03",
    }
    assert save_card(day, card)
    stored = load_card(day)
    assert stored["_publication_date"] == day
    assert stored["_fixture_target_date"] == "2099-01-03"


def test_published_over_singles_are_not_appended_without_archive_revision():
    day = "2099-01-04"
    ensure_card_table()
    db = SessionLocal()
    try:
        db.query(DailyCard).filter(DailyCard.publish_date == day).delete()
        db.commit()
    finally:
        db.close()
    original = {"match_id": "official", "confidence": .8, "odds": 1.2}
    assert save_card(day, {
        "over_1_5": {"selected": True, "presentation": "singles",
                      "games": [original]},
    })
    filled = fill_empty_card_tiers(day, {
        "over_1_5": {"selected": True, "presentation": "singles",
                      "games": [original, {"match_id": "late"}]},
    })
    assert filled == []
    assert [g["match_id"] for g in load_card(day)["over_1_5"]["games"]] == [
        "official"
    ]
