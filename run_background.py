"""Run one BetSightly background process role."""

import atexit
import logging
import os
import time


logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s - %(name)s - "
        "%(levelname)s - %(message)s"
    ),
)

logger = logging.getLogger(
    __name__
)

role = os.getenv(
    "BETSIGHTLY_PROCESS_ROLE",
    "",
).strip().lower()

if role not in {
    "worker",
    "scheduler",
    "telegram",
}:
    raise SystemExit(
        "Set BETSIGHTLY_PROCESS_ROLE="
        "worker, scheduler or telegram"
    )


# Importing main starts only loops
# belonging to the selected role.
import main  # noqa: E402

from leagues.runtime_heartbeat import (  # noqa: E402
    instance_id,
    mark_stopped,
    touch,
)


ownership = {
    "scheduler":
        bool(
            main
            .SCHEDULER_JOBS_ENABLED
        ),

    "settlement":
        bool(
            main
            .SETTLEMENT_JOBS_ENABLED
        ),

    "telegram":
        bool(
            main
            .TELEGRAM_POLLING_ENABLED
        ),
}

identity = instance_id()


def _stop() -> None:
    try:
        mark_stopped(
            process_instance_id=identity,
        )

    except Exception:
        logger.exception(
            "Could not mark "
            "worker stopped"
        )


atexit.register(
    _stop
)


while True:
    try:
        touch(
            role,
            ownership=ownership,
            process_instance_id=identity,
        )

    except Exception:
        logger.exception(
            "Runtime heartbeat failed"
        )

    time.sleep(30)
