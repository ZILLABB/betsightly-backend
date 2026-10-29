"""Clock-aligned fallback for the 08:00 Africa/Lagos daily publication.

GitHub's cron remains the independent trigger. The Render recovery loop
normally polls every 15 minutes, but must not sleep *across* 08:00 WAT.
Actual publication remains protected by the existing DB idempotency claim.
"""
from datetime import datetime, timedelta, timezone

PUBLISH_UTC_HOUR = 7  # 08:00 WAT; Nigeria observes no daylight saving
DEFAULT_POLL_SECONDS = 900


def seconds_until_next_check(now: datetime, *, interval: int = DEFAULT_POLL_SECONDS) -> float:
    """Return a bounded delay, shortened only when the 08:00 WAT edge is near."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("an aware timestamp is required")
    if type(interval) is not int or interval < 1:
        raise ValueError("interval must be a positive integer")
    current = now.astimezone(timezone.utc)
    cutoff = current.replace(hour=PUBLISH_UTC_HOUR, minute=0, second=0, microsecond=0)
    if current < cutoff:
        return max(0.1, min(float(interval), (cutoff - current).total_seconds()))
    return float(interval)
