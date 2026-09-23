"""Bounded ESPN monthly scoreboard reads for historical model inputs."""

from datetime import datetime, timedelta

import requests


def finished_events(slug: str, start: str, end: str, *, limit: int = 500) -> list[dict]:
    """Read only events in an inclusive YYYYMMDD window, without range queries.

    ESPN's scoreboard rejects YYYYMMDD-YYYYMMDD ranges for some leagues.
    Monthly queries are supported; filtering here also excludes future games
    returned by a monthly response and deduplicates overlapping provider data.
    """
    first = datetime.strptime(start, "%Y%m%d").date()
    last = datetime.strptime(end, "%Y%m%d").date()
    if last < first:
        return []
    month = first.replace(day=1)
    seen: set[str] = set()
    events: list[dict] = []
    while month <= last:
        try:
            response = requests.get(
                f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard",
                params={"dates": month.strftime("%Y%m"), "limit": limit}, timeout=25,
            )
            if response.status_code == 200:
                for event in response.json().get("events", []) or []:
                    event_day = str(event.get("date", ""))[:10]
                    if not (first.isoformat() <= event_day <= last.isoformat()):
                        continue
                    identity = str(event.get("id") or "")
                    if not identity or identity in seen:
                        continue
                    seen.add(identity)
                    events.append(event)
        except (requests.RequestException, ValueError, TypeError):
            pass  # A missing month degrades the sample, not the whole board.
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return events
