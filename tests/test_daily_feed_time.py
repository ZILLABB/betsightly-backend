from datetime import datetime, timezone

from leagues.daily_feed import _wat_now


def test_wat_date_rolls_over_before_utc_date():
    utc = datetime(2026, 9, 9, 23, 30, tzinfo=timezone.utc)
    assert _wat_now(utc).strftime("%Y-%m-%d %H:%M") == "2026-09-10 00:30"
