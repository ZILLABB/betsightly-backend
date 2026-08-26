"""
API router.
"""

import os

from fastapi import APIRouter

from api.endpoints import (
    betting_codes, predictions, fixtures, punters,
    bookmakers, dashboard, health,
    daily_predictions, accumulators, subscriptions,
)

# Importing the ML routes loads every model and the full historical dataset.
# That is appropriate for the production API, but makes unrelated unit tests
# pay tens of seconds and hundreds of MB merely to import the health route.
_lightweight_startup = os.getenv("ENVIRONMENT", "").strip().lower() == "test"
if not _lightweight_startup:
    from api.endpoints import ml_predictions

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
if not _lightweight_startup:
    api_router.include_router(ml_predictions.router, prefix="/ml-predictions", tags=["ml-predictions"])
api_router.include_router(daily_predictions.router, prefix="/daily-predictions", tags=["daily-predictions"])
api_router.include_router(accumulators.router, prefix="/accumulators", tags=["accumulators"])
api_router.include_router(fixtures.router, prefix="/fixtures", tags=["fixtures"])
api_router.include_router(punters.router, prefix="/punters", tags=["punters"])
api_router.include_router(bookmakers.router, prefix="/bookmakers", tags=["bookmakers"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])

# Subscription endpoints are unauthenticated (public subscribe/unsubscribe)
api_router.include_router(subscriptions.router, prefix="/notifications", tags=["notifications"])
