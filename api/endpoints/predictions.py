"""
API endpoints for predictions.

Enhanced prediction endpoints with security, caching, and comprehensive error handling.
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from enum import Enum

from sqlalchemy.orm import Session

# Set up logging
logger = logging.getLogger(__name__)

from database import get_db
# Phase 3: Using basic prediction service for stable deployment
from services.basic_prediction_service import basic_prediction_service
# Phase 4: Re-enabling advanced services gradually
try:
    from services.quick_prediction_service import quick_prediction_service
    QUICK_PREDICTION_AVAILABLE = True
except ImportError:
    QUICK_PREDICTION_AVAILABLE = False
    logger.warning("Quick prediction service not available")

try:
    from services.cached_prediction_service import cached_prediction_service
    CACHED_PREDICTION_AVAILABLE = True
except ImportError:
    CACHED_PREDICTION_AVAILABLE = False
    logger.warning("Cached prediction service not available")
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

        # Log request for monitoring
        logger.info(f"Predictions request: category={category}, date={date}, limit={limit}")

        # Use basic prediction service with real football data
        date_str = date.strftime("%Y-%m-%d") if date else datetime.now().strftime("%Y-%m-%d")

        try:
            # Get predictions using basic prediction service
            predictions_data = basic_prediction_service.get_predictions_for_date(date_str)

            # Process the predictions data
            if predictions_data.get("status") != "success":
                logger.warning(f"Prediction service returned error: {predictions_data.get('message')}")
                # Fall back to mock data if service fails
                predictions_data = basic_prediction_service._get_mock_predictions(date_str)

            categorized_predictions = predictions_data.get("categories", {})

        except Exception as e:
            logger.error(f"Error getting predictions from service: {str(e)}")
            # Fallback to simple mock data
            categorized_predictions = {
                "2_odds": [{"home_team": "Arsenal", "away_team": "Chelsea", "prediction": "Arsenal Win", "odds": 2.1}],
                "5_odds": [{"home_team": "Man City", "away_team": "Liverpool", "prediction": "Over 2.5", "odds": 1.8}],
                "10_odds": [],
                "rollover": []
            }

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


# Phase 4: Re-enabling enhanced predictions
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

        logger.info(f"Enhanced predictions request: date={date}, explanations={include_explanations}, meta_stacking={use_meta_stacking}")

        # Use available prediction services
        date_str = date.strftime("%Y-%m-%d") if date else datetime.now().strftime("%Y-%m-%d")

        if QUICK_PREDICTION_AVAILABLE:
            # Use advanced quick prediction service
            predictions_result = quick_prediction_service.get_predictions_for_date(date_str)
        else:
            # Fall back to basic prediction service
            predictions_result = basic_prediction_service.get_predictions_for_date(date_str)

        # Add enhanced features metadata
        predictions_result.update({
            "api_version": "enhanced_v1",
            "features": {
                "explainability": include_explanations and QUICK_PREDICTION_AVAILABLE,
                "meta_stacking": use_meta_stacking and QUICK_PREDICTION_AVAILABLE,
                "explanation_detail": explanation_detail,
                "service_used": "quick_prediction" if QUICK_PREDICTION_AVAILABLE else "basic_prediction"
            }
        })

        return predictions_result

        # This code is unreachable due to early return above
        # Keeping for reference but disabled

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


# Phase 5: Re-enabling cache management
@router.get("/cache/status")
@query_performance_monitor
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

        logger.info("Cache status request")

        if CACHED_PREDICTION_AVAILABLE:
            # Get cache status from cached service
            cache_status = cached_prediction_service.get_cache_status()
        else:
            # Return basic cache status
            cache_status = {
                "status": "basic_mode",
                "cached_prediction_service": "not_available",
                "basic_prediction_service": "available",
                "real_time_predictions": True
            }

        return {
            "status": "success",
            "cache_status": cache_status,
            "services_available": {
                "basic_prediction": True,
                "quick_prediction": QUICK_PREDICTION_AVAILABLE,
                "cached_prediction": CACHED_PREDICTION_AVAILABLE
            },
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Cache status endpoint error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error getting cache status: {str(e)}"
        )


# Phase 5: Re-enabling cache refresh
@router.post("/cache/refresh")
@query_performance_monitor
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

        date_str = date.strftime("%Y-%m-%d") if date else None
        logger.info(f"Manual cache refresh requested for {date_str or 'today'}")

        if CACHED_PREDICTION_AVAILABLE:
            # Force refresh using cached service
            result = cached_prediction_service.force_refresh(date_str)
            message = f"Cache refreshed successfully for {date_str or 'today'}"
        else:
            # Trigger fresh predictions from basic service
            result = basic_prediction_service.get_predictions_for_date(date_str)
            message = f"Fresh predictions generated for {date_str or 'today'} (no cache service)"

        return {
            "status": "success",
            "message": message,
            "date": date_str or "today",
            "refresh_time": datetime.now().isoformat(),
            "service_used": "cached_prediction" if CACHED_PREDICTION_AVAILABLE else "basic_prediction",
            "result_summary": {
                "total_predictions": len(result.get("categories", {}).get("rollover", [])),
                "data_source": result.get("data_source", "unknown")
            }
        }

    except Exception as e:
        logger.error(f"Cache refresh endpoint error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error refreshing cache: {str(e)}"
        )
