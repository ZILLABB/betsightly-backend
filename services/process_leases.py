"""Cross-process singleton leases for background jobs."""

from __future__ import annotations

import hashlib
import threading

from sqlalchemy import text

from database import engine


_LOCAL_LOCKS: dict[
    str,
    threading.Lock,
] = {}

_LOCAL_GUARD = threading.Lock()


def _lease_key(name: str) -> int:
    digest = hashlib.sha256(
        str(name).encode("utf-8")
    ).digest()[:8]

    return int.from_bytes(
        digest,
        byteorder="big",
        signed=True,
    )


class ProcessLease:
    def __init__(
        self,
        name: str,
        *,
        connection=None,
        local_lock=None,
    ):
        self.name = name
        self.connection = connection
        self.local_lock = local_lock
        self.key = _lease_key(name)
        self.released = False

    def release(self) -> None:
        if self.released:
            return

        self.released = True

        if self.connection is not None:
            try:
                self.connection.execute(
                    text(
                        "SELECT "
                        "pg_advisory_unlock(:key)"
                    ),
                    {
                        "key":
                            self.key,
                    },
                )

            finally:
                self.connection.close()

        if self.local_lock is not None:
            self.local_lock.release()


def acquire_process_lease(
    name: str,
    *,
    db_engine=engine,
) -> ProcessLease | None:

    if (
        db_engine.dialect.name
        != "postgresql"
    ):
        with _LOCAL_GUARD:
            lock = (
                _LOCAL_LOCKS
                .setdefault(
                    str(name),
                    threading.Lock(),
                )
            )

        if not lock.acquire(
            blocking=False
        ):
            return None

        return ProcessLease(
            str(name),
            local_lock=lock,
        )

    connection = (
        db_engine.connect()
    )

    try:
        acquired = bool(
            connection.execute(
                text(
                    "SELECT "
                    "pg_try_advisory_lock(:key)"
                ),
                {
                    "key":
                        _lease_key(name),
                },
            ).scalar()
        )

        if not acquired:
            connection.close()
            return None

        return ProcessLease(
            str(name),
            connection=connection,
        )

    except Exception:
        connection.close()
        raise
