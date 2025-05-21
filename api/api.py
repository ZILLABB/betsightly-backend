"""
API router.
"""

from fastapi import APIRouter

from app.api.endpoints import fixtures, predictions, dashboard, punters, betting_codes, bookmakers

api_router = APIRouter()
api_router.include_router(fixtures.router, prefix="/fixtures", tags=["fixtures"])
api_router.include_router(predictions.router, prefix="/predictions", tags=["predictions"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(punters.router, prefix="/punters", tags=["punters"])
api_router.include_router(betting_codes.router, prefix="/betting-codes", tags=["betting-codes"])
api_router.include_router(bookmakers.router, prefix="/bookmakers", tags=["bookmakers"])
