"""
API router.
"""

from fastapi import APIRouter

# Import all endpoints (basketball temporarily disabled for Railway deployment)
from api.endpoints import betting_codes, predictions, fixtures, punters, bookmakers, dashboard, health, ml_predictions, daily_predictions, accumulators
# from api.endpoints import basketball_predictions  # Temporarily disabled for Railway

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(betting_codes.router, prefix="/betting-codes", tags=["betting-codes"])
api_router.include_router(predictions.router, prefix="/predictions", tags=["predictions"])
api_router.include_router(ml_predictions.router, prefix="/ml-predictions", tags=["ml-predictions"])
api_router.include_router(daily_predictions.router, prefix="/daily-predictions", tags=["daily-predictions"])
api_router.include_router(accumulators.router, prefix="/accumulators", tags=["accumulators"])
# api_router.include_router(basketball_predictions.router, prefix="/basketball-predictions", tags=["basketball-predictions"])  # Temporarily disabled
api_router.include_router(fixtures.router, prefix="/fixtures", tags=["fixtures"])
api_router.include_router(punters.router, prefix="/punters", tags=["punters"])
api_router.include_router(bookmakers.router, prefix="/bookmakers", tags=["bookmakers"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
