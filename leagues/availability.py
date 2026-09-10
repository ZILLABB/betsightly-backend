"""Canonical pre-kickoff actionability policy shared by every product."""

from datetime import datetime, timedelta, timezone


BOOKING_BUFFER = timedelta(minutes=20)


def parse_kickoff(value) -> datetime | None:
    """Parse a stored/provider kickoff as an aware UTC datetime."""
    if isinstance(value, datetime):
        parsed = value
    elif value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def kickoff_lifecycle(value, now: datetime | None = None) -> str:
    """Return actionable, kickoff_buffer, started, or invalid."""
    kickoff = parse_kickoff(value)
    if kickoff is None:
        return "invalid"
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    if kickoff <= current:
        return "started"
    if kickoff <= current + BOOKING_BUFFER:
        return "kickoff_buffer"
    return "actionable"


def game_kickoff_lifecycle(game: dict, now: datetime | None = None) -> str:
    return kickoff_lifecycle(
        game.get("kickoff") or game.get("date") or game.get("commence_time"),
        now,
    )


def all_games_actionable(games: list, now: datetime | None = None) -> bool:
    return bool(games) and all(
        game_kickoff_lifecycle(game, now) == "actionable" for game in games
    )
