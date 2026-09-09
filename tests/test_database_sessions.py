"""Regression coverage for database-session ownership and pool hygiene."""

import asyncio
import inspect
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool


def _queue_pool_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=QueuePool,
        pool_size=1,
        max_overflow=0,
    )


def test_repeated_legacy_and_current_operations_return_connections(monkeypatch):
    """The former early-return leak must not consume one checkout per call."""
    import services.daily_predictions_service as legacy
    from punter import Punter
    from services.punter_service import PunterService

    test_engine = _queue_pool_engine()
    factory = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    legacy.DailyPredictionSummary.__table__.create(test_engine, checkfirst=True)
    Punter.__table__.create(test_engine, checkfirst=True)

    seed = factory()
    try:
        seed.add(legacy.DailyPredictionSummary(
            prediction_date=legacy.datetime.strptime("2026-09-09", "%Y-%m-%d").date(),
            generation_status="completed",
        ))
        seed.commit()
    finally:
        seed.close()

    monkeypatch.setattr(legacy, "SessionLocal", factory)
    retired_service = object.__new__(legacy.DailyPredictionsService)

    for _ in range(20):
        result = retired_service.generate_daily_predictions("2026-09-09")
        assert result["status"] == "already_exists"
        assert test_engine.pool.checkedout() == 0

    for _ in range(20):
        db = factory()
        try:
            assert PunterService(db).get_all_punters(include_codes=False) == []
        finally:
            db.close()
        assert test_engine.pool.checkedout() == 0

    test_engine.dispose()


def test_punter_service_requires_a_caller_owned_session():
    from services.punter_service import PunterService

    with pytest.raises(TypeError):
        PunterService()


def test_retired_generator_is_absent_from_periodic_refresh():
    import main

    source = inspect.getsource(main._ensure_today_generated)
    assert "from services.daily_predictions_service" not in source
    assert ".generate_daily_predictions" not in source
    assert "build_daily_accumulators" in source


def test_legacy_ml_get_is_read_only_when_database_is_empty(monkeypatch):
    from api.endpoints import ml_predictions

    monkeypatch.setattr(ml_predictions, "_read_predictions_from_db", lambda _day: None)
    response = ml_predictions.get_todays_predictions(force_refresh=True)

    assert response["status"] == "no_predictions"
    assert response["predictions"] == []
    assert "daily-accumulators" in response["message"]


def test_production_code_does_not_advance_get_db_manually():
    root = Path(__file__).resolve().parents[1]
    files = [root / "main.py", root / "telegram_bot.py"]
    for directory in ("api", "growth", "leagues", "scripts", "services"):
        files.extend((root / directory).rglob("*.py"))

    offenders = [
        str(path.relative_to(root))
        for path in files
        if "next(get_db())" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_pool_snapshot_contains_counters_but_no_credentials(monkeypatch):
    import database

    test_engine = _queue_pool_engine()
    monkeypatch.setattr(database, "engine", test_engine)
    state = database.pool_status()

    assert state["pool_class"] == "QueuePool"
    assert state["checked_out"] == 0
    serialized = json.dumps(state)
    assert "DATABASE_URL" not in serialized
    assert "postgres" not in serialized.lower()
    assert "password" not in serialized.lower()

    test_engine.dispose()


def test_pool_timeout_has_retryable_safe_http_response(monkeypatch):
    import database
    from main import app
    from starlette.requests import Request

    test_engine = _queue_pool_engine()
    monkeypatch.setattr(database, "engine", test_engine)
    handler = app.exception_handlers[SQLAlchemyTimeoutError]
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/api/leagues/results",
        "headers": [],
        "query_string": b"",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "scheme": "http",
    })

    response = asyncio.run(handler(request, SQLAlchemyTimeoutError("pool exhausted")))
    body = response.body.decode("utf-8")

    assert response.status_code == 503
    assert "DATABASE_POOL_TIMEOUT" in body
    assert "DATABASE_URL" not in body
    assert "pool exhausted" not in body

    test_engine.dispose()
