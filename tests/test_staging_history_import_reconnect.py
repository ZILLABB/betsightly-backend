"""Regress SSL disconnect resilience and zero production write risk."""
from contextlib import contextmanager

import pytest
from sqlalchemy.exc import OperationalError

from scripts import ingest_staging_historical_results as ingest


class FakeResult:
    def __init__(self, *, scalar_value=None, rowcount=0):
        self.scalar_value, self.rowcount = scalar_value, rowcount

    def scalar(self):
        return self.scalar_value


class FakeEngine:
    def __init__(self, *, database="betsightly_db_staging", fail_insert_once=False,
                 fail_permanently=False):
        self.database = database
        self.fail_insert_once = fail_insert_once
        self.fail_permanently = fail_permanently
        self.attempted = 0
        self.dispose_count = 0
        self.committed = set()
        self.counts = []

    @contextmanager
    def begin(self):
        yield self

    def dispose(self):
        self.dispose_count += 1

    def execute(self, statement, values=None):
        if values is None:
            return FakeResult(scalar_value=self.database)
        self.attempted += 1
        if self.fail_permanently or (self.fail_insert_once and self.attempted == 1):
            raise OperationalError(
                "INSERT", values,
                OSError("SSL connection has been closed unexpectedly"),
                connection_invalidated=True,
            )
        count = 0
        for value in values:
            if value["fixture_key"] not in self.committed:
                self.committed.add(value["fixture_key"])
                count += 1
        self.counts.append(count)
        return FakeResult(rowcount=count)


def _rows(n):
    return [{"fixture_key": str(i)} for i in range(n)]


def test_transient_ssl_connection_loss_retries_one_chunk_and_resumes():
    engine = FakeEngine(fail_insert_once=True)
    result = ingest._insert_rows_with_reconnect(
        _rows(9), engine=engine, batch_size=4,
        sleep=lambda seconds: None,
    )
    assert result["inserted"] == 9
    assert result["committed_chunks"] == 3
    assert result["reconnect_retries"] == 1
    assert engine.dispose_count == 1
    assert len(engine.committed) == 9


def test_import_restart_is_idempotent_after_partial_progress():
    engine = FakeEngine()
    ingest._insert_rows_with_reconnect(
        _rows(5), engine=engine, batch_size=5, sleep=lambda _: None,
    )
    again = ingest._insert_rows_with_reconnect(
        _rows(8), engine=engine, batch_size=3, sleep=lambda _: None,
    )
    assert again["inserted"] == 3
    assert len(engine.committed) == 8


def test_wrong_db_fails_closed_before_first_write():
    engine = FakeEngine(database="betsightly_db")
    with pytest.raises(RuntimeError, match="non-staging"):
        ingest._insert_rows_with_reconnect(
            _rows(2), engine=engine, sleep=lambda _: None,
        )
    assert engine.attempted == 0


def test_permanent_ssl_failure_is_bounded():
    engine = FakeEngine(fail_permanently=True)
    with pytest.raises(RuntimeError, match="reconnect attempts"):
        ingest._insert_rows_with_reconnect(
            _rows(1), engine=engine, sleep=lambda _: None,
        )
    assert engine.attempted == ingest.MAX_WRITE_ATTEMPTS
    assert engine.dispose_count == ingest.MAX_WRITE_ATTEMPTS - 1


def test_bulk_chunk_size_is_bounded():
    with pytest.raises(ValueError, match="1..250"):
        ingest._insert_rows_with_reconnect(
            _rows(10), engine=FakeEngine(), batch_size=1000,
        )
