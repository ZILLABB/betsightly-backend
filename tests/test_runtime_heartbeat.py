from datetime import (
    datetime,
    timedelta,
    timezone,
)

from sqlalchemy import (
    create_engine,
)
from sqlalchemy.pool import (
    StaticPool,
)

from leagues import (
    runtime_heartbeat,
)


def _db():
    return create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={
            "check_same_thread":
                False,
        },
    )


def test_single_worker_is_active():
    db = _db()

    now = datetime(
        2026,
        10,
        2,
        12,
        0,
        tzinfo=timezone.utc,
    )

    runtime_heartbeat.touch(
        "worker",
        ownership={
            "scheduler": True,
            "settlement": True,
            "telegram": True,
        },
        now=now,
        db_engine=db,
        process_instance_id="w1",
    )

    report = (
        runtime_heartbeat.status(
            role="worker",
            now=(
                now
                + timedelta(
                    seconds=30
                )
            ),
            db_engine=db,
        )
    )

    assert report["active"] is True
    assert report["active_count"] == 1

    assert (
        report[
            "duplicate_active"
        ]
        is False
    )


def test_duplicate_workers_are_visible():
    db = _db()
    now = datetime.now(
        timezone.utc
    )

    for identity in (
        "w1",
        "w2",
    ):
        runtime_heartbeat.touch(
            "worker",
            now=now,
            db_engine=db,
            process_instance_id=identity,
        )

    report = (
        runtime_heartbeat.status(
            role="worker",
            now=now,
            db_engine=db,
        )
    )

    assert report["active_count"] == 2

    assert (
        report[
            "duplicate_active"
        ]
        is True
    )


def test_stale_worker_is_not_active():
    db = _db()
    now = datetime.now(
        timezone.utc
    )

    runtime_heartbeat.touch(
        "worker",
        now=(
            now
            - timedelta(
                minutes=10
            )
        ),
        db_engine=db,
        process_instance_id="old",
    )

    report = (
        runtime_heartbeat.status(
            role="worker",
            now=now,
            stale_after_seconds=120,
            db_engine=db,
        )
    )

    assert report["active"] is False
