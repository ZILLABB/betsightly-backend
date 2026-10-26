"""Bounded, protected, staged-only NBA final-score settlement from hosted archive.

Uses the existing immutable three-ledger validators and the existing ESPN/NBA
scoreboard verifier. No football database writes, prediction rewrites, bookmaking,
or new model forecasts. Invoked by authenticated admin; scheduling is separate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from basketball.research_coldstart import _json, _now
from basketball.research_data import write_games
from basketball.research_private_bundle import (
    ARCHIVES, export_bundle, inspect_bundle, _digest,
)
from basketball.research_private_store import (
    SessionLocal, latest_bundle, import_bundle, hosted_board,
)
from basketball.research_scoreboard import (
    refresh_recent_finals, selected_dates,
)


def settle_hosted(*, now: datetime | None = None, session_factory=None,
                  refresher=None) -> dict:
    """Grade only existing before-tipoff forecasts against verified final scores.

    Fetch at most two provider-local dates per invocation (bounded upstream
    latency). A matching result is never guessed from team name. The existing
    DB snapshot append/identity checks run before every committed update.
    """
    instant = _now(now)
    db = (session_factory or SessionLocal)()
    try:
        original = latest_bundle(db)
    finally:
        db.close()
    if original is None:
        raise ValueError("NO_IMPORTED_NBA_ARCHIVE")
    inspect_bundle(original)

    source_games = original["fixtures"]
    dates = selected_dates(source_games, instant)[:2]
    if not dates:
        return {
            "status": "idle", "dates_checked": 0, "new_finals": 0,
            "new_settlements": {k: 0 for k in
                                ("moneyline", "original_score", "advanced_score")},
            "archive_digest": _digest(original), "research_only": True,
            "not_bookable": True,
        }

    relevant = [g for g in source_games if g["date"] in dates]
    updated_subset, provider = (refresher or refresh_recent_finals)(
        relevant, as_of=instant
    )
    changes = {str(g["game_id"]): g for g in updated_subset}
    if set(changes) != {str(g["game_id"]) for g in relevant}:
        raise ValueError("NBA_PROVIDER_COHORT_MISMATCH")
    updated_games = [changes.get(str(g["game_id"]), g) for g in source_games]
    new_final_count = sum(
        a["status"] != "final" and b["status"] == "final"
        for a, b in zip(source_games, updated_games)
    )

    with TemporaryDirectory(prefix="nba-hosted-grade-") as folder:
        home = Path(folder)
        write_games(updated_games, home / "nba_games.jsonl")
        for kind, filename in ARCHIVES.items():
            rows = original["records"][kind]
            if rows:
                (home / filename).write_text(
                    "".join(_json(row) + "\n" for row in rows),
                    encoding="utf-8",
                )

        from basketball.research_coldstart import settle as money_settle
        from basketball.research_opening_score import settle as score_settle
        from basketball.research_early_advanced_ops import settle as advanced_settle
        graded = {
            "moneyline": money_settle(home, now=instant),
            "original_score": score_settle(home, now=instant),
            "advanced_score": advanced_settle(home, now=instant),
        }
        if any(v["status"] == "integrity_failed" for v in graded.values()):
            raise ValueError("NBA_SIGNED_LEDGER_INTEGRITY_FAILURE")
        counts = {k: v["new_settlements"] for k, v in graded.items()}
        updated_bundle = export_bundle(home)

    result = {
        "status": "no_new_verified_finals",
        "dates_checked": provider.get("dates_checked", 0),
        "provider_status": provider.get("status", "unknown"),
        "failed_dates": provider.get("failed_dates", []),
        "new_finals": new_final_count,
        "new_settlements": counts,
        "research_only": True,
        "not_bookable": True,
    }
    if _digest(updated_bundle) == _digest(original):
        return {**result, "archive_digest": _digest(original)}
    # import_bundle acquires its own transaction/advisory lock, rechecks the
    # newest DB snapshot, and rejects concurrent conflicting updates.
    persisted = import_bundle(updated_bundle)
    readback = hosted_board()
    if readback is None or readback.get("archive_digest") != persisted["digest"]:
        raise RuntimeError("NBA_STAGING_SETTLEMENT_READBACK_MISMATCH")
    return {
        **result, "status": "settled_and_verified",
        "archive_digest": persisted["digest"],
        "fixture_count": persisted["fixture_count"],
    }
