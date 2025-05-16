"""
API router.
"""

from fastapi import APIRouter

from app.api.endpoints import fixtures, predictions, dashboard

api_router = APIRouter()
api_router.include_router(fixtures.router, prefix="/fixtures", tags=["fixtures"])
api_router.include_router(predictions.router, prefix="/predictions", tags=["predictions"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
