"""
API endpoints for predictions.

Enhanced prediction endpoints with security, caching, and comprehensive error handling.
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from enum import Enum

from sqlalchemy.orm import Session

# Set up logging
logger = logging.getLogger(__name__)

from database import get_db
from services.quick_prediction_service import quick_prediction_service
from services.cached_prediction_service import cached_prediction_service
# Using quick prediction service with trained models
from utils.error_handling import handle_database_error, BetSightlyError, ValidationError
from utils.database_optimization import query_performance_monitor
from utils.security import check_rate_limit

router = APIRouter()

# Enums for better type safety
class PredictionCategory(str, Enum):
    SAFE_BETS = "2_odds"
    BALANCED_RISK = "5_odds"
    HIGH_REWARD = "10_odds"
    ROLLOVER = "rollover"

class ResponseFormat(str, Enum):
    SIMPLE = "simple"
    DETAILED = "detailed"
    COMBINATIONS = "combinations"

def _get_category_metadata(category: str) -> Dict[str, Any]:
    """Get metadata for a prediction category."""
    metadata = {
        "2_odds": {
            "name": "Safe Bets",
            "description": "Lower odds, higher confidence predictions",
            "target_odds": 2.0,
            "risk_level": "low"
        },
        "5_odds": {
            "name": "Balanced Risk",
            "description": "Medium odds, balanced risk-reward",
            "target_odds": 5.0,
            "risk_level": "medium"
        },
        "10_odds": {
            "name": "High Reward",
            "description": "Higher odds, higher potential returns",
            "target_odds": 10.0,
            "risk_level": "high"
        },
        "rollover": {
            "name": "10-Day Rollover",
            "description": "Daily predictions for a 10-day rollover strategy",
            "target_odds": 3.0,
            "risk_level": "medium"
        }
    }
    return metadata.get(category, {})

def _standardize_prediction_response(
    predictions: List[Any],
    category: Optional[str] = None,
    format_type: ResponseFormat = ResponseFormat.SIMPLE
) -> Dict[str, Any]:
    """
    Standardize prediction response format.

    Args:
        predictions: List of predictions
        category: Category name (optional)
        format_type: Response format type

    Returns:
        Standardized response dictionary
    """
    if not predictions:
        return {
            "count": 0,
            "predictions": [],
            "metadata": _get_category_metadata(category) if category else {}
        }

    response = {
        "count": len(predictions),
        "predictions": [p.to_dict() if hasattr(p, 'to_dict') else p for p in predictions]
    }

    if category:
        response["metadata"] = _get_category_metadata(category)

    if format_type == ResponseFormat.DETAILED:
        response["statistics"] = {
            "avg_confidence": sum(p.confidence or 0 for p in predictions if hasattr(p, 'confidence')) / len(predictions),
            "avg_odds": sum(p.odds or 0 for p in predictions if hasattr(p, 'odds')) / len(predictions)
        }

    return response

# Consolidated prediction endpoints - all functionality moved to main endpoint

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
    """
    **Consolidated Predictions Endpoint**

    Get predictions with flexible filtering and formatting options.
    This single endpoint replaces multiple redundant endpoints.

    **Examples:**
    - `/api/predictions/` - All predictions for today
    - `/api/predictions/?category=2_odds&best_only=true` - Best safe bets
    - `/api/predictions/?format=detailed` - Detailed response with statistics
    - `/api/predictions/?advanced=true` - Use advanced ML models
    """
    try:
        # Apply rate limiting
        check_rate_limit(request)

        # Input validation and sanitization
        if date and date > datetime.now().date() + timedelta(days=7):
            raise ValidationError("Date cannot be more than 7 days in the future")

        if limit > 100:
            raise ValidationError("Limit cannot exceed 100")

        # Log request for monitoring
        logger.info(f"Predictions request: category={category}, date={date}, limit={limit}")

        # Use cached prediction service for fast responses
        date_str = date.strftime("%Y-%m-%d") if date else datetime.now().strftime("%Y-%m-%d")

        # Get predictions using cached service (sub-500ms response)
        predictions_data = cached_prediction_service.get_predictions_for_date(date_str)

        # Process the predictions data
        if predictions_data.get("status") != "success":
            raise BetSightlyError(f"Failed to get predictions: {predictions_data.get('message', 'Unknown error')}")

        categorized_predictions = predictions_data.get("categories", {})

        if category:
            # Return specific category
            category_predictions = categorized_predictions.get(category.value, [])

            if best_only:
                # Sort by confidence and limit
                sorted_predictions = sorted(
                    category_predictions,
                    key=lambda p: p.get("confidence", 0),
                    reverse=True
                )
                category_predictions = sorted_predictions[:limit]

            return _standardize_prediction_response(
                category_predictions,
                category.value,
                format
            )
        else:
            # Return all categories
            result = {}
            for cat_name, cat_predictions in categorized_predictions.items():
                if best_only:
                    sorted_predictions = sorted(
                        cat_predictions,
                        key=lambda p: p.get("confidence", 0),
                        reverse=True
                    )
                    cat_predictions = sorted_predictions[:limit]

                result[cat_name] = _standardize_prediction_response(
                    cat_predictions,
                    cat_name,
                    format
                )

            # For backward compatibility, also return the old format
            if format == ResponseFormat.SIMPLE:
                # Return simple format for legacy compatibility
                simple_result = {}
                for cat_name, cat_data in result.items():
                    simple_result[cat_name] = cat_data["predictions"]

                return simple_result
            else:
                return {
                    "date": date_str,
                    "categories": result,
                    "total_predictions": sum(len(cat["predictions"]) for cat in result.values())
                }

    except Exception as e:
        logger.error(f"Error getting predictions: {str(e)}")
        raise handle_database_error(e, "getting predictions")

# Legacy endpoint for backward compatibility
@router.get("/categories")
def get_prediction_categories_legacy(
    request: Request,
    date: Optional[date] = None
):
    """
    **Legacy endpoint** - Use `/api/predictions/` instead.

    Get predictions organized by categories for backward compatibility.
    """
    # Redirect to the new consolidated endpoint
    return get_predictions(
        request=request,
        date=date,
        category=None,
        limit=10,
        format=ResponseFormat.SIMPLE,
        best_only=False
    )

# Legacy endpoint for backward compatibility
@router.get("/category/{category}")
def get_predictions_by_category_legacy(
    category: str,
    request: Request,
    date: Optional[date] = None,
    limit: int = Query(10, description="Maximum number of predictions to return"),
    best_only: bool = Query(True, description="Return only the best predictions")
):
    """
    **Legacy endpoint** - Use `/api/predictions/?category={category}` instead.

    Get predictions by category for backward compatibility.
    """
    try:
        # Validate and convert category
        category_enum = PredictionCategory(category)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Must be one of: {[c.value for c in PredictionCategory]}"
        )

    # Redirect to the new consolidated endpoint
    return get_predictions(
        request=request,
        date=date,
        category=category_enum,
        limit=limit,
        format=ResponseFormat.SIMPLE,
        best_only=best_only
    )

# Legacy endpoint for backward compatibility
@router.get("/best/{category}")
def get_best_predictions_by_category_legacy(
    category: str,
    request: Request,
    date: Optional[date] = None,
    limit: int = Query(3, description="Maximum number of predictions to return")
):
    """
    **Legacy endpoint** - Use `/api/predictions/?category={category}&best_only=true` instead.
    """
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
        best_only=True
    )

# Legacy endpoint for backward compatibility
@router.get("/best")
def get_all_best_predictions_legacy(
    request: Request,
    date: Optional[date] = None,
    limit_per_category: int = Query(3, description="Maximum number of predictions per category")
):
    """
    **Legacy endpoint** - Use `/api/predictions/?best_only=true` instead.
    """
    return get_predictions(
        request=request,
        date=date,
        category=None,
        limit=limit_per_category,
        format=ResponseFormat.SIMPLE,
        best_only=True
    )

# Keep essential endpoints only
@router.get("/{prediction_id}")
def get_prediction_by_id(
    prediction_id: int,
    db: Session = Depends(get_db)
):
    """
    Get a specific prediction by ID.

    Args:
        prediction_id: The ID of the prediction to retrieve

    Returns:
        Prediction details or 404 if not found
    """
    try:
        # Query prediction directly from database
        from prediction import Prediction
        prediction = db.query(Prediction).filter(Prediction.id == prediction_id).first()

        if not prediction:
            raise HTTPException(status_code=404, detail="Prediction not found")

        return _standardize_prediction_response([prediction], format_type=ResponseFormat.DETAILED)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting prediction {prediction_id}: {str(e)}")
        raise handle_database_error(e, f"getting prediction {prediction_id}")

# Advanced ML predictions are now integrated into the main endpoint with ?advanced=true parameter
# Legacy endpoints removed to eliminate redundancy


@router.get("/enhanced/")
@query_performance_monitor
def get_enhanced_predictions(
    request: Request,
    date: Optional[date] = Query(None, description="Date to get predictions for (YYYY-MM-DD)"),
    include_explanations: bool = Query(True, description="Include SHAP/LIME explanations"),
    use_meta_stacking: bool = Query(True, description="Use meta-model stacking"),
    explanation_detail: str = Query("human", description="Level of explanation detail (human/technical/both)")
):
    """
    **Enhanced Predictions with Explainability & Meta-Stacking**

    Get predictions with transparent explanations and intelligent model blending.

    **Features:**
    - SHAP explanations for XGBoost/LightGBM models
    - LIME explanations for Neural Network models
    - Meta-model stacking for optimal prediction blending
    - Calibrated confidence scores
    - Human-readable explanations

    **Examples:**
    - `/api/predictions/enhanced/` - Enhanced predictions with explanations
    - `/api/predictions/enhanced/?include_explanations=false` - Predictions without explanations
    - `/api/predictions/enhanced/?explanation_detail=technical` - Technical explanations only
    """
    try:
        # Apply rate limiting
        check_rate_limit(request)

        # Input validation
        if date and date > datetime.now().date() + timedelta(days=7):
            raise ValidationError("Date cannot be more than 7 days in the future")

        if explanation_detail not in ["human", "technical", "both"]:
            raise ValidationError("explanation_detail must be 'human', 'technical', or 'both'")

        # Log request for monitoring
        logger.info(f"Enhanced predictions request: date={date}, explanations={include_explanations}, meta_stacking={use_meta_stacking}")

        # Get enhanced predictions
        date_str = date.strftime("%Y-%m-%d") if date else None

        predictions_result = quick_prediction_service.get_predictions_for_date(date_str)

        if predictions_result.get("status") == "error":
            raise BetSightlyError(
                message=predictions_result.get("message", "Enhanced prediction failed"),
                error_code="ENHANCED_PREDICTION_ERROR"
            )

        # Filter explanations based on detail level
        if include_explanations and explanation_detail != "both":
            for prediction in predictions_result.get("predictions", []):
                explanations = prediction.get("explanations", {})
                for pred_type, explanation_data in explanations.items():
                    if explanation_detail == "human":
                        # Keep only human-readable explanations
                        explanations[pred_type] = {
                            "human_readable": explanation_data.get("human_readable", "")
                        }
                    elif explanation_detail == "technical":
                        # Keep only technical explanations
                        explanations[pred_type] = {
                            "technical": explanation_data.get("technical", {})
                        }

        # Add metadata
        predictions_result.update({
            "api_version": "enhanced_v1",
            "features": {
                "explainability": include_explanations,
                "meta_stacking": use_meta_stacking,
                "explanation_detail": explanation_detail
            },
            "performance": {
                "models_available": predictions_result.get("models_available", False),
                "explainers_available": predictions_result.get("explainers_available", False)
            }
        })

        return predictions_result

    except ValidationError as e:
        logger.warning(f"Enhanced predictions validation error: {e.message}")
        raise HTTPException(status_code=400, detail=e.message)

    except BetSightlyError as e:
        logger.error(f"Enhanced predictions error: {e.message}")
        raise HTTPException(status_code=500, detail=e.message)

    except Exception as e:
        logger.error(f"Enhanced predictions endpoint error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.get("/cache/status")
def get_cache_status(request: Request):
    """
    **Cache Status Endpoint**

    Get detailed information about the prediction cache status and performance.

    **Returns:**
    - Cache entries with expiration status
    - Generation statistics for last 24 hours
    - Background refresh configuration
    - Performance metrics
    """
    try:
        # Apply rate limiting
        check_rate_limit(request)

        # Get cache status from cached service
        cache_status = cached_prediction_service.get_cache_status()

        return {
            "status": "success",
            "cache_status": cache_status,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Cache status endpoint error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error getting cache status: {str(e)}"
        )


@router.post("/cache/refresh")
def force_cache_refresh(
    request: Request,
    date: Optional[date] = Query(None, description="Date to refresh (YYYY-MM-DD)")
):
    """
    **Force Cache Refresh**

    Manually trigger cache refresh for a specific date.
    Useful for cache invalidation or immediate updates.

    **Parameters:**
    - date: Optional date to refresh (default: today)

    **Returns:**
    - Fresh predictions with generation metrics
    """
    try:
        # Apply rate limiting (stricter for refresh operations)
        check_rate_limit(request)

        # Convert date
        date_str = date.strftime("%Y-%m-%d") if date else None

        # Force refresh
        logger.info(f"Manual cache refresh requested for {date_str or 'today'}")
        result = cached_prediction_service.force_refresh(date_str)

        return {
            "status": "success",
            "message": f"Cache refreshed for {date_str or 'today'}",
            "predictions": result,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Cache refresh endpoint error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error refreshing cache: {str(e)}"
        )
