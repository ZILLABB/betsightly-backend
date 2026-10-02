from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services import api_football_gateway as gateway


@pytest.fixture
def quota_db(monkeypatch):
    test_engine = create_engine(
        "sqlite:///:memory:"
    )

    TestSession = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
    )

    monkeypatch.setattr(
        gateway,
        "engine",
        test_engine,
    )

    monkeypatch.setattr(
        gateway,
        "SessionLocal",
        TestSession,
    )

    monkeypatch.setattr(
        gateway,
        "_TABLE_READY",
        False,
    )

    monkeypatch.setenv(
        "API_FOOTBALL_API_KEY",
        "test-key",
    )

    monkeypatch.setenv(
        "ENVIRONMENT",
        "development",
    )

    monkeypatch.delenv(
        "BETSIGHTLY_PROCESS_ROLE",
        raising=False,
    )

    gateway.ensure_table()

    yield

    test_engine.dispose()


def test_daily_budget_stops_at_90(
    quota_db,
    monkeypatch,
):
    monkeypatch.setenv(
        "API_FOOTBALL_DAILY_BUDGET",
        "90",
    )

    start = datetime(
        2026,
        10,
        2,
        tzinfo=timezone.utc,
    )

    for index in range(90):
        allowed, reason = gateway.reserve_request(
            now=start + timedelta(
                minutes=index,
            )
        )

        assert allowed is True
        assert reason == "reserved"

    allowed, reason = gateway.reserve_request(
        now=start + timedelta(
            minutes=91,
        )
    )

    assert allowed is False
    assert reason == "local_daily_budget_reached"


def test_minute_budget_stops_at_8(
    quota_db,
    monkeypatch,
):
    monkeypatch.setenv(
        "API_FOOTBALL_MINUTE_BUDGET",
        "8",
    )

    now = datetime(
        2026,
        10,
        2,
        12,
        30,
        tzinfo=timezone.utc,
    )

    for _ in range(8):
        assert gateway.reserve_request(
            now=now
        )[0] is True

    allowed, reason = gateway.reserve_request(
        now=now
    )

    assert allowed is False
    assert reason == "local_minute_budget_reached"


def test_provider_reserve_opens_circuit(
    quota_db,
):
    now = datetime(
        2026,
        10,
        2,
        13,
        0,
        tzinfo=timezone.utc,
    )

    assert gateway.reserve_request(
        now=now
    )[0] is True

    class Response:
        status_code = 200
        headers = {
            "x-ratelimit-requests-remaining":
                "10",

            "X-RateLimit-Remaining":
                "7",
        }

    gateway.record_response(
        Response(),
        {
            "errors": {},
        },
        now=now,
    )

    allowed, reason = gateway.reserve_request(
        now=now + timedelta(
            minutes=1,
        )
    )

    assert allowed is False
    assert (
        reason
        == "provider_daily_reserve_reached"
    )


def test_suspended_provider_opens_circuit(
    quota_db,
):
    now = datetime(
        2026,
        10,
        2,
        14,
        0,
        tzinfo=timezone.utc,
    )

    assert gateway.reserve_request(
        now=now
    )[0] is True

    class Response:
        status_code = 200
        headers = {}

    gateway.record_response(
        Response(),
        {
            "errors": {
                "access":
                    "Your account is suspended",
            },
        },
        now=now,
    )

    allowed, reason = gateway.reserve_request(
        now=now + timedelta(
            minutes=1,
        )
    )

    assert allowed is False
    assert (
        reason
        == "provider_account_suspended"
    )


def test_web_role_spends_zero_quota(
    quota_db,
    monkeypatch,
):
    monkeypatch.setenv(
        "ENVIRONMENT",
        "staging",
    )

    monkeypatch.setenv(
        "BETSIGHTLY_PROCESS_ROLE",
        "web",
    )

    monkeypatch.setattr(
        gateway.requests,
        "get",
        lambda *args, **kwargs:
            pytest.fail(
                "web process touched provider"
            ),
    )

    response = gateway.api_football_get(
        "fixtures",
        params={
            "date":
                "2026-10-02",
        },
    )

    assert response is None

    status = gateway.quota_status()

    assert status["used"] == 0
    assert status["process_allowed"] is False


def test_scheduler_and_legacy_all_allowed(
    quota_db,
    monkeypatch,
):
    monkeypatch.setenv(
        "ENVIRONMENT",
        "staging",
    )

    monkeypatch.setenv(
        "BETSIGHTLY_PROCESS_ROLE",
        "scheduler",
    )

    assert gateway.reserve_request()[0] is True

    monkeypatch.setenv(
        "BETSIGHTLY_PROCESS_ROLE",
        "all",
    )

    assert gateway.reserve_request()[0] is True


def test_new_utc_day_gets_fresh_budget(
    quota_db,
    monkeypatch,
):
    monkeypatch.setenv(
        "API_FOOTBALL_DAILY_BUDGET",
        "1",
    )

    first = datetime(
        2026,
        10,
        2,
        23,
        59,
        tzinfo=timezone.utc,
    )

    assert gateway.reserve_request(
        now=first
    )[0] is True

    assert gateway.reserve_request(
        now=first
    )[0] is False

    second = datetime(
        2026,
        10,
        3,
        0,
        0,
        tzinfo=timezone.utc,
    )

    assert gateway.reserve_request(
        now=second
    )[0] is True
