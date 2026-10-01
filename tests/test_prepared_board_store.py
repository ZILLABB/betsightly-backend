from datetime import datetime, timedelta, timezone
import time

from sqlalchemy import create_engine

from leagues import prepared_board_store as store


def _entry(*, complete=True, marker="one"):
    now = datetime.now(timezone.utc)
    return {
        "picks": [
            {
                "match_id": f"m-{marker}",
                "market": "over_1_5",
                "_fixture": {
                    "match_id": f"m-{marker}",
                    "commence_time": (
                        now + timedelta(hours=3)
                    ).isoformat(),
                },
            }
        ],
        "fixtures": [
            {
                "match_id": f"m-{marker}",
                "commence_time": (
                    now + timedelta(hours=3)
                ).isoformat(),
            }
        ],
        "builder_supplemental_picks": [],
        "ts": time.time(),
        "metadata": {
            "generated_at": now.isoformat(),
            "requested_days": 7,
            "coverage_start": now.isoformat(),
            "coverage_end": (
                now + timedelta(days=7)
            ).isoformat(),
            "fixture_count": 1,
            "provider": {
                "complete": complete,
            },
            "decision_snapshot_id": marker,
        },
    }


def _sqlite_store(monkeypatch):
    db = create_engine("sqlite://")
    monkeypatch.setattr(store, "engine", db)
    monkeypatch.setenv(
        store.FEATURE_FLAG,
        "true",
    )
    return db


def test_persistence_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv(
        store.FEATURE_FLAG,
        raising=False,
    )
    assert store.enabled() is False
    assert store.load_entries() == []


def test_round_trip_full_prepared_entry(monkeypatch):
    _sqlite_store(monkeypatch)
    source = _entry()

    result = store.persist_entry(
        7,
        source,
        healthy=True,
    )

    assert result["status"] == "saved"
    assert result["slots"] == [
        "latest",
        "healthy",
    ]

    loaded = store.load_entries()

    assert {
        row["slot"]
        for row in loaded
    } == {
        "latest",
        "healthy",
    }

    for row in loaded:
        assert row["horizon_days"] == 7
        assert (
            row["entry"]["metadata"]
            ["decision_snapshot_id"]
            == "one"
        )
        assert (
            row["entry"]["picks"][0]
            ["match_id"]
            == "m-one"
        )


def test_degraded_latest_does_not_overwrite_healthy_slot(monkeypatch):
    _sqlite_store(monkeypatch)

    store.persist_entry(
        7,
        _entry(
            complete=True,
            marker="healthy",
        ),
        healthy=True,
    )

    store.persist_entry(
        7,
        _entry(
            complete=False,
            marker="degraded",
        ),
        healthy=False,
    )

    rows = {
        row["slot"]: row["entry"]
        for row in store.load_entries()
    }

    assert (
        rows["latest"]["metadata"]
        ["decision_snapshot_id"]
        == "degraded"
    )
    assert (
        rows["healthy"]["metadata"]
        ["decision_snapshot_id"]
        == "healthy"
    )


def test_corrupt_payload_is_ignored(monkeypatch):
    db = _sqlite_store(monkeypatch)
    store.ensure_table()

    now = datetime.now(timezone.utc)

    with db.begin() as conn:
        conn.execute(
            store.prepared_board_cache.insert().values(
                cache_key="bad",
                schema_version=store.SCHEMA_VERSION,
                horizon_days=7,
                slot="latest",
                saved_at=now,
                payload_sha256="0" * 64,
                payload_bytes=3,
                payload=b"bad",
            )
        )

    assert store.load_entries() == []
