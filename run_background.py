"""Run one BetSightly background process role."""

import atexit
import logging
import os
import time
import threading


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
    "publication",
    "settlement",
    "telegram",
}:
    raise SystemExit(
        "Set BETSIGHTLY_PROCESS_ROLE="
        "worker, scheduler, publication, settlement or telegram"
    )


# Importing main starts only loops
# belonging to the selected role.
import main  # noqa: E402

from utils.runtime_supervisor import expected_thread_names, missing_threads  # noqa: E402

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

# Only new VPS split roles are strictly supervised; legacy Render roles
# retain their established behavior while migration is staged.
expected_threads = expected_thread_names(
    role,
    ownership,
    telegram_configured=bool(os.getenv("TELEGRAM_BOT_TOKEN")),
)
thread_grace_deadline = time.monotonic() + 90



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
    if expected_threads and time.monotonic() >= thread_grace_deadline:
        alive = {t.name for t in threading.enumerate() if t.is_alive()}
        missing = missing_threads(expected_threads, alive)
        if missing:
            logger.critical("Expected background threads exited: %s", missing)
            raise SystemExit(1)  # Docker restarts the container

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
