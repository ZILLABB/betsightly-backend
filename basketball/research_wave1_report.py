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
from basketball.research_coldstart_ops import closeout
from basketball.research_cup_classification import from_home as cup_source_audit
from basketball.research_opening_score import audit as opening_score_audit


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
    coldstart = closeout(root, now=instant)
    cup = cup_source_audit(root, now=instant)
    opening_scores = opening_score_audit(root, now=instant)
    upcoming = [
        item for item in readiness["fixtures"]
        if item["fixture_state"] == "upcoming"
    ]
    # A previously saved paper result is not proof of a current ready
    # forecast or source compliance. Keep all three readiness layers separate.
    eligible = [item for item in upcoming if item["eligible"]]
    quality = advanced["current_2027_asset_health"]
    # Distinguish a healthy baseline pregame job from an optional blocked
    # advanced source. Surface the warning without declaring v1 unhealthy.
    hard_warnings = list(dict.fromkeys([
        *ops.get("warnings", []),
        *tasks.get("issues", []),
    ]))
    advisories = list(dict.fromkeys([
        *tasks.get("advisories", []),
        *(
            ["advanced_2027_boxscores_stale"]
            if advanced.get("current_2027_lagging_assets") else []
        ),
    ]))
    # No unsupported extrapolation from future scheduled NBA games: counts
    # refer ONLY to already completed, verified same-season finals.
    closest = sorted(
        (
            {
                "game_id": item["game_id"],
                "start_utc": item["start_utc"],
                "home_team": item["home_team"],
                "away_team": item["away_team"],
                "home_prior_verified": item["home_prior_games"],
                "away_prior_verified": item["away_prior_games"],
                "home_additional_finals_required": item["home_games_remaining"],
                "away_additional_finals_required": item["away_games_remaining"],
                "minimum_additional_team_finals": (
                    item["home_games_remaining"] + item["away_games_remaining"]
                ),
            }
            for item in upcoming
            if item["home_games_remaining"] or item["away_games_remaining"]
        ),
        key=lambda item: (
            item["minimum_additional_team_finals"],
            item["start_utc"] or "",
            item["game_id"],
        ),
    )
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
            "closest_to_five_verified_games": closest[:5],
            "closest_are_not_predictions": True,
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
        "historical_cup_classification_review": {
            "status": cup["status"],
            "match_status": cup.get("cup_fixture_identification"),
            "source_game_id": cup.get("cup_final_source_game_id"),
            "regular_season_inflation_review": (
                cup.get("raw_season_calendar", {}).get("teams_over_standard_count")),
            "no_source_mutation": True,
            "prospective_model_scores_replaced": False,
        },
        "separate_opening_score_experiment": {
            "status": opening_scores["status"],
            "forecast_count": opening_scores.get("forecasts"),
            "settled": opening_scores.get("settled"),
            "pending": opening_scores.get("pending"),
            "prospective_metrics": opening_scores.get("prospective_metrics"),
            "integrity_errors": opening_scores.get("integrity_errors", []),
            "not_a_bookmaker_market": True,
            "not_official_v1_calibration": True,
            "research_only": True,
        },
        "separate_early_season_experiment": {
            "status": coldstart["status"],
            "forecast_count": coldstart["forecast_count"],
            "settled": coldstart["verified_settlements"],
            "pending": coldstart["pending"],
            "verified_directional_correct": coldstart["verified_directional_correct"],
            "verified_directional_incorrect": coldstart["verified_directional_incorrect"],
            "integrity_errors": coldstart["integrity_errors"],
            "not_official_v1_calibration": True,
            "research_only": True,
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
            "advisories": advisories,
            "pregame_status": tasks["tasks"]["pregame"]["status"],
            "score_status": tasks["tasks"]["score"]["status"],
            "full_status": tasks["tasks"]["full"]["status"],
        },
        "attention": list(dict.fromkeys([*hard_warnings, *advisories])),
        "hard_operational_issues": hard_warnings,
        "nonblocking_advisories": advisories,
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
