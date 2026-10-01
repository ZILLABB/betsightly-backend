"""Bounded ESPN monthly scoreboard reads for historical model inputs."""

from datetime import datetime, timedelta, timezone
import time

import requests


class HistoryMonthUnavailable(RuntimeError):
    """A league-month could not be read; partial history must not be cached."""

    def __init__(self, message: str, *, permanent: bool = False,
                 status_code: int | None = None):
        super().__init__(message)
        self.permanent = permanent
        self.status_code = status_code


def finished_events(slug: str, start: str, end: str, *, limit: int = 500,
                    as_of: datetime | None = None) -> list[dict]:
    """Read only events in an inclusive YYYYMMDD window, without range queries.

    ESPN's scoreboard rejects YYYYMMDD-YYYYMMDD ranges for some leagues.
    Monthly queries are supported; filtering here also excludes future games
    returned by a monthly response and deduplicates overlapping provider data.
    """
    first = datetime.strptime(start, "%Y%m%d").date()
    last = datetime.strptime(end, "%Y%m%d").date()
    if as_of is not None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        as_of = as_of.astimezone(timezone.utc)
    if last < first:
        return []
    month = first.replace(day=1)
    seen: set[str] = set()
    events: list[dict] = []
    while month <= last:
        month_key = month.strftime("%Y%m")
        response = None
        for attempt in range(2):
            try:
                response = requests.get(
                    f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard",
                    params={"dates": month_key, "limit": limit}, timeout=25,
                )
                if response.status_code == 200:
                    break
                if response.status_code not in {429, 500, 502, 503, 504}:
                    break
            except requests.RequestException:
                response = None
            if attempt == 0:
                time.sleep(.2)
        if response is None or response.status_code != 200:
            raise HistoryMonthUnavailable(
                f"{slug} {month_key} unavailable",
                permanent=response is not None and response.status_code in {400, 404},
                status_code=response.status_code if response is not None else None,
            )
        try:
            for event in response.json().get("events", []) or []:
                event_day = str(event.get("date", ""))[:10]
                if not (first.isoformat() <= event_day <= last.isoformat()):
                    continue
                if as_of is not None:
                    # A live historical scoreboard has no trustworthy
                    # first-observed-completed timestamp. An as-of replay
                    # may use only an archived observation with this field.
                    observed = event.get("observed_completed_at")
                    if not observed:
                        continue
                    try:
                        observed_at = datetime.fromisoformat(
                            str(observed).replace("Z", "+00:00"))
                        if (observed_at.tzinfo is None
                                or observed_at.astimezone(timezone.utc) > as_of):
                            continue
                    except ValueError:
                        continue
                identity = str(event.get("id") or "")
                if not identity or identity in seen:
                    continue
                seen.add(identity)
                events.append(event)
        except (ValueError, TypeError, AttributeError) as exc:
            raise HistoryMonthUnavailable(
                f"{slug} {month_key} malformed") from exc
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return events
