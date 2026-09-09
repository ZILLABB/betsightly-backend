"""
API router.
"""

import importlib
import os

from fastapi import APIRouter

from api.endpoints import (
    betting_codes, predictions, fixtures, punters,
    bookmakers, dashboard, health,
    daily_predictions, accumulators, subscriptions,
)

def _env_enabled(name: str, default: bool = False) -> bool:
    fallback = "true" if default else "false"
    return os.getenv(name, fallback).strip().lower() in {"1", "true", "yes", "on"}


# This compatibility router imports pandas/joblib, loads every legacy model,
# reads the full historical CSV, and builds ELO/Dixon-Coles indexes.  The
# authoritative public product lives under /api/leagues, so production only
# pays that cost when an operator explicitly opts back into the retired API.
LEGACY_ML_API_ENABLED = _env_enabled("ENABLE_LEGACY_ML_API", default=False)


def _mount_legacy_ml_router(router: APIRouter, enabled: bool) -> bool:
    """Mount the retired ML API without importing it when disabled."""
    if not enabled:
        return False
    ml_predictions = importlib.import_module("api.endpoints.ml_predictions")
    router.include_router(
        ml_predictions.router, prefix="/ml-predictions", tags=["ml-predictions"]
    )
    return True

# Basketball re-enable when NBA data fetcher is production-ready:
# from api.endpoints import basketball_predictions

api_router = APIRouter()

# Health endpoints are intentionally unauthenticated (load-balancer probes need them)
api_router.include_router(health.router, prefix="/health", tags=["health"])

# Prediction data is public. Browser-delivered API keys are not secrets, so
# authentication belongs on the individual write/maintenance routes instead
# of on these routers wholesale. Each mutating endpoint carries
# Depends(require_api_key); GET endpoints remain usable by the public SPA.
api_router.include_router(betting_codes.router, prefix="/betting-codes", tags=["betting-codes"])
api_router.include_router(predictions.router, prefix="/predictions", tags=["predictions"])
# Keep this import inside the flag. Importing it at module scope defeats the
# memory guard even when the router is never mounted.
_mount_legacy_ml_router(api_router, LEGACY_ML_API_ENABLED)
api_router.include_router(daily_predictions.router, prefix="/daily-predictions", tags=["daily-predictions"])
api_router.include_router(accumulators.router, prefix="/accumulators", tags=["accumulators"])
api_router.include_router(fixtures.router, prefix="/fixtures", tags=["fixtures"])
api_router.include_router(punters.router, prefix="/punters", tags=["punters"])
api_router.include_router(bookmakers.router, prefix="/bookmakers", tags=["bookmakers"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])

# Subscription endpoints are unauthenticated (public subscribe/unsubscribe)
api_router.include_router(subscriptions.router, prefix="/notifications", tags=["notifications"])
