"""Bounded read-only staging preview from the persisted evaluated board.

Interactive runtime intentionally retains a stale-safe snapshot for six hours,
but diagnostic scripts previously refused after the one-hour fresh TTL. A
historical *comparison* can use a sufficiently recent snapshot without any
provider network requests. This is not approval for official publication,
SportyBet booking or claims of fresh bookmaker availability.
"""
from __future__ import annotations

import math

MAX_PREVIEW_AGE_SECONDS = 4 * 3600


def verify_read_only_snapshot(board: dict | None) -> dict:
    if not isinstance(board, dict) or not board.get("ready"):
        raise RuntimeError("No prepared staging board available for read-only audit")
    try:
        age_seconds = float(board["age_seconds"])
    except (TypeError, ValueError, KeyError):
        raise RuntimeError("Read-only audit requires verified board age") from None
    if (not math.isfinite(age_seconds)
            or age_seconds < 0
            or age_seconds > MAX_PREVIEW_AGE_SECONDS):
        raise RuntimeError(
            "Prepared staging board outside bounded read-only audit window; "
            "refresh in isolated staging before comparing"
        )
    if not board.get("board_snapshot_id"):
        raise RuntimeError("Read-only audit requires a persisted snapshot identity")
    return {
        "snapshot_age_seconds": round(age_seconds, 1),
        "snapshot_stale": bool(board.get("stale")),
        "snapshot_source": board.get("board_source"),
        "snapshot_for_diagnostics_only": True,
        "bookmaker_availability_not_reverified": True,
        "maximum_allowed_audit_age_seconds": MAX_PREVIEW_AGE_SECONDS,
    }
