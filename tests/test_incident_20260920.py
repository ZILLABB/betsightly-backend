"""Regression cases for the September 20 daily-card and partial-singles incident."""
from datetime import datetime, timedelta, timezone

from leagues.booking import booking_lifecycle, leg_fingerprint
from leagues.scheduler import _published_tier_counts


def test_daily_card_summary_ignores_non_product_metadata():
    accs = {
        "banker": {"games": [{"match_id": "1"}]},
        "over_1_5": {"games": [{"match_id": "2"}, {"match_id": "3"}]},
        "rollover": {"games": [{"match_id": "4"}]},
        "_publication_date": "2026-09-20",
        "_portfolio": {"products": {}},
    }
    assert _published_tier_counts(accs) == {
        "banker": 1, "over_1_5": 2, "rollover": 1,
    }
    assert _published_tier_counts(accs, include_rollover=False) == {
        "banker": 1, "over_1_5": 2,
    }


def _partial_record(now):
    games = [
        {"match_id": str(i), "home_team": f"Home {i}",
         "away_team": f"Away {i}", "market": "over_1_5",
         "kickoff": (now + timedelta(hours=2)).isoformat()}
        for i in range(10)
    ]
    booked = games[:8]
    return games, {
        "status": "active", "booking_status": "PARTIAL", "partial": True,
        "share_code": "MOCK_ONLY", "readback_validation": "PASSED",
        "original_leg_count": 10, "booked_leg_count": 8,
        "excluded_leg_count": 2, "final_booked_legs": booked,
        "excluded_legs": games[8:],
        "leg_fingerprint": leg_fingerprint(games),
        "booking_variant_fingerprint": leg_fingerprint(booked),
        "expires_at": (now + timedelta(days=1)).isoformat(),
    }


def test_only_verified_partial_singles_can_show_a_code():
    now = datetime(2026, 9, 20, 7, 0, tzinfo=timezone.utc)
    games, record = _partial_record(now)
    # Existing general/public-accumulator behavior remains fail-closed.
    assert booking_lifecycle(record, games, now)["share_code"] is None
    checked = booking_lifecycle(
        record, games, now, allow_partial_singles=True)
    assert checked["actionable"] is True
    assert checked["share_code"] == "MOCK_ONLY"

    bad = dict(record, excluded_legs=[games[7], games[9]])
    assert not booking_lifecycle(
        bad, games, now, allow_partial_singles=True)["actionable"]
    bad = dict(record, booking_variant_fingerprint="wrong")
    assert not booking_lifecycle(
        bad, games, now, allow_partial_singles=True)["actionable"]
    bad = dict(record, readback_validation="FAILED")
    assert not booking_lifecycle(
        bad, games, now, allow_partial_singles=True)["actionable"]
    assert not booking_lifecycle(
        record, games, now + timedelta(hours=3),
        allow_partial_singles=True)["actionable"]
