"""Lightweight private NBA settlement: no model training or full data download."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from basketball.research_data import read_games, write_games
from basketball.research_scoreboard import refresh_recent_finals
from basketball.research_store import (
    log_event, open_ledger, performance_report, settle_forecasts,
)

DEFAULT_HOME = Path("data/basketball/research")


def write_scoreboard_health(home: str | Path, status: dict,
                            when: datetime) -> None:
    root = Path(home)
    path = root / "scoreboard_health.json"
    # Retain evidence from the last actual network check across idle runs.
    previous = {}
    if path.is_file():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(previous, dict):
                previous = {}
        except (ValueError, OSError):
            previous = {}
    last_checked = previous.get("last_actual_check_at")
    last_check_status = previous.get("last_actual_check_status")
    if status.get("dates_checked", 0) > 0:
        last_checked = when.astimezone(timezone.utc).isoformat()
        last_check_status = status.get("status")
    data = {
        **status, "checked_at": when.astimezone(timezone.utc).isoformat(),
        "last_actual_check_at": last_checked,
        "last_actual_check_status": last_check_status,
        "research_only": True,
    }
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def settle_once(*, home: str | Path = DEFAULT_HOME,
                now: datetime | None = None, offline: bool = False,
                loader=None) -> dict:
    """Revalidate sources and settle exact fixture IDs; keep picks immutable.

    Offline uses only already verified local finals and does no network calls.
    """
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Settlement needs a timezone-aware clock")
    timestamp = timestamp.astimezone(timezone.utc)
    root = Path(home)
    games = read_games(root / "nba_games.jsonl")
    with open_ledger(root / "nba_paper.sqlite") as db:
        pending_dates = [
            row[0] for row in db.execute(
                "SELECT DISTINCT f.fixture_date FROM forecasts f "
                "LEFT JOIN settlements s ON s.game_id=f.game_id "
                "WHERE s.game_id IS NULL"
            ).fetchall()
        ]
        health = {"status": "offline", "dates_checked": 0,
                  "verified_new_finals": 0, "failed_dates": []}
        if not offline:
            games, health = refresh_recent_finals(
                games, as_of=timestamp, pending_dates=pending_dates,
                loader=loader)
            # Save the verified snapshot BEFORE writing settlement rows. A
            # future run can always recover exact verified finals after reboot.
            write_games(games, root / "nba_games.jsonl")
            write_scoreboard_health(root, health, timestamp)
        settled = settle_forecasts(db, games)
        log_event(db, "score-only",
                  f"source={health['status']} checked={health['dates_checked']} "
                  f"verified={health['verified_new_finals']} "
                  f"new_settlements={settled['newly_settled']} "
                  f"failures={len(health['failed_dates'])}")
        report = performance_report(db)
    from basketball.research_score_diagnostics import inspect_recent
    recent = inspect_recent(games, now=timestamp)
    return {
        "status": "research_only",
        "generated_at": timestamp.isoformat(),
        "scoreboard": health,
        "recent_fixtures": {
            "started_games": recent["started_games"],
            "completed_finals": recent["completed_finals"],
            "started_without_final": recent["started_without_final"],
            "finals_by_source": recent["finals_by_source"],
            "dates_awaiting_result": recent["dates_awaiting_result"],
        },
        "settlement": settled, "performance": report,
        "models_retrained": False,
        "public_publishing_enabled": False,
        "bookmaker_booking_enabled": False,
        "local_only": True,
    }
