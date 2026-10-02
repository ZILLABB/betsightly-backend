from sqlalchemy import (
    create_engine,
)
from sqlalchemy.pool import (
    StaticPool,
)

from services.process_leases import (
    acquire_process_lease,
)


def test_process_lease_is_singleton_and_reusable():
    db = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={
            "check_same_thread":
                False,
        },
    )

    first = acquire_process_lease(
        "telegram-test",
        db_engine=db,
    )

    assert first is not None

    second = acquire_process_lease(
        "telegram-test",
        db_engine=db,
    )

    assert second is None

    first.release()

    third = acquire_process_lease(
        "telegram-test",
        db_engine=db,
    )

    assert third is not None

    third.release()
