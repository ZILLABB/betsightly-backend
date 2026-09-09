"""Regression coverage for production startup memory and request tracing."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from fastapi import APIRouter


ROOT = Path(__file__).resolve().parents[1]


def test_production_startup_excludes_legacy_ml_and_keeps_current_routes():
    env = os.environ.copy()
    env.update(ENVIRONMENT="production", ENABLE_BACKGROUND_JOBS="false")
    env.pop("ENABLE_LEGACY_ML_API", None)
    env.pop("ENABLE_LEGACY_PREDICTION_SETTLEMENT", None)
    script = """
import json
import sys
import main
paths = {getattr(route, "path", None) for route in main.app.routes}
from fastapi.testclient import TestClient
with TestClient(main.app) as client:
    ml_status = client.get("/api/health/ml-status").json()
    ml_test = client.get("/api/health/ml-test").json()
print(json.dumps({
    "legacy_imported": "api.endpoints.ml_predictions" in sys.modules,
    "legacy_route": "/api/ml-predictions/today" in paths,
    "health": "/api/health" in paths,
    "builder": "/api/leagues/slip-builder/generate" in paths,
    "daily": "/api/leagues/daily-accumulators" in paths,
    "health_ml_status": ml_status.get("status"),
    "health_ml_test": ml_test.get("status"),
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=30, check=True,
    )
    report = json.loads(completed.stdout.strip().splitlines()[-1])
    assert report == {
        "legacy_imported": False,
        "legacy_route": False,
        "health": True,
        "builder": True,
        "daily": True,
        "health_ml_status": "disabled",
        "health_ml_test": "disabled",
    }


def test_explicit_flag_enables_compatibility_router(monkeypatch):
    import api.api as api_module

    monkeypatch.setenv("ENABLE_LEGACY_ML_API", "true")
    assert api_module._env_enabled("ENABLE_LEGACY_ML_API") is True

    compatibility = APIRouter()

    @compatibility.get("/today")
    def today():
        return {"status": "compatibility"}

    imported = []

    def fake_import(name):
        imported.append(name)
        return SimpleNamespace(router=compatibility)

    monkeypatch.setattr(api_module.importlib, "import_module", fake_import)
    router = APIRouter()
    assert api_module._mount_legacy_ml_router(router, enabled=True) is True
    assert imported == ["api.endpoints.ml_predictions"]
    assert "/ml-predictions/today" in {route.path for route in router.routes}


def test_disabled_compatibility_router_never_imports(monkeypatch):
    import api.api as api_module

    monkeypatch.setenv("ENABLE_LEGACY_ML_API", "false")
    assert api_module._env_enabled("ENABLE_LEGACY_ML_API") is False

    def fail_import(_name):
        raise AssertionError("disabled legacy module was imported")

    monkeypatch.setattr(api_module.importlib, "import_module", fail_import)
    assert api_module._mount_legacy_ml_router(APIRouter(), enabled=False) is False


def test_legacy_settlement_defaults_off_and_current_checker_is_callable(monkeypatch):
    import main

    monkeypatch.setattr(main, "BACKGROUND_JOBS_ENABLED", True)
    monkeypatch.setattr(main, "LEGACY_PREDICTION_SETTLEMENT_ENABLED", False)
    assert main._legacy_prediction_settlement_should_start() is False

    called = []
    main._start_current_results_checker(lambda: called.append("started"))
    assert called == ["started"]


def test_builder_request_trace_is_safe(client, caplog):
    caplog.set_level(logging.INFO, logger="main")
    response = client.post(
        "/api/leagues/slip-builder/generate?target=1&secret=query-secret",
        headers={
            "CF-Ray": "abc-123",
            "Authorization": "Bearer auth-secret",
            "Cookie": "session=cookie-secret",
            "X-API-Key": "api-secret",
        },
    )
    assert response.status_code == 200

    trace = next(
        record.getMessage() for record in caplog.records
        if record.getMessage().startswith("request_start ")
    )
    assert "method=POST" in trace
    assert "path=/api/leagues/slip-builder/generate" in trace
    assert "cf_ray=abc-123" in trace
    for secret in ("query-secret", "auth-secret", "cookie-secret", "api-secret"):
        assert secret not in trace


def test_runtime_memory_telemetry_has_no_environment_values(monkeypatch, caplog):
    from utils.runtime_metrics import log_runtime_memory, process_rss_mb

    monkeypatch.setenv("DATABASE_URL", "postgresql://secret@example.invalid/db")
    caplog.set_level(logging.INFO, logger="utils.runtime_metrics")
    assert process_rss_mb() is not None
    log_runtime_memory("builder_start", target=100, horizon="week")
    message = caplog.records[-1].getMessage()
    assert message.startswith("runtime_memory ")
    assert "postgresql" not in message
    assert "secret" not in message


def test_common_logging_import_does_not_eagerly_load_scientific_stack():
    env = os.environ.copy()
    script = """
import json
import sys
import utils.common
print(json.dumps({
    "pandas": "pandas" in sys.modules,
    "numpy": "numpy" in sys.modules,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=10, check=True,
    )
    assert json.loads(completed.stdout.strip()) == {
        "pandas": False,
        "numpy": False,
    }


def test_common_json_serializer_still_handles_scientific_values():
    import numpy as np
    import pandas as pd

    from utils.common import json_serializer

    assert json_serializer(pd.Timestamp("2026-09-09")) == "2026-09-09T00:00:00"
    assert json_serializer(np.int64(7)) == 7
    assert json_serializer(np.float64(1.25)) == 1.25
    assert json_serializer(np.array([1, 2])) == [1, 2]
    assert json_serializer(float("nan")) is None
