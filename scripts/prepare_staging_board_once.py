"""One-time, board-only staging data preparation (no scheduled side effects).

Run with the full staging runtime configuration; never with production data.
Unlike leagues.scheduler.run_daily, this does not publish, settle, distribute,
notify, or request bookmaker booking codes.
"""
from __future__ import annotations

import json
import os


STAGING_DATABASE_NAME = "betsightly_db_staging"


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def preflight() -> str:
    """Fail closed before loading any prediction engine or side effects."""
    if os.getenv("ENVIRONMENT", "").strip().lower() != "staging":
        raise RuntimeError("Refusing board refresh: ENVIRONMENT must be staging")
    if os.getenv("BETSIGHTLY_STAGING_BOARD_ONCE", "") != "CONFIRM_STAGING_ONLY":
        raise RuntimeError(
            "Refusing board refresh: set BETSIGHTLY_STAGING_BOARD_ONCE="
            "CONFIRM_STAGING_ONLY"
        )
    if _enabled(os.getenv("ENABLE_BACKGROUND_JOBS")):
        raise RuntimeError("Refusing board refresh with background jobs enabled")
    if not _enabled(os.getenv("PREPARED_BOARD_PERSISTENCE_ENABLED")):
        raise RuntimeError(
            "Refusing board refresh: PREPARED_BOARD_PERSISTENCE_ENABLED "
            "must be true, or the result is only cached in this job's memory"
        )

    # Check the *connected database*, not a configurable label in a URL.
    # A wrong DATABASE_URL must never make this command refresh production.
    from sqlalchemy import text
    from database import engine
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Staging board refresh requires PostgreSQL")
    with engine.connect() as db:
        actual = str(db.execute(text("select current_database()")).scalar() or "")
    if actual != STAGING_DATABASE_NAME:
        raise RuntimeError(
            f"Refusing board refresh for database {actual!r}; expected "
            f"{STAGING_DATABASE_NAME!r}"
        )
    return actual


def warm_staging_history() -> dict:
    """Warm history only after the caller verifies the isolated staging DB.

    Preserve a previous complete cache if the new optional backfill fails,
    rather than invalidating all daily predictions during a data upgrade.
    Never run this warmup from public HTTP endpoints.
    """
    from leagues import base_rates, history_readiness, team_history

    before = history_readiness.status()
    prior = base_rates.get_base_rates(allow_refresh=False)
    # Normal board preparation should not repeatedly refetch months of
    # historical football just because optional new backfill is unavailable.
    # The operator must explicitly request the expansion. Always recover
    # missing historical prerequisites, with production safely excluded.
    explicit_backfill = _enabled(os.getenv("BETSIGHTLY_STAGING_HISTORY_BACKFILL"))
    requested = (
        not before["usable"]
        or (
            explicit_backfill
            and prior.get("_history_backfill_version")
            != base_rates.HISTORY_BACKFILL_VERSION
        )
    )
    if requested:
        base_rates.get_base_rates(force=True)
        # A new staging workspace may not yet have any complete team form.
        if not history_readiness.status()["artifacts"]["team_history"]["complete"]:
            team_history.load(force=True)

    after = history_readiness.status()
    result = {
        "previous_state": before["state"],
        "state": after["state"],
        "usable": after["usable"],
        "backfill_refresh_requested": requested,
        "backfill_explicitly_requested": explicit_backfill,
        "backfill_policy_applied": bool(
            base_rates.get_base_rates(allow_refresh=False).get(
                "_history_backfill_version"
            ) == base_rates.HISTORY_BACKFILL_VERSION
        ),
    }
    if not after["usable"]:
        raise RuntimeError(
            "Staging history is incomplete after explicit prewarm: "
            + json.dumps(result, sort_keys=True)
            + ". Restore complete history caches before rebuilding board."
        )
    return result


def source_health_summary(status: dict) -> dict:
    """Explain independent provider quality without changing readiness."""
    provider = status.get("provider") or {}
    failed = sorted(set(str(s) for s in provider.get("failed_leagues") or []))
    detail = provider.get("failed_league_details") or {}
    return {
        "espn_complete": bool(provider.get("complete", False)),
        "espn_leagues_requested": int(provider.get("requested_league_count") or 0),
        "espn_leagues_succeeded": int(provider.get("successful_league_count") or 0),
        "espn_leagues_failed": len(failed),
        "espn_failed_leagues": failed,
        "espn_failed_reasons": {
            slug: dict(detail.get(slug) or {})
            for slug in failed
        },
        "espn_previous_snapshot_recovered_leagues": sorted(
            str(s) for s in provider.get("recovered_leagues") or []
        ),
        "board_ready_independent_of_provider_completeness": bool(
            status.get("ready")
        ),
        "note": (
            "A degraded source response does not mean the stored board is "
            "absent. These league failures remain missing or recovered; "
            "do not mislabel provider coverage as complete."
        ),
    }


def prepare_once() -> dict:
    database_name = preflight()
    history = warm_staging_history()
    from leagues.engine import prepared_board_status, run_pipeline

    # Direct, single synchronous board build. No daily scheduler and no
    # publication or booking endpoints are involved.
    picks, fixtures = run_pipeline(days_ahead=7, force=True)
    status = prepared_board_status(days_ahead=7)
    result = {
        "database": database_name,
        "history": history,
        "source_health": source_health_summary(status),
        "requested_days": 7,
        "fixture_count": len(fixtures),
        "candidate_count": len(picks),
        "board_ready": bool(status.get("ready")),
        "board_stale": bool(status.get("stale")),
        "complete": bool(status.get("complete")),
        "board_source": status.get("board_source"),
        "board_snapshot_id": status.get("board_snapshot_id"),
        "age_seconds": status.get("age_seconds"),
    }
    if not result["board_ready"] or result["board_stale"]:
        raise RuntimeError(
            "Staging board refresh did not produce a current usable snapshot: "
            + json.dumps(result, sort_keys=True)
        )
    return result


if __name__ == "__main__":
    print(json.dumps(prepare_once(), sort_keys=True))
