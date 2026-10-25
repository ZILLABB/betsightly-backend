"""Wave 1 one-command, read-only NBA research launch and settlement status.

Combines separately tested source, eligibility, immutable-ledger, automation
and market readiness checks. No network access, no database writes, no
predictions or public endpoints are created by this report.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from basketball.research_readiness import readiness_from_home
from basketball.research_operations import operations_from_home
from basketball.research_automation import reliability_from_home
from basketball.research_stage4_operations import stage4_report


def wave1_report(home: str | Path, *, now: datetime | None = None) -> dict:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("Wave 1 status clock must be timezone-aware")
    instant = instant.astimezone(timezone.utc)
    root = Path(home)
    readiness = readiness_from_home(root, days_ahead=7, now=instant)
    ops = operations_from_home(root, now=instant)
    tasks = reliability_from_home(root, now=instant)
    advanced = stage4_report(root, now=instant)
    upcoming = [
        item for item in readiness["fixtures"]
        if item["fixture_state"] == "upcoming"
    ]
    # A previously saved paper result is not proof of a current ready
    # forecast or source compliance. Keep all three readiness layers separate.
    eligible = [item for item in upcoming if item["eligible"]]
    quality = advanced["current_2027_asset_health"]
    warnings = list(dict.fromkeys([
        *ops.get("warnings", []),
        *tasks.get("issues", []),
    ]))
    reason = (
        "research_snapshot_missing"
        if readiness["snapshot"]["status"] in ("missing", "invalid", "unknown")
        else "schedule_or_source_stale"
        if readiness["snapshot"]["status"] != "fresh"
        else "eligible_private_games_waiting_for_cycle"
        if ops.get("eligible_not_yet_recorded")
        else "first_forecast_pending_final"
        if ops.get("pending_paper_forecasts", 0)
        else "first_forecast_settled"
        if ops.get("verified_paper_settlements", 0)
        else "five_verified_earlier_games_per_team_required"
        if any("warmup" in code for code in readiness["blockers"])
        else "no_current_eligible_pregame_fixtures"
    )
    return {
        "status": "research_only",
        "phase": "wave1_sources_forecast_settlement",
        "generated_at": instant.isoformat(),
        "source": {
            "snapshot_status": readiness["snapshot"]["status"],
            "last_retrieved_at": readiness["snapshot"]["last_retrieved_at"],
            "verified_2027_finals": advanced["current_2027_final_fixture_count"],
            "team_advanced_coverage": quality["team"],
            "player_advanced_coverage": quality["player"],
            "advanced_lagging_assets": advanced["current_2027_lagging_assets"],
        },
        "pregame": {
            "upcoming_next_7_days": len(upcoming),
            "eligible_next_7_days": len(eligible),
            "eligible_in_next_48h": ops.get("eligible_in_daily_cycle_window", 0),
            "already_recorded_next_48h": ops.get("already_recorded_in_daily_window", 0),
            "blockers": readiness["blockers"],
            "next_eligible": ({
                "game_id": eligible[0]["game_id"],
                "start_utc": eligible[0]["start_utc"],
                "home_team": eligible[0]["home_team"],
                "away_team": eligible[0]["away_team"],
            } if eligible else None),
            "next_upcoming_reason": ({
                "game_id": upcoming[0]["game_id"],
                "start_utc": upcoming[0]["start_utc"],
                "reasons": upcoming[0]["reasons"],
            } if upcoming else None),
        },
        "settlement": {
            "total_paper_forecasts": ops.get("total_recorded_paper_forecasts", 0),
            "verified_settlements": ops.get("verified_paper_settlements", 0),
            "pending": ops.get("pending_paper_forecasts", 0),
            "overdue": ops.get("overdue_pending", []),
            "prospective_integrity": ops.get("prospective_integrity"),
        },
        "automation": {
            "issues": tasks["issues"],
            "advisories": tasks.get("advisories", []),
            "pregame_status": tasks["tasks"]["pregame"]["status"],
            "score_status": tasks["tasks"]["score"]["status"],
            "full_status": tasks["tasks"]["full"]["status"],
        },
        "attention": warnings,
        "primary_next_step": reason,
        "release_gate": {
            "first_100_forward_finals_complete": (
                ops.get("verified_paper_settlements", 0) >= 100
            ),
            "deployable_to_public": False,
            "commercial_use_cleared": False,
            "no_bookmaker_prices": True,
        },
        "no_writes": True,
        "public_publishing_enabled": False,
        "local_only": True,
    }
