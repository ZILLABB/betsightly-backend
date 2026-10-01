"""Staging-only automation for prospective V2 shadow evidence.

This worker deliberately cannot run in production.  It periodically forces a
fresh 7-day prediction board on staging so new pre-kickoff V2 observations are
captured automatically.  The normal pipeline already triggers the shared
shadow settlement worker, so this module does not create a second settlement
system.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone


logger = logging.getLogger(__name__)

AUTOMATION_FLAG = (
    "FOOTBALL_FIRST_SHADOW_V2_AUTOMATION_ENABLED"
)

INTERVAL_ENV = (
    "FOOTBALL_FIRST_SHADOW_V2_AUTOMATION_INTERVAL_SECONDS"
)

INITIAL_DELAY_ENV = (
    "FOOTBALL_FIRST_SHADOW_V2_AUTOMATION_INITIAL_DELAY_SECONDS"
)

DEFAULT_INTERVAL_SECONDS = 6 * 60 * 60
MIN_INTERVAL_SECONDS = 60 * 60
MAX_INTERVAL_SECONDS = 24 * 60 * 60
DEFAULT_INITIAL_DELAY_SECONDS = 30


_RUN_LOCK = threading.Lock()
_START_LOCK = threading.Lock()
_THREAD = None

_STATE_LOCK = threading.Lock()

_STATE = {
    "running":
        False,

    "thread_started_at":
        None,

    "last_started_at":
        None,

    "last_finished_at":
        None,

    "last_success_at":
        None,

    "last_failure_at":
        None,

    "last_error":
        None,

    "last_fixture_count":
        None,

    "last_pick_count":
        None,

    "last_v2_total":
        None,

    "last_v2_pending":
        None,

    "last_v2_settled":
        None,

    "last_history_refresh_status":
        None,

    "last_history_refresh_at":
        None,

    "last_base_rates_built_at":
        None,

    "last_team_history_built_at":
        None,

    "last_base_rate_competition_count":
        None,

    "last_team_history_match_count":
        None,

    "last_builder_candidate_count":
        None,

    "last_supplemental_qualified":
        None,

    "last_supplemental_bookable":
        None,

    "last_supplemental_approved":
        None,

    "last_supplemental_readiness_counts":
        {},

    "last_supplemental_ready_for_shadow":
        None,

    "last_supplemental_evaluated":
        None,

    "last_force_history":
        False,

    "runs":
        0,

    "successes":
        0,

    "failures":
        0,
}


def _truthy(
    name: str,
) -> bool:

    return str(
        os.getenv(
            name,
            "false",
        )
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _environment() -> str:

    return str(
        os.getenv(
            "ENVIRONMENT",
            "",
        )
    ).strip().lower()


def _bounded_int(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:

    try:
        value = int(
            os.getenv(
                name,
                str(default),
            )
        )

    except (
        TypeError,
        ValueError,
    ):
        value = default

    return max(
        minimum,
        min(
            maximum,
            value,
        ),
    )


def interval_seconds() -> int:

    return _bounded_int(
        INTERVAL_ENV,
        DEFAULT_INTERVAL_SECONDS,
        minimum=MIN_INTERVAL_SECONDS,
        maximum=MAX_INTERVAL_SECONDS,
    )


def initial_delay_seconds() -> int:

    return _bounded_int(
        INITIAL_DELAY_ENV,
        DEFAULT_INITIAL_DELAY_SECONDS,
        minimum=0,
        maximum=10 * 60,
    )


def enabled() -> bool:
    """Automation is deliberately impossible outside staging."""

    if (
        _environment()
        != "staging"
    ):
        return False

    return _truthy(
        AUTOMATION_FLAG
    )


def _now_iso() -> str:

    return (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )


def _update_state(
    **values,
) -> None:

    with _STATE_LOCK:
        _STATE.update(
            values
        )


def _refresh_staging_history(*, force: bool = False) -> dict:
    """Refresh only the evidence artifacts needed by the staging worker.

    Staging intentionally keeps ENABLE_BACKGROUND_JOBS=false, so the normal
    daily-generation loop does not call start_history_prewarm(). The V2
    evidence worker must therefore refresh these two caches itself before it
    forces a new prospective board.

    This does not publish a card, send notifications, settle public slips,
    enable production workers, change prediction thresholds, or promote V2.
    """

    if _environment() != "staging":
        return {
            "status": "NOT_APPLICABLE",
            "usable": False,
            "staging_only": True,
        }

    from leagues.base_rates import get_base_rates
    from leagues.team_history import load as load_team_history
    from leagues.history_readiness import status as history_status

    base_rates = get_base_rates(
        force=bool(force),
        allow_refresh=True,
    )

    team_history = load_team_history(
        force=bool(force),
        allow_refresh=True,
    )

    readiness = history_status()

    competition_count = sum(
        1
        for key, value in (base_rates or {}).items()
        if (
            not str(key).startswith("_")
            and isinstance(value, dict)
            and int(value.get("matches") or 0) > 0
        )
    )

    history_match_count = len(
        (team_history or {}).get("matches") or []
    )

    usable = bool(
        readiness.get("usable")
    )

    return {
        "status": (
            "READY"
            if usable
            else "NOT_READY"
        ),
        "usable": usable,
        "staging_only": True,
        "base_rates_built_at": (
            (base_rates or {}).get("_built_at")
        ),
        "team_history_built_at": (
            (team_history or {}).get("built_at")
        ),
        "base_rate_competition_count": (
            competition_count
        ),
        "team_history_match_count": (
            history_match_count
        ),
        "readiness_state": readiness.get(
            "state"
        ),
        "forced": bool(force),
        "history_fallback": dict(
            (base_rates or {}).get("_history_fallback")
            or {}
        ),
    }


def _supplemental_readiness_snapshot(fixtures: list[dict]) -> dict:
    """Read-only explanation of SportyBet-only supplemental blockers."""
    try:
        from leagues.base_rates import get_base_rates
        from leagues.sportybet import fetch_board, shadow_supplemental_readiness
        from leagues.team_history import HistoryIndex, load as load_team_history

        rates = get_base_rates(force=False, allow_refresh=False)
        history = HistoryIndex(
            load_team_history(force=False, allow_refresh=False)
        )
        report = shadow_supplemental_readiness(
            fixtures,
            fetch_board(),
            cached_rates=rates,
            history=history,
            days_ahead=7,
            sample_limit=25,
        )
        return {
            "status": report.get("status"),
            "evaluated_fixture_count": int(
                report.get("evaluated_fixture_count") or 0
            ),
            "ready_for_shadow_model_count": int(
                report.get("ready_for_shadow_model_count") or 0
            ),
            "readiness_counts": dict(
                report.get("readiness_counts") or {}
            ),
            "readiness_by_league": dict(
                report.get("readiness_by_league") or {}
            ),
            "identity_not_ready_samples": list(
                report.get("identity_not_ready_samples") or []
            ),
            "minimum_competition_history_matches": (
                report.get("minimum_competition_history_matches")
            ),
            "minimum_team_history_matches": (
                report.get("minimum_team_history_matches")
            ),
            "shadow_only": True,
        }
    except Exception as exc:
        logger.warning(
            "V2 staging supplemental readiness measurement failed: %s",
            exc,
            exc_info=True,
        )
        return {
            "status": "ERROR",
            "error_type": type(exc).__name__,
            "shadow_only": True,
        }


def _builder_candidate_snapshot() -> dict:
    """Read the prepared Builder pool after a successful staging refresh."""
    try:
        from leagues.builder_v2 import list_candidates
        result = list_candidates({"horizon": "7_days", "require_bookable": True})
        diagnostics = result.get("selection_diagnostics") or {}
        supplemental = diagnostics.get("staging_supplemental_counts") or {}
        return {
            "status": result.get("status"),
            "candidate_count": int(result.get("candidate_count") or 0),
            "supplemental_qualified": int(supplemental.get("qualified_pool") or 0),
            "supplemental_bookable": int(supplemental.get("prepared_bookable") or 0),
            "supplemental_after_trust_policy": int(supplemental.get("after_trust_and_policy") or 0),
            "supplemental_approved": int(supplemental.get("approved") or 0),
            "supplemental_bookability_rejections": dict(
                diagnostics.get("staging_supplemental_bookability_rejections") or {}
            ),
            "board_snapshot_id": (result.get("board") or {}).get("board_snapshot_id"),
        }
    except Exception as exc:
        logger.warning("V2 staging Builder measurement failed: %s", exc, exc_info=True)
        return {"status": "ERROR", "error_type": type(exc).__name__}


def status() -> dict:

    with _STATE_LOCK:
        state = dict(
            _STATE
        )

    thread = _THREAD

    state.update({
        "enabled":
            enabled(),

        "environment":
            _environment(),

        "staging_only":
            True,

        "interval_seconds":
            interval_seconds(),

        "initial_delay_seconds":
            initial_delay_seconds(),

        "thread_alive":
            bool(
                thread
                and thread.is_alive()
            ),

        "automatic_promotion":
            False,

        "production_allowed":
            False,

        "settlement_via_shared_pipeline":
            True,
    })

    return state


def run_once(*, force_history: bool = False) -> dict:
    """Run one staging evidence collection cycle synchronously.

    ``force_history`` only bypasses history freshness inside this staging-only
    worker. Production remains impossible because ``enabled()`` refuses it.
    """

    if not enabled():
        return {
            "status":
                "DISABLED",

            "reason":
                "staging_only_or_flag_disabled",

            "staging_only":
                True,
        }

    if not _RUN_LOCK.acquire(
        blocking=False
    ):
        return {
            "status":
                "SKIPPED",

            "reason":
                "already_running",

            "staging_only":
                True,
        }

    started_at = (
        _now_iso()
    )

    with _STATE_LOCK:
        _STATE[
            "running"
        ] = True

        _STATE[
            "last_started_at"
        ] = started_at

        _STATE[
            "runs"
        ] += 1

    try:
        history_refresh = (
            _refresh_staging_history(
                force=bool(force_history)
            )
        )

        refresh_finished_at = (
            _now_iso()
        )

        _update_state(
            last_history_refresh_status=(
                history_refresh.get("status")
            ),
            last_history_refresh_at=(
                refresh_finished_at
            ),
            last_base_rates_built_at=(
                history_refresh.get(
                    "base_rates_built_at"
                )
            ),
            last_team_history_built_at=(
                history_refresh.get(
                    "team_history_built_at"
                )
            ),
            last_base_rate_competition_count=(
                history_refresh.get(
                    "base_rate_competition_count"
                )
            ),
            last_team_history_match_count=(
                history_refresh.get(
                    "team_history_match_count"
                )
            ),
            last_force_history=bool(force_history),
        )

        logger.info(
            "V2 staging history refresh: "
            "status=%s base_rates_built_at=%s "
            "team_history_built_at=%s "
            "base_rate_competitions=%s "
            "team_history_matches=%s",
            history_refresh.get("status"),
            history_refresh.get(
                "base_rates_built_at"
            ),
            history_refresh.get(
                "team_history_built_at"
            ),
            history_refresh.get(
                "base_rate_competition_count"
            ),
            history_refresh.get(
                "team_history_match_count"
            ),
        )

        if not history_refresh.get(
            "usable"
        ):
            raise RuntimeError(
                "staging history refresh did not "
                "produce usable artifacts"
            )

        from leagues.engine import (
            run_pipeline,
        )

        picks, fixtures = (
            run_pipeline(
                days_ahead=7,
                force=True,
            )
        )

        from leagues.football_first_shadow_v2_observations import (
            shadow_report,
        )

        report = (
            shadow_report()
        )

        observations = (
            report.get(
                "observations"
            )
            or {}
        )

        supplemental_readiness = (
            _supplemental_readiness_snapshot(
                fixtures
            )
        )

        builder_snapshot = (
            _builder_candidate_snapshot()
        )

        finished_at = (
            _now_iso()
        )

        _update_state(
            running=False,
            last_finished_at=finished_at,
            last_success_at=finished_at,
            last_error=None,
            last_fixture_count=len(
                fixtures
            ),
            last_pick_count=len(
                picks
            ),
            last_v2_total=int(
                observations.get(
                    "total"
                )
                or 0
            ),
            last_v2_pending=int(
                observations.get(
                    "pending"
                )
                or 0
            ),
            last_v2_settled=int(
                observations.get(
                    "settled"
                )
                or 0
            ),
            last_builder_candidate_count=(builder_snapshot.get("candidate_count")),
            last_supplemental_qualified=(builder_snapshot.get("supplemental_qualified")),
            last_supplemental_bookable=(builder_snapshot.get("supplemental_bookable")),
            last_supplemental_approved=(builder_snapshot.get("supplemental_approved")),
            last_supplemental_readiness_counts=dict(
                supplemental_readiness.get("readiness_counts") or {}
            ),
            last_supplemental_ready_for_shadow=(
                supplemental_readiness.get("ready_for_shadow_model_count")
            ),
            last_supplemental_evaluated=(
                supplemental_readiness.get("evaluated_fixture_count")
            ),
            successes=(
                _STATE[
                    "successes"
                ]
                + 1
            ),
        )

        logger.info(
            "V2 staging evidence automation completed: "
            "fixtures=%s picks=%s total=%s pending=%s settled=%s "
            "builder_candidates=%s supplemental_qualified=%s "
            "supplemental_bookable=%s supplemental_approved=%s "
            "readiness=%s",
            len(fixtures),
            len(picks),
            observations.get("total"),
            observations.get("pending"),
            observations.get("settled"),
            builder_snapshot.get("candidate_count"),
            builder_snapshot.get("supplemental_qualified"),
            builder_snapshot.get("supplemental_bookable"),
            builder_snapshot.get("supplemental_approved"),
            supplemental_readiness.get("readiness_counts"),
        )

        return {
            "status":
                "SUCCESS",

            "fixtures":
                len(
                    fixtures
                ),

            "picks":
                len(
                    picks
                ),

            "v2_observations":
                observations,

            "history":
                history_refresh,

            "builder":
                builder_snapshot,

            "supplemental_readiness":
                supplemental_readiness,

            "staging_only":
                True,

            "automatic_promotion":
                False,
        }

    except Exception as exc:
        finished_at = (
            _now_iso()
        )

        with _STATE_LOCK:
            failures = (
                _STATE[
                    "failures"
                ]
                + 1
            )

        _update_state(
            running=False,
            last_finished_at=finished_at,
            last_failure_at=finished_at,
            last_error=(
                f"{type(exc).__name__}: {exc}"
            )[:1000],
            failures=failures,
        )

        logger.error(
            "V2 staging evidence automation failed: %s",
            exc,
            exc_info=True,
        )

        return {
            "status":
                "ERROR",

            "error_type":
                type(
                    exc
                ).__name__,

            "staging_only":
                True,

            "automatic_promotion":
                False,
        }

    finally:
        _RUN_LOCK.release()


def trigger_once(*, force_history: bool = False) -> dict:
    """Start one staging evidence cycle without blocking the HTTP request."""
    if not enabled():
        return {
            "status": "DISABLED",
            "reason": "staging_only_or_flag_disabled",
            "staging_only": True,
            "automatic_promotion": False,
        }

    with _STATE_LOCK:
        if _STATE.get("running"):
            return {
                "status": "SKIPPED",
                "reason": "already_running",
                "staging_only": True,
                "automatic_promotion": False,
            }

    thread = threading.Thread(
        target=run_once,
        kwargs={"force_history": bool(force_history)},
        daemon=True,
        name="football-first-v2-staging-manual-refresh",
    )
    thread.start()

    return {
        "status": "STARTED",
        "force_history": bool(force_history),
        "staging_only": True,
        "automatic_promotion": False,
    }


def _worker() -> None:

    delay = (
        initial_delay_seconds()
    )

    if delay:
        time.sleep(
            delay
        )

    first_run = True

    while enabled():

        # A staging deploy is our deterministic validation point for history
        # fallbacks. Force history once after startup, then return to the normal
        # freshness policy for six-hour cycles. Production can never reach
        # this worker because enabled() is staging-only.
        run_once(force_history=first_run)
        first_run = False

        if not enabled():
            break

        time.sleep(
            interval_seconds()
        )


def start() -> dict:
    """Start the singleton staging V2 evidence worker."""

    global _THREAD

    if not enabled():
        return {
            "status":
                "DISABLED",

            "reason":
                "staging_only_or_flag_disabled",

            "environment":
                _environment(),

            "staging_only":
                True,
        }

    with _START_LOCK:

        if (
            _THREAD is not None
            and _THREAD.is_alive()
        ):
            return {
                "status":
                    "EXISTS",

                "reason":
                    "worker_already_running",

                "staging_only":
                    True,
            }

        _THREAD = threading.Thread(
            target=_worker,
            daemon=True,
            name=(
                "football-first-v2-"
                "staging-evidence"
            ),
        )

        _update_state(
            thread_started_at=
                _now_iso()
        )

        _THREAD.start()

    logger.info(
        "V2 staging evidence automation started "
        "(interval=%ss, initial_delay=%ss)",
        interval_seconds(),
        initial_delay_seconds(),
    )

    return {
        "status":
            "STARTED",

        "interval_seconds":
            interval_seconds(),

        "initial_delay_seconds":
            initial_delay_seconds(),

        "staging_only":
            True,

        "automatic_promotion":
            False,
    }
