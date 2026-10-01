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


def run_once() -> dict:
    """Run one fresh staging evidence collection cycle synchronously."""

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
            successes=(
                _STATE[
                    "successes"
                ]
                + 1
            ),
        )

        logger.info(
            "V2 staging evidence automation completed: "
            "fixtures=%s picks=%s total=%s pending=%s settled=%s",
            len(
                fixtures
            ),
            len(
                picks
            ),
            observations.get(
                "total"
            ),
            observations.get(
                "pending"
            ),
            observations.get(
                "settled"
            ),
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


def _worker() -> None:

    delay = (
        initial_delay_seconds()
    )

    if delay:
        time.sleep(
            delay
        )

    while enabled():

        run_once()

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
