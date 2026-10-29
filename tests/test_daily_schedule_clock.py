"""8 AM WAT fallback timing regressions: no network or scheduler threads."""
from datetime import datetime, timedelta, timezone
import pytest

from leagues.daily_schedule_clock import seconds_until_next_check


@pytest.mark.parametrize("stamp,expected", [
    ("2026-10-29T06:40:00Z", 900),
    ("2026-10-29T06:45:00Z", 900),
    ("2026-10-29T06:50:00Z", 600),
    ("2026-10-29T06:55:56Z", 244),
    ("2026-10-29T06:59:30Z", 30),
    ("2026-10-29T07:00:00Z", 900),
    ("2026-10-29T07:01:15Z", 900),
])
def test_render_fallback_wakes_at_publication_boundary(stamp, expected):
    assert seconds_until_next_check(
        datetime.fromisoformat(stamp.replace("Z", "+00:00"))) == expected


def test_wat_timezone_is_not_shifted_twice():
    wat = timezone(timedelta(hours=1))
    instant = datetime(2026, 10, 29, 7, 56, tzinfo=wat)
    assert seconds_until_next_check(instant) == 240


def test_utc_boundary_always_same_even_after_timezone_conversion():
    now = datetime(2026, 10, 29, 8, 5, tzinfo=timezone(timedelta(hours=2)))
    assert seconds_until_next_check(now) == 900


def test_nearly_exact_boundary_is_bounded_and_does_not_spin():
    time = datetime(2026, 10, 29, 6, 59, 59, 950000, tzinfo=timezone.utc)
    assert seconds_until_next_check(time) == 0.1


def test_invalid_time_and_poll_intervals_rejected():
    with pytest.raises(ValueError):
        seconds_until_next_check(datetime(2026, 10, 29, 6, 58))
    with pytest.raises(ValueError):
        seconds_until_next_check(
            datetime(2026, 10, 29, 6, 58, tzinfo=timezone.utc), interval=0)
