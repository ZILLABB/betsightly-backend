"""Read-only readiness bridge from immutable NBA paper forecasts to Jev.

The NBA staging repository has its own SQLite research ledger, distinct from
BetSightly football production. This reader opens that ledger in read-only
mode, never inserts results, and never sends paper forecasts for wagering.
The existing official injury archive is reported only as source-readiness:
there is no verified player crosswalk or approved commercial reuse yet.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from basketball.research_store import DEFAULT_DB
from basketball.research_injury_reports import injury_status


def _utc(value: str | datetime) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return value.astimezone(timezone.utc)


def jev_research_readiness(
    db_path: str | Path = DEFAULT_DB, *,
    home: str | Path | None = None,
    at: datetime | None = None,
) -> dict[str, Any]:
    now = _utc(at or datetime.now(timezone.utc))
    db_path = Path(db_path)
    root = Path(home) if home is not None else db_path.parent
    status = injury_status(root)
    overview: dict[str, Any] = {
        "status": "research_readiness_only", "sport": "basketball",
        "league": "NBA", "public_betting_enabled": False,
        "production_football_modified": False, "jev_calls_made": 0,
        "total_archived_forecasts": 0,
        "eligible_current_pretipoff_forecasts": 0,
        "verified_settlements": 0,
        "ineligible_archive_rows": 0,
        "injury_source": status,
        "injury_player_crosswalk_accepted": False,
        "injury_evidence_automatically_sent_to_jev": False,
        "shadow_evidence_eligible": False,
    }
    if not db_path.is_file():
        return {**overview, "status": "ledger_missing"}
    uri = db_path.resolve().as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
            connection.row_factory = sqlite3.Row
            items = connection.execute(
                "SELECT game_id, start_utc, created_at, raw_json "
                "FROM forecasts ORDER BY start_utc DESC LIMIT 2000"
            ).fetchall()
            count = connection.execute(
                "SELECT COUNT(*) FROM forecasts"
            ).fetchone()[0]
            finals = connection.execute(
                "SELECT COUNT(*) FROM settlements"
            ).fetchone()[0]
    except sqlite3.DatabaseError:
        return {**overview, "status": "unreadable_ledger"}
    eligible: list[dict[str, Any]] = []
    invalid = 0
    for row in items:
        try:
            original = json.loads(row["raw_json"])
            created = _utc(row["created_at"])
            start = _utc(row["start_utc"])
            if (not isinstance(original, dict)
                    or original.get("research_only") is not True
                    or original.get("not_for_betting") is not True
                    or original.get("bookmaker_odds_verified") is not False
                    or original.get("booking_code") is not None
                    or original.get("game_id") != row["game_id"]
                    or created >= start
                    or created > now):
                invalid += 1
                continue
            if start <= now:
                continue
            eligible.append({
                "game_id": str(row["game_id"]),
                "tipoff_utc": start.isoformat(),
                "captured_at": created.isoformat(),
                "market": "nba_moneyline",
                "model_version": str(original.get("model_version") or ""),
                "research_only": True, "bookable": False,
            })
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            invalid += 1
    return {
        **overview, "total_archived_forecasts": int(count),
        "verified_settlements": int(finals),
        "eligible_current_pretipoff_forecasts": len(eligible),
        "eligible_game_stubs": eligible[:20],
        "ineligible_archive_rows": invalid,
        "review_release_blockers": [
            "verified_source_identity_for_independent_nba_evidence",
            "approved_injury_player_crosswalk_and_usage_rights",
            "separate_jev_gateway_budget_and_private_staging_credentials",
        ],
    }
