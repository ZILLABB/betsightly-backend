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
# Phase 5: Advanced ML Integration - Using sophisticated models
from services.basic_prediction_service import basic_prediction_service

# Import advanced prediction service
try:
    from services.advanced_prediction_service import advanced_prediction_service
    ADVANCED_PREDICTION_AVAILABLE = True
    logger.info("✅ Advanced prediction service loaded")
except ImportError:
    ADVANCED_PREDICTION_AVAILABLE = False
    logger.warning("❌ Advanced prediction service not available")

# Import quick prediction service
try:
    from services.quick_prediction_service import quick_prediction_service
    QUICK_PREDICTION_AVAILABLE = True
    logger.info("✅ Quick prediction service loaded")
except ImportError:
    QUICK_PREDICTION_AVAILABLE = False
    logger.warning("❌ Quick prediction service not available")

# Import cached prediction service
try:
    from services.cached_prediction_service import cached_prediction_service
    CACHED_PREDICTION_AVAILABLE = True
    logger.info("✅ Cached prediction service loaded")
except ImportError:
    CACHED_PREDICTION_AVAILABLE = False
    logger.warning("❌ Cached prediction service not available")

# Import daily prediction cache service
try:
    from services.daily_prediction_cache import daily_prediction_cache
    DAILY_CACHE_AVAILABLE = True
    logger.info("✅ Daily prediction cache service loaded")
except ImportError:
    DAILY_CACHE_AVAILABLE = False
    logger.warning("❌ Daily prediction cache service not available")

# Import training pipeline service
try:
    from services.training_pipeline_service import training_pipeline_service
    TRAINING_PIPELINE_AVAILABLE = True
    logger.info("✅ Training pipeline service loaded")
except ImportError:
    TRAINING_PIPELINE_AVAILABLE = False
    logger.warning("❌ Training pipeline service not available")
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

        # Use advanced ML prediction service for maximum accuracy
        date_str = date.strftime("%Y-%m-%d") if date else datetime.now().strftime("%Y-%m-%d")

        try:
            # Priority 1: Use Daily Prediction Cache (Fastest)
            if DAILY_CACHE_AVAILABLE:
                logger.info("💾 Using Daily Prediction Cache")
                predictions_data = daily_prediction_cache.get_cached_predictions(date_str, category.value if category else None)
                service_used = "daily_prediction_cache"

                # If cache miss, fall through to real-time generation
                if predictions_data.get('source') != 'cache':
                    logger.info("🔄 Cache miss - falling through to real-time generation")
                    raise Exception("Cache miss")

            # Priority 2: Use Advanced ML Service (XGBoost + Ensemble)
            elif ADVANCED_PREDICTION_AVAILABLE:
                logger.info("🚀 Using Advanced ML Prediction Service")
                predictions_data = advanced_prediction_service.get_predictions_for_date(date_str)
                service_used = "advanced_prediction_service"

            # Priority 3: Use Quick Prediction Service (Pre-trained models)
            elif QUICK_PREDICTION_AVAILABLE:
                logger.info("⚡ Using Quick Prediction Service")
                predictions_data = quick_prediction_service.get_predictions_for_date(date_str)
                service_used = "quick_prediction_service"

            # Priority 4: Use Cached Prediction Service
            elif CACHED_PREDICTION_AVAILABLE:
                logger.info("💾 Using Cached Prediction Service")
                predictions_data = cached_prediction_service.get_predictions_for_date(date_str)
                service_used = "cached_prediction_service"

            # Fallback: Use Basic Prediction Service
            else:
                logger.info("🔧 Using Basic Prediction Service (fallback)")
                predictions_data = basic_prediction_service.get_predictions_for_date(date_str)
                service_used = "basic_prediction_service"

            # Process the predictions data
            if predictions_data.get("status") != "success":
                logger.warning(f"Prediction service returned error: {predictions_data.get('message')}")
                # Fall back to basic service if advanced fails
                if service_used != "basic_prediction_service":
                    logger.info("🔄 Falling back to basic prediction service")
                    predictions_data = basic_prediction_service.get_predictions_for_date(date_str)
                    service_used = "basic_prediction_service"

            categorized_predictions = predictions_data.get("categories", {})

            # Add service metadata to response
            if "metadata" not in predictions_data:
                predictions_data["metadata"] = {}
            predictions_data["metadata"]["service_used"] = service_used

        except Exception as e:
            logger.error(f"Error getting predictions from advanced services: {str(e)}")
            # Final fallback to simple mock data
            categorized_predictions = {
                "2_odds": [{"home_team": "Arsenal", "away_team": "Chelsea", "prediction": "Arsenal Win", "odds": 2.1, "confidence": 75}],
                "5_odds": [{"home_team": "Man City", "away_team": "Liverpool", "prediction": "Over 2.5", "odds": 1.8, "confidence": 65}],
                "10_odds": [{"home_team": "Real Madrid", "away_team": "Barcelona", "prediction": "BTTS Yes", "odds": 8.5, "confidence": 45}],
                "rollover": [{"home_team": "Bayern Munich", "away_team": "Dortmund", "prediction": "Bayern Win", "odds": 1.9, "confidence": 80}]
            }
            service_used = "fallback_mock_data"

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

        # Use the most advanced available prediction service
        date_str = date.strftime("%Y-%m-%d") if date else datetime.now().strftime("%Y-%m-%d")

        # Priority 1: Use Advanced ML Service with full explanations
        if ADVANCED_PREDICTION_AVAILABLE:
            logger.info("🚀 Using Advanced ML Service for enhanced predictions")
            predictions_result = advanced_prediction_service.get_enhanced_predictions_with_explanations(
                date_str=date_str,
                include_explanations=include_explanations,
                explanation_detail=explanation_detail
            )
            service_used = "advanced_prediction_service"
            advanced_features = True

        # Priority 2: Use Quick Prediction Service
        elif QUICK_PREDICTION_AVAILABLE:
            logger.info("⚡ Using Quick Prediction Service for enhanced predictions")
            predictions_result = quick_prediction_service.get_predictions_for_date(date_str)
            service_used = "quick_prediction_service"
            advanced_features = True

        # Fallback: Use Basic Prediction Service
        else:
            logger.info("🔧 Using Basic Prediction Service for enhanced predictions")
            predictions_result = basic_prediction_service.get_predictions_for_date(date_str)
            service_used = "basic_prediction_service"
            advanced_features = False

        # Add enhanced features metadata
        predictions_result.update({
            "api_version": "enhanced_v2",
            "enhanced_features": {
                "explainability": include_explanations and ADVANCED_PREDICTION_AVAILABLE,
                "meta_stacking": use_meta_stacking and ADVANCED_PREDICTION_AVAILABLE,
                "explanation_detail": explanation_detail,
                "service_used": service_used,
                "advanced_ml_models": ADVANCED_PREDICTION_AVAILABLE,
                "xgboost_models": ADVANCED_PREDICTION_AVAILABLE,
                "ensemble_voting": ADVANCED_PREDICTION_AVAILABLE,
                "shap_explanations": include_explanations and ADVANCED_PREDICTION_AVAILABLE,
                "feature_engineering": "advanced" if ADVANCED_PREDICTION_AVAILABLE else "basic"
            },
            "model_info": advanced_prediction_service.get_model_info() if ADVANCED_PREDICTION_AVAILABLE else {
                "message": "Advanced models not available - using fallback service"
            }
        })

        return predictions_result

    except ValidationError as e:
        logger.warning(f"Enhanced predictions validation error: {e.message}")
        raise HTTPException(status_code=400, detail=e.message)

    except BetSightlyError as e:
        logger.error(f"Enhanced predictions error: {e.message}")
        raise HTTPException(status_code=500, detail=e.message)


# ============================================================================
# TRAINING PIPELINE & CACHING ENDPOINTS
# ============================================================================

@router.post("/models/retrain")
def trigger_model_retraining(
    request: Request,
    force_retrain: bool = Query(False, description="Force retraining even if not needed"),
    training_type: str = Query("manual", description="Type of training (manual/scheduled/triggered)")
):
    """
    **Trigger Model Retraining**

    Manually trigger the training pipeline to retrain ML models with new data.

    **Features:**
    - Continuous learning from new match results
    - Performance monitoring and validation
    - Automatic deployment of improved models
    - Training progress tracking

    **Examples:**
    - `POST /api/predictions/models/retrain` - Standard retraining
    - `POST /api/predictions/models/retrain?force_retrain=true` - Force retraining
    """
    try:
        # Apply rate limiting for training requests
        check_rate_limit(request)

        if not TRAINING_PIPELINE_AVAILABLE:
            raise HTTPException(
                status_code=503,
                detail="Training pipeline service not available"
            )

        logger.info(f"🚀 Manual training request: force={force_retrain}, type={training_type}")

        # Trigger training pipeline
        training_result = training_pipeline_service.trigger_training(
            training_type=training_type,
            trigger_reason="manual_request",
            force_retrain=force_retrain
        )

        if training_result.get('status') == 'success':
            return {
                "status": "success",
                "message": "Training pipeline started successfully",
                "training_run_id": training_result.get('training_run_id'),
                "estimated_completion_time": "15-30 minutes",
                "training_details": training_result
            }
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Training failed: {training_result.get('error', 'Unknown error')}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error triggering training: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Training request failed: {str(e)}")


@router.get("/models/training/status")
def get_training_status():
    """
    **Get Training Status**

    Check the status of current and recent training runs.

    **Returns:**
    - Current training status
    - Recent training history
    - Model performance metrics
    - Next scheduled training
    """
    try:
        if not TRAINING_PIPELINE_AVAILABLE:
            return {
                "status": "unavailable",
                "message": "Training pipeline service not available"
            }

        # Get training status from database
        from database import SessionLocal
        from models.training_models import ModelTrainingRun

        db = SessionLocal()

        try:
            # Get current running training
            current_training = db.query(ModelTrainingRun).filter(
                ModelTrainingRun.status == 'running'
            ).first()

            # Get recent training runs
            recent_trainings = db.query(ModelTrainingRun).order_by(
                ModelTrainingRun.started_at.desc()
            ).limit(5).all()

            return {
                "status": "success",
                "current_training": current_training.to_dict() if current_training else None,
                "recent_trainings": [training.to_dict() for training in recent_trainings],
                "training_pipeline_available": TRAINING_PIPELINE_AVAILABLE,
                "next_scheduled_training": "Weekly (Sundays at 2 AM UTC)"
            }

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error getting training status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get training status: {str(e)}")


@router.post("/cache/generate")
def generate_daily_cache(
    request: Request,
    date: Optional[date] = Query(None, description="Date to generate cache for (default: today)"),
    force_refresh: bool = Query(False, description="Force refresh even if cache exists")
):
    """
    **Generate Daily Prediction Cache**

    Generate and cache predictions for a specific date to optimize API performance.

    **Features:**
    - Batch ML prediction generation
    - Database caching with expiration
    - Performance optimization
    - Cache status tracking

    **Examples:**
    - `POST /api/predictions/cache/generate` - Generate cache for today
    - `POST /api/predictions/cache/generate?date=2025-06-07` - Generate for specific date
    """
    try:
        # Apply rate limiting
        check_rate_limit(request)

        if not DAILY_CACHE_AVAILABLE:
            raise HTTPException(
                status_code=503,
                detail="Daily prediction cache service not available"
            )

        date_str = date.strftime("%Y-%m-%d") if date else datetime.now().strftime("%Y-%m-%d")

        logger.info(f"🔄 Manual cache generation request for {date_str}")

        # Check if cache already exists and is fresh
        if not force_refresh:
            existing_cache = daily_prediction_cache.get_cached_predictions(date_str)
            if existing_cache.get('source') == 'cache':
                return {
                    "status": "success",
                    "message": f"Cache for {date_str} already exists and is fresh",
                    "cache_details": existing_cache.get('metadata', {}),
                    "action": "no_action_needed"
                }

        # Generate new cache
        cache_result = daily_prediction_cache.generate_daily_predictions(date_str)

        if cache_result.get('status') == 'success':
            return {
                "status": "success",
                "message": f"Daily cache generated successfully for {date_str}",
                "cache_details": cache_result,
                "estimated_generation_time": f"{cache_result.get('generation_time_seconds', 0):.2f} seconds"
            }
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Cache generation failed: {cache_result.get('error', 'Unknown error')}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating cache: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Cache generation failed: {str(e)}")


@router.get("/cache/status")
def get_cache_status(
    date: Optional[date] = Query(None, description="Date to check cache status for")
):
    """
    **Get Cache Status**

    Check the status and health of the prediction cache system.

    **Returns:**
    - Cache freshness and expiration
    - Performance metrics
    - Cache hit rates
    - Health indicators
    """
    try:
        date_str = date.strftime("%Y-%m-%d") if date else datetime.now().strftime("%Y-%m-%d")

        from database import SessionLocal
        from models.training_models import CacheStatus, PredictionBatch

        db = SessionLocal()

        try:
            # Get cache status
            cache_status = db.query(CacheStatus).filter(
                CacheStatus.cache_date == date_str
            ).first()

            # Get batch info
            batch_info = db.query(PredictionBatch).filter(
                PredictionBatch.batch_date == date_str
            ).first()

            # Check if cached predictions exist
            cached_predictions = daily_prediction_cache.get_cached_predictions(date_str) if DAILY_CACHE_AVAILABLE else None

            return {
                "status": "success",
                "date": date_str,
                "cache_status": cache_status.to_dict() if cache_status else None,
                "batch_info": batch_info.to_dict() if batch_info else None,
                "cache_available": cached_predictions.get('source') == 'cache' if cached_predictions else False,
                "daily_cache_service_available": DAILY_CACHE_AVAILABLE,
                "cache_health": "healthy" if cache_status and not cache_status.is_stale else "stale_or_missing"
            }

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error getting cache status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get cache status: {str(e)}")


@router.delete("/cache/clear")
def clear_cache(
    request: Request,
    date: Optional[date] = Query(None, description="Date to clear cache for (default: all)")
):
    """
    **Clear Prediction Cache**

    Clear cached predictions for a specific date or all dates.

    **Use Cases:**
    - Clear stale cache data
    - Force cache regeneration
    - Maintenance operations
    """
    try:
        # Apply rate limiting
        check_rate_limit(request)

        from database import SessionLocal
        from models.training_models import CachedPrediction, CacheStatus

        db = SessionLocal()

        try:
            if date:
                date_str = date.strftime("%Y-%m-%d")

                # Clear specific date
                deleted_predictions = db.query(CachedPrediction).filter(
                    CachedPrediction.prediction_date == date_str
                ).delete()

                # Update cache status
                cache_status = db.query(CacheStatus).filter(
                    CacheStatus.cache_date == date_str
                ).first()

                if cache_status:
                    cache_status.is_stale = True
                    cache_status.health_status = 'cleared'

                db.commit()

                return {
                    "status": "success",
                    "message": f"Cache cleared for {date_str}",
                    "predictions_deleted": deleted_predictions
                }
            else:
                # Clear all cache
                deleted_predictions = db.query(CachedPrediction).delete()
                deleted_status = db.query(CacheStatus).delete()

                db.commit()

                return {
                    "status": "success",
                    "message": "All cache cleared",
                    "predictions_deleted": deleted_predictions,
                    "status_records_deleted": deleted_status
                }

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error clearing cache: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to clear cache: {str(e)}")


@router.get("/models/info")
@query_performance_monitor
def get_advanced_models_info(request: Request):
    """
    **Advanced ML Models Information**

    Get detailed information about the loaded ML models and their capabilities.

    **Returns:**
    - Model counts by type (XGBoost, Ensemble, Enhanced)
    - Available features (SHAP, LIME, Meta-stacking)
    - Model performance metrics
    - Service availability status
    """
    try:
        # Apply rate limiting
        check_rate_limit(request)

        logger.info("Advanced models info request")

        # Get comprehensive model information
        if ADVANCED_PREDICTION_AVAILABLE:
            model_info = advanced_prediction_service.get_model_info()
            service_status = "advanced_ml_active"
        else:
            model_info = {
                "total_models": 0,
                "model_types": {"xgboost": 0, "enhanced": 0, "advanced": 0, "quick": 0},
                "explainers": 0,
                "advanced_features": {
                    "feature_engineering": False,
                    "shap_explanations": False,
                    "lime_explanations": False,
                    "meta_stacking": False,
                    "ensemble_voting": False
                },
                "models": []
            }
            service_status = "basic_ml_only"

        # Service availability summary
        services_available = {
            "advanced_prediction_service": ADVANCED_PREDICTION_AVAILABLE,
            "quick_prediction_service": QUICK_PREDICTION_AVAILABLE,
            "cached_prediction_service": CACHED_PREDICTION_AVAILABLE,
            "basic_prediction_service": True
        }

        # ML capabilities summary
        ml_capabilities = {
            "xgboost_models": ADVANCED_PREDICTION_AVAILABLE,
            "ensemble_models": ADVANCED_PREDICTION_AVAILABLE,
            "shap_explanations": ADVANCED_PREDICTION_AVAILABLE,
            "lime_explanations": ADVANCED_PREDICTION_AVAILABLE,
            "meta_model_stacking": ADVANCED_PREDICTION_AVAILABLE,
            "advanced_feature_engineering": ADVANCED_PREDICTION_AVAILABLE,
            "real_time_predictions": True,
            "prediction_categories": ["2_odds", "5_odds", "10_odds", "rollover"]
        }

        return {
            "status": "success",
            "service_status": service_status,
            "model_info": model_info,
            "services_available": services_available,
            "ml_capabilities": ml_capabilities,
            "api_endpoints": {
                "basic_predictions": "/api/predictions/",
                "enhanced_predictions": "/api/predictions/enhanced/",
                "cache_status": "/api/predictions/cache/status",
                "model_info": "/api/predictions/models/info"
            },
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Models info endpoint error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error getting models info: {str(e)}"
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
