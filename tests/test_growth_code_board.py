from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from growth import models, store
from growth.content import generate
from growth.dataset import _tier_block
from growth.engine import _due_templates
from growth.models import (
    DEFAULT_SETTINGS, GrowthContent, GrowthPublication, GrowthSetting, Status,
)
from growth.publishers.telegram import MAX_LEN, _truncate
from growth.templates import codes, over_15
from leagues.booking import leg_fingerprint, validated_public_booking


def _leg(match_id="m1", kickoff=None):
    kickoff = kickoff or (
        datetime.now(timezone.utc) + timedelta(days=1)
    ).isoformat()
    return {
        "match_id": match_id, "home_team": f"Home {match_id}",
        "away_team": f"Away {match_id}", "league": "Test League",
        "kickoff": kickoff, "prediction": "Over 1.5 Goals",
        "market": "over_1_5", "confidence": .82, "odds": 1.3,
        "odds_are_real": True,
    }


def _booking(games, code, odds=2.0, booking_status="FULL", **overrides):
    record = {
        "status": "active", "booking_status": booking_status,
        "share_code": code, "readback_validation": "PASSED",
        "actual_sportybet_odds": odds,
        "original_leg_count": len(games), "booked_leg_count": len(games),
        "excluded_leg_count": 0, "replacement_count": 0,
        "leg_fingerprint": leg_fingerprint(games),
    }
    record.update(overrides)
    return record


def _tier(key, count, code=None, odds=2.0, selected=True, **booking_overrides):
    games = [_leg(f"{key}-{index}") for index in range(count)]
    booking = (
        _booking(games, code, odds, **booking_overrides) if code else None
    )
    return _tier_block(key, {
        "selected": selected, "games": games,
        "total_odds": odds, "hit_probability": .6,
        "reason": None if selected else "Not enough safe matches today.",
        "booking": booking,
    })


def _data():
    rollover = _tier("rollover", 3, "ROLL33", 2.04)
    rollover.update({"day_number": 2, "target_days": 3})
    return {
        "date": "2026-09-09",
        "banker": _tier("banker", 1, "BANK11", 1.14),
        "two_odds": _tier("2_odds", 3, "TWO222", 1.89),
        "five_odds": _tier("5_odds", 4, "FIVE55", 5.1),
        "ten_odds": _tier("10_odds", 6, "TEN101", 10.2),
        "rollover": rollover,
        "over_1_5": _tier("over_1_5", 10),
    }


def test_code_board_renders_all_validated_tiers_and_actual_odds():
    payload = codes(_data(), "telegram")
    text = payload["text"]
    for code in ("BANK11", "TWO222", "FIVE55", "TEN101", "ROLL33"):
        assert code in text
    assert "Actual SportyBet odds: 1.89x" in text
    assert "ROLLOVER — DAY 2 OF 3" in text
    assert "10 independent picks" in text
    assert len(text) <= MAX_LEN
    assert _truncate(text) == text
    assert codes(_data(), "website") is None


def test_content_pipeline_generates_one_compliant_telegram_code_board():
    items = generate(
        _data(), platforms=["telegram", "website"], templates=["codes"]
    )
    assert len(items) == 1
    assert items[0]["template"] == "codes"
    assert items[0]["platform"] == "telegram"
    assert "18+" in items[0]["payload"]["text"]
    assert len(items[0]["payload"]["text"]) <= MAX_LEN


def test_code_board_schedule_is_morning_and_late_two_odds_is_retired(monkeypatch):
    assert DEFAULT_SETTINGS["schedule"]["codes"] == "07:15"
    assert "two_odds" not in DEFAULT_SETTINGS["schedule"]
    before = datetime(2026, 9, 9, 7, 14, tzinfo=timezone.utc)
    on_tick = datetime(2026, 9, 9, 7, 15, tzinfo=timezone.utc)
    assert "codes" not in _due_templates(before, DEFAULT_SETTINGS["schedule"])
    assert "codes" in _due_templates(on_tick, DEFAULT_SETTINGS["schedule"])

    engine = create_engine("sqlite:///:memory:")
    GrowthSetting.__table__.create(engine)
    session = sessionmaker(bind=engine)
    monkeypatch.setattr(models, "SessionLocal", session)
    db = session()
    db.add(GrowthSetting(
        key="schedule",
        value='{"two_odds":"14:00","results":"20:30"}',
    ))
    db.commit()
    db.close()
    effective = models.get_setting("schedule")
    assert effective["codes"] == "07:15"
    assert effective["results"] == "20:30"
    assert "two_odds" not in effective
    assert models.all_settings()["schedule"] == effective


def test_code_board_shows_missing_safe_five_and_ten_without_forcing():
    data = _data()
    data["five_odds"] = _tier("5_odds", 0, selected=False)
    data["ten_odds"] = _tier("10_odds", 0, selected=False)
    text = codes(data, "telegram")["text"]
    assert text.count("No safe slip today.") == 2
    assert text.count("We won't force this ticket.") == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "failed"},
        {"readback_validation": "FAILED"},
        {"booking_status": "PARTIAL", "partial": True},
        {"leg_fingerprint": "stale-card"},
        {"expires_at": "2020-01-01T00:00:00+00:00"},
    ],
)
def test_unsafe_booking_never_exposes_share_code(overrides):
    data = _data()
    data["two_odds"] = _tier(
        "2_odds", 3, "MUSTNOTSHOW", 1.9, **overrides
    )
    text = codes(data, "telegram")["text"]
    assert "MUSTNOTSHOW" not in text
    assert "No verified SportyBet code available." in text


def test_rebuilt_full_booking_is_labelled_and_must_still_be_complete():
    data = _data()
    data["five_odds"] = _tier(
        "5_odds", 4, "REBUILD", 5.2,
        booking_status="REBUILT_FULL", replacement_count=1,
    )
    text = codes(data, "telegram")["text"]
    assert "REBUILD" in text
    assert "Validated replacement slip" in text
    assert "1 unavailable selection was replaced before booking." in text


def test_over_15_code_is_never_in_board_even_if_partial_booking_exists():
    data = _data()
    tier = data["over_1_5"]
    tier["booking"] = {"status": "active", "booking_status": "PARTIAL",
                       "share_code": "PARTIAL15"}
    tier["booking_verified"] = False
    text = codes(data, "telegram")["text"]
    assert "PARTIAL15" not in text
    assert "independent picks" in text
    assert "Bet separately" in text


def test_started_accumulator_code_is_not_advertised():
    data = _data()
    data["two_odds"]["actionable"] = False
    text = codes(data, "telegram")["text"]
    assert "TWO222" not in text
    assert "no longer actionable" in text


def test_estimated_tier_odds_are_never_labelled_actual():
    data = _data()
    data["banker"]["booking"].pop("actual_sportybet_odds")
    text = codes(data, "telegram")["text"]
    banker = text.split("🎯 *2 ODDS*")[0]
    assert "Actual SportyBet odds" not in banker
    assert "1.14" not in banker


@pytest.mark.parametrize(
    "platform,text_field",
    [
        ("telegram", "text"), ("x", "text"),
        ("instagram", "caption"), ("facebook", "text"),
    ],
)
def test_over_15_is_truthful_independent_singles(platform, text_field):
    tier = _data()["over_1_5"]
    tier["total_odds"] = 6.04
    tier["hit_probability"] = .82
    payload = over_15({"date": "2026-09-09", "over_1_5": tier}, platform)
    text = payload[text_field].lower()
    assert "independent" in text
    assert "separate" in text
    assert "combined" not in text
    assert "together" not in text
    assert "6.04" not in text


@pytest.mark.parametrize("platform", ["tiktok", "youtube"])
def test_over_15_video_script_never_describes_an_accumulator(platform):
    tier = _data()["over_1_5"]
    tier["total_odds"] = 6.04
    payload = over_15({"date": "2026-09-09", "over_1_5": tier}, platform)
    script = " ".join(payload["script"]).lower()
    assert "independent" in script
    assert "separately" in script
    assert "together" not in script
    assert "6.04" not in script


def test_over_15_website_shape_does_not_expose_combined_product_fields():
    tier = _data()["over_1_5"]
    payload = over_15({"date": "2026-09-09", "over_1_5": tier}, "website")
    assert payload["presentation"] == "singles"
    assert payload["leg_count"] == 10
    assert "tier" not in payload
    assert "total_odds" not in payload


def test_booking_gate_requires_full_validated_exact_unexpired_record():
    games = [_leg("one"), _leg("two")]
    good = _booking(games, "SAFE22")
    assert validated_public_booking(good, games) is good
    assert validated_public_booking({**good, "partial": True}, games) is None
    assert validated_public_booking(
        {**good, "readback_validation": "FAILED"}, games
    ) is None


def test_publication_duplicate_guard_sends_code_board_once(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    GrowthContent.__table__.create(engine)
    GrowthPublication.__table__.create(engine)
    session = sessionmaker(bind=engine)
    monkeypatch.setattr(store, "SessionLocal", session)
    monkeypatch.setattr(models, "SessionLocal", session)
    monkeypatch.setattr(store, "channel_is_enabled", lambda channel: True)
    monkeypatch.setattr(store, "get_setting", lambda key, default=None: default)
    db = session()
    row = GrowthContent(
        publish_date="2026-09-09", template="codes", platform="telegram",
        payload='{"text": "codes"}', content_hash="codes-hash",
        status=Status.APPROVED,
    )
    db.add(row)
    db.commit()
    content_id = row.id
    db.close()
    sent = []

    assert store.publish_one(content_id, lambda payload: sent.append(payload) or "1")[
        "ok"
    ]
    assert not store.publish_one(
        content_id, lambda payload: sent.append(payload) or "2"
    )["ok"]
    assert len(sent) == 1
