"""Evidence-based NBA research release dashboard with explicit non-release gates.

Reads only verified private Supabase archive and operational audit metadata.
Do not infer schedule completeness, licensed data rights, commercial model
fitness, or independently proven disaster recovery from passing code tests.
"""
from __future__ import annotations

from basketball.research_forward_scorecard import scorecard
from basketball.research_multileague_release_gates import (
    CANDIDATE_LEAGUES, assess_league,
)
from basketball.research_market_settlement_contract import SUPPORTED, UNSUPPORTED


def evaluate_closeout(health: dict, archive: dict) -> dict:
    if not isinstance(health, dict) or health.get("status") != "private_research_health":
        raise ValueError("NBA_CLOSEOUT_PRIVATE_HEALTH_INVALID")
    if not isinstance(archive, dict):
        raise ValueError("NBA_CLOSEOUT_ARCHIVE_MISSING")
    models = scorecard(archive)
    live = health["job_readiness"]
    mandatory = ("forecast", "settlement", "market", "backup")
    if any(k not in live for k in mandatory):
        raise ValueError("NBA_CLOSEOUT_JOB_AUDIT_INCOMPLETE")
    service_blockers = [
        f"{kind}_not_healthy"
        for kind in mandatory if live[kind]["state"] != "observed"
    ]
    cohort = health["archive_cohort_coverage"]
    if cohort["future_missing_either_model"]:
        service_blockers.append("archived_future_fixtures_missing_model")
    if health["archive_capacity_state"] != "normal":
        service_blockers.append("research_archive_capacity_scale_required")
    if not (health["backup_version"] == "v2" and
            health["backup_recent_for_current_archive"] and
            health["backup_covers_current_market_history"]):
        service_blockers.append("current_complete_offsite_backup_not_verified")
    if not health["backup_covers_latest_job_history"]:
        # V2 acknowledges itself AFTER saving the prior job history.
        service_blockers.append("post_backup_audit_rows_not_yet_offsite")

    recent_coverage = health.get("latest_forecast_source_coverage")
    if recent_coverage is None:
        service_blockers.append("source_schedule_coverage_not_yet_audited")
    elif recent_coverage.get("next_48h_missing_original_model",0)>0:
        service_blockers.append("source_fixtures_missing_signed_forecasts")
    league_summary = {
        league: assess_league(league, {
            "independent_verified_finals": 0,
            "complete_seasons": 0,
        })
        for league in CANDIDATE_LEAGUES
    }
    # Zero means no independent league evidence accepted in this isolated
    # NBA database, NOT that the sport/league has zero games in the world.
    return {
        "status": "private_basketball_release_audit",
        "research_only": True,
        "public_publishing_enabled": False,
        "bookmaker_code_enabled": False,
        "infrastructure": {
            "state": ("degraded" if service_blockers else
                      "observed_healthy_private_research"),
            "blocking_evidence": service_blockers,
            "job_readiness": live,
            "archive_capacity_state": health["archive_capacity_state"],
            "remaining_fixture_slots": health["remaining_fixture_slots"],
            "archived_future_coverage": cohort,
            "all_nba_schedule_coverage_proven": False,
            "latest_provider_source_coverage": recent_coverage,
            "provider_source_not_independently_crosschecked": True,
        },
        "offsite_recovery": {
            "v2_blob_readback_verified": bool(
                health["backup_version"] == "v2"
                and health["backup_recent_for_current_archive"]
            ),
            "archive_market_receipts_current": bool(
                health["backup_covers_current_market_history"]
            ),
            "complete_audit_history_in_format": bool(
                health["job_audit_history_in_portable_backup"]
            ),
            "post_backup_job_rows_current": bool(
                health["backup_covers_latest_job_history"]
            ),
            "exact_private_blob_restored_on_independent_postgres": False,
            "production_failback_approved": False,
        },
        "nba_model_validation": models,
        "research_full_game_markets": sorted(SUPPORTED),
        "period_and_player_markets_blocked": sorted(UNSUPPORTED),
        "league_research": league_summary,
        "remaining_release_gates": [
            "restore_exact_private_blob_into_separate_postgres",
            "continuous_fixture_completeness_against_independent_nba_schedule",
            "minimum_100_independent_forward_model_evaluations_and_calibration",
            "period_player_availability_and_bookmaker_settlement_evidence",
            "source_rights_and_independent_validation_per_league",
        ],
        "not_a_betting_recommendation": True,
    }
