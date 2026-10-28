"""Already-started bookings may be visible only as historical references.

These tests never call the bookmaker, create codes or change persisted results.
"""
from datetime import datetime, timedelta, timezone

from leagues.booking import booking_lifecycle, leg_fingerprint

NOW = datetime(2026, 10, 28, 17, 0, tzinfo=timezone.utc)


def _games(minutes):
    return [
        {
            "match_id": "sportybet:1001",
            "home_team": "Alpha",
            "away_team": "Beta",
            "market": "over_1_5",
            "kickoff": (NOW + timedelta(minutes=minutes)).isoformat(),
        }
    ]


def _full(games):
    fingerprint = leg_fingerprint(games)
    return {
        "status": "active",
        "booking_status": "FULL",
        "share_code": "OLD123",
        "share_url": "https://www.sportybet.com/ng/?shareCode=OLD123",
        "readback_validation": "PASSED",
        "leg_fingerprint": fingerprint,
        "booking_variant_fingerprint": fingerprint,
        "booked_leg_count": len(games),
        "original_leg_count": len(games),
        "expires_at": (NOW + timedelta(days=2)).isoformat(),
    }


def test_started_ticket_keeps_only_nonactionable_historical_reference():
    games = _games(-10)
    result = booking_lifecycle(_full(games), games, now=NOW)
    assert result["status"] == "started"
    assert result["actionable"] is False
    assert result["share_code"] is None
    assert result["share_url"] is None
    assert result["historical_share_code"] == "OLD123"


def test_upcoming_ticket_keeps_original_actionable_code():
    games = _games(180)
    result = booking_lifecycle(_full(games), games, now=NOW)
    assert result["actionable"] is True
    assert result["share_code"] == "OLD123"


def test_code_expiry_keeps_reference_but_not_placeable_link():
    games = _games(180)
    booking = _full(games)
    booking["expires_at"] = (NOW - timedelta(minutes=3)).isoformat()
    result = booking_lifecycle(booking, games, now=NOW)
    assert result["status"] == "expired"
    assert result["share_code"] is None
    assert result["historical_share_code"] == "OLD123"


def test_invalid_identity_or_readback_may_not_show_historical_code():
    games = _games(-10)
    for key, value in (
        ("leg_fingerprint", "another-slip"),
        ("booking_variant_fingerprint", "another-slip"),
        ("booked_leg_count", 2),
        ("readback_validation", "FAILED"),
        ("booking_status", "PARTIAL"),
    ):
        booking = _full(games)
        booking[key] = value
        result = booking_lifecycle(booking, games, now=NOW)
        assert result.get("historical_share_code") is None
        assert result["share_code"] is None
