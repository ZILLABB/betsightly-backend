"""
API endpoints for predictions.

Only the endpoints the frontend actually calls live here:
  GET /                      — consolidated predictions (all categories)
  GET /categories            — legacy alias of /
  GET /category/{category}   — single category
  GET /best/{category}       — best picks for a category
  GET /best                  — best picks across categories
  GET /{prediction_id}       — single prediction by ID (MUST stay registered last)

Legacy cache/training/enhanced endpoints were removed June 2026 — they
referenced optional services that were rarely available in production and
tripled the attack surface for no user-facing value.
"""

import logging
from typing import Optional
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from database import get_db
from services import prediction_engine
from utils.error_handling import handle_database_error
from utils.database_optimization import query_performance_monitor
from utils.security import check_rate_limit
from api.endpoints.prediction_types import (
    PredictionCategory,
    ResponseFormat,
    get_category_metadata,
    standardize_prediction_response,
)

router = APIRouter()

_standardize_prediction_response = standardize_prediction_response


@router.get("/")
@query_performance_monitor
def get_predictions(
    request: Request,
    date: Optional[date] = Query(None, description="Date to get predictions for (YYYY-MM-DD)"),
    category: Optional[PredictionCategory] = Query(None, description="Filter by specific category"),
    limit: int = Query(10, ge=1, le=100, description="Maximum number of predictions per category"),
    format: ResponseFormat = Query(ResponseFormat.SIMPLE, description="Response format"),
    best_only: bool = Query(False, description="Return only the best predictions")
):
    """Consolidated predictions endpoint with flexible filtering."""
    try:
        check_rate_limit(request)
        date_str = date.strftime("%Y-%m-%d") if date else datetime.now().strftime("%Y-%m-%d")

        predictions_data = prediction_engine.get_predictions(date_str, mode="advanced")
        if predictions_data.get("status") != "success":
            logger.warning("Advanced mode failed, falling back to basic")
            predictions_data = prediction_engine.get_predictions(date_str, mode="basic")

        categorized_predictions = predictions_data.get("categories", {})

        if category:
            category_predictions = categorized_predictions.get(category.value, [])
            if best_only:
                category_predictions = sorted(
                    category_predictions,
                    key=lambda p: p.get("confidence", 0),
                    reverse=True,
                )[:limit]
            return _standardize_prediction_response(category_predictions, category.value, format)

        result = {}
        for cat_name, cat_predictions in categorized_predictions.items():
            if best_only:
                cat_predictions = sorted(
                    cat_predictions,
                    key=lambda p: p.get("confidence", 0),
                    reverse=True,
                )[:limit]
            result[cat_name] = _standardize_prediction_response(cat_predictions, cat_name, format)

        if format == ResponseFormat.SIMPLE:
            return {cat_name: cat_data["predictions"] for cat_name, cat_data in result.items()}
        return {
            "date": date_str,
            "categories": result,
            "total_predictions": sum(len(cat["predictions"]) for cat in result.values()),
        }

    except Exception as e:
        logger.error(f"Error getting predictions: {str(e)}")
        raise handle_database_error(e, "getting predictions")


@router.get("/categories")
def get_prediction_categories_legacy(
    request: Request,
    date: Optional[date] = None
):
    """Legacy alias — use `/api/predictions/` instead."""
    return get_predictions(
        request=request,
        date=date,
        category=None,
        limit=10,
        format=ResponseFormat.SIMPLE,
        best_only=False,
    )


@router.get("/category/{category}")
def get_predictions_by_category_legacy(
    category: str,
    request: Request,
    date: Optional[date] = None,
    limit: int = Query(10, description="Maximum number of predictions to return"),
    best_only: bool = Query(True, description="Return only the best predictions")
):
    """Legacy alias — use `/api/predictions/?category={category}` instead."""
    try:
        category_enum = PredictionCategory(category)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Must be one of: {[c.value for c in PredictionCategory]}"
        )
    return get_predictions(
        request=request,
        date=date,
        category=category_enum,
        limit=limit,
        format=ResponseFormat.SIMPLE,
        best_only=best_only,
    )


@router.get("/best/{category}")
def get_best_predictions_by_category_legacy(
    category: str,
    request: Request,
    date: Optional[date] = None,
    limit: int = Query(3, description="Maximum number of predictions to return")
):
    """Legacy alias — use `/api/predictions/?category={category}&best_only=true` instead."""
    try:
        category_enum = PredictionCategory(category)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Must be one of: {[c.value for c in PredictionCategory]}"
        )
    return get_predictions(
        request=request,
        date=date,
        category=category_enum,
        limit=limit,
        format=ResponseFormat.SIMPLE,
        best_only=True,
    )


@router.get("/best")
def get_all_best_predictions_legacy(
    request: Request,
    date: Optional[date] = None,
    limit_per_category: int = Query(3, description="Maximum number of predictions per category")
):
    """Legacy alias — use `/api/predictions/?best_only=true` instead."""
    return get_predictions(
        request=request,
        date=date,
        category=None,
        limit=limit_per_category,
        format=ResponseFormat.SIMPLE,
        best_only=True,
    )


# IMPORTANT: this catch-all matches ANY single path segment under
# /api/predictions/, so it must be registered after every named route above.
# (It once shadowed /today, returning a confusing int-parsing error.)
@router.get("/{prediction_id}")
def get_prediction_by_id(
    prediction_id: str,
    db: Session = Depends(get_db)
):
    """Get a specific prediction by numeric ID."""
    if not prediction_id.isdigit():
        raise HTTPException(
            status_code=404,
            detail=f"Unknown predictions endpoint '/{prediction_id}'. "
                   f"Did you mean /api/ml-predictions/today or /api/accumulators/today?"
        )
    try:
        from prediction import Prediction
        prediction = db.query(Prediction).filter(Prediction.id == int(prediction_id)).first()
        if not prediction:
            raise HTTPException(status_code=404, detail="Prediction not found")
        return _standardize_prediction_response([prediction], format_type=ResponseFormat.DETAILED)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting prediction {prediction_id}: {str(e)}")
        raise handle_database_error(e, f"getting prediction {prediction_id}")
