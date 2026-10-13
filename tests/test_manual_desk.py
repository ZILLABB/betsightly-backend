"""Manual picks never mint misleading codes or mutate official daily records."""
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from leagues import manual_desk


NOW = datetime(2026, 10, 13, 9, 15, tzinfo=manual_desk.WAT)


def row(id="52587", market="home_win"):
    return {
        "sportybet_event_id": id, "home_team": "Arsenal", "away_team": "Lille",
        "league": "UEFA Champions League",
        "kickoff": "2026-10-13T19:00:00+01:00", "market": market,
        "confidence": 0.99, "odds": 9000.0, "share_code": "FORGED",
    }


def test_manual_parser_strips_claimed_probability_quoted_odds_and_code():
    result = manual_desk.normalise({
        "tier": "banker", "date": "2026-10-13",
        "legs": [row()],
    }, now=NOW)
    game = result["legs"][0]
    assert result["tier"] == "banker"
    assert game["source"] == "ADMIN_MANUAL"
    assert game["bookable"] is False
    assert "confidence" not in game
    assert "odds" not in game
    assert "share_code" not in game


def test_duplicate_match_fails_and_bookmaker_market_required():
    duplicate = [row(), row()]
    with pytest.raises(ValueError, match="more than once"):
        manual_desk.normalise({"tier": "2_odds", "legs": duplicate},
                              now=NOW)
    with pytest.raises(ValueError, match="unsupported"):
        manual_desk.normalise({"tier": "banker",
                               "legs": [row(market="score_will_be_3_1")]},
                              now=NOW)


def test_over15_tier_rejects_other_markets_and_started_matches():
    with pytest.raises(ValueError, match="only over_1_5"):
        manual_desk.normalise({"tier": "over_1_5", "legs": [row()]}, now=NOW)
    stale = row()
    stale["kickoff"] = "2026-10-13T09:20:00+01:00"
    with pytest.raises(ValueError, match="too close"):
        manual_desk.normalise({"tier": "banker", "legs": [stale]}, now=NOW)


def test_unpublished_database_read_fails_closed(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    monkeypatch.setattr(manual_desk, "_db", lambda: engine)
    result = manual_desk.public_slips("2026-10-13")
    assert result["slips"] == []
    assert result["status"] == "not_available"


def test_preview_does_not_write_or_verify_booking(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    monkeypatch.setattr(manual_desk, "_db", lambda: engine)
    data = {"tier": "banker", "legs": [row()]}
    # Test current clock isn't used to validate a historical fixture.
    monkeypatch.setattr(manual_desk, "normalise",
                        lambda payload: manual_desk.normalise(payload, now=NOW))
    result = manual_desk.preview(data)
    assert result["booking_verified"] is False
    assert result["official_model_record_unchanged"]
    assert manual_desk.public_slips("2026-10-13")["slips"] == []
