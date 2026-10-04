"""Dedicated prepared-board worker.

Owns only history/fixture-board prewarming. It never publishes a card,
creates a SportyBet code, settles official slips, sends notifications,
or runs Telegram.
"""

from __future__ import annotations

import logging
import os
import signal
import threading

logger = logging.getLogger("betsightly.prepared_board_worker")

DEFAULT_INTERVAL_SECONDS = 900


def run_once() -> dict:
    from leagues.engine import (
        prepared_board_status,
        start_history_prewarm,
    )

    before = prepared_board_status(days_ahead=7)

    # Non-request caller: this is the explicitly authorised board worker.
    refresh_requested = start_history_prewarm(
        request_triggered=False,
    )

    result = {
        "refresh_requested": bool(refresh_requested),
        "ready_before": bool(before.get("ready")),
        "stale_before": bool(before.get("stale")),
        "age_seconds": before.get("age_seconds"),
        "fixture_count": int(before.get("fixture_count") or 0),
        "board_snapshot_id": before.get("board_snapshot_id"),
    }

    logger.info("prepared_board_worker_tick %s", result)
    return result


def run_forever() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )

    interval = max(
        60,
        int(
            os.getenv(
                "PREPARED_BOARD_WORKER_INTERVAL_SECONDS",
                str(DEFAULT_INTERVAL_SECONDS),
            )
        ),
    )

    stop = threading.Event()

    def _stop(*_args):
        logger.info("prepared board worker stopping")
        stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    logger.info(
        "prepared board worker started interval_seconds=%s",
        interval,
    )

    run_once()

    while not stop.wait(interval):
        try:
            run_once()
        except Exception:
            logger.exception("prepared board worker tick failed")


if __name__ == "__main__":
    run_forever()
