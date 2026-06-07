"""
Health Check API Endpoints

This module provides health check endpoints to monitor the application status.
"""

import logging
import os
from datetime import datetime
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db
from utils.config import settings

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
def health_check():
    """
    Basic health check endpoint.
    
    Returns:
        Basic health status
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "BetSightly Backend API"
    }


@router.get("/detailed")
def detailed_health_check(db: Session = Depends(get_db)):
    """
    Detailed health check that verifies all critical components.
    
    Returns:
        Comprehensive health status including database, API keys, and models
    """
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "BetSightly Backend API",
        "version": "1.0.0",
        "checks": {}
    }
    
    overall_healthy = True
    
    # Check database connectivity
    try:
        db.execute(text("SELECT 1"))
        health_status["checks"]["database"] = {
            "status": "healthy",
            "message": "Database connection successful"
        }
    except Exception as e:
        logger.error(f"Database health check failed: {str(e)}")
        health_status["checks"]["database"] = {
            "status": "unhealthy",
            "message": f"Database connection failed: {str(e)}"
        }
        overall_healthy = False
    
    # Check API keys configuration
    api_keys_status = check_api_keys()
    health_status["checks"]["api_keys"] = api_keys_status
    if api_keys_status["status"] != "healthy":
        overall_healthy = False
    
    # Check model availability
    models_status = check_models()
    health_status["checks"]["models"] = models_status
    if models_status["status"] != "healthy":
        overall_healthy = False
    
    # Check external API connectivity
    external_apis_status = check_external_apis()
    health_status["checks"]["external_apis"] = external_apis_status
    if external_apis_status["status"] != "healthy":
        overall_healthy = False
    
    # Check file system permissions
    filesystem_status = check_filesystem()
    health_status["checks"]["filesystem"] = filesystem_status
    if filesystem_status["status"] != "healthy":
        overall_healthy = False
    
    # Set overall status
    health_status["status"] = "healthy" if overall_healthy else "unhealthy"
    
    # Return appropriate HTTP status
    if not overall_healthy:
        raise HTTPException(status_code=503, detail=health_status)
    
    return health_status


def check_api_keys() -> Dict[str, Any]:
    """Check if required API keys are configured."""
    try:
        missing_keys = []
        
        # Check Football Data API key
        if not settings.football_data.API_KEY:
            missing_keys.append("FOOTBALL_DATA_API_KEY")

        # Check API Football key
        if not settings.api_football.API_KEY:
            missing_keys.append("API_FOOTBALL_API_KEY")
        
        if missing_keys:
            return {
                "status": "unhealthy",
                "message": f"Missing API keys: {', '.join(missing_keys)}",
                "missing_keys": missing_keys
            }
        
        return {
            "status": "healthy",
            "message": "All required API keys are configured"
        }
        
    except Exception as e:
        logger.error(f"API keys check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "message": f"Error checking API keys: {str(e)}"
        }


def check_models() -> Dict[str, Any]:
    """Check if ML models are available."""
    try:
        # Check if model factory is available
        try:
            from ml.model_factory import model_factory
            available_models = model_factory.get_available_models() if hasattr(model_factory, 'get_available_models') else []
            
            return {
                "status": "healthy",
                "message": f"Model factory available with {len(available_models)} models",
                "available_models": available_models
            }
        except ImportError:
            return {
                "status": "degraded",
                "message": "Model factory not available - using fallback predictions"
            }
        
    except Exception as e:
        logger.error(f"Models check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "message": f"Error checking models: {str(e)}"
        }


def check_external_apis() -> Dict[str, Any]:
    """Check connectivity to external APIs."""
    try:
        # This is a basic check - in production you might want to make actual API calls
        # but be careful about rate limits
        
        apis_status = {
            "football_data": "not_tested",
            "api_football": "not_tested"
        }
        
        # For now, just check if the base URLs are configured
        if settings.football_data.BASE_URL:
            apis_status["football_data"] = "configured"
        
        if settings.api_football.BASE_URL:
            apis_status["api_football"] = "configured"
        
        return {
            "status": "healthy",
            "message": "External APIs configured",
            "apis": apis_status
        }
        
    except Exception as e:
        logger.error(f"External APIs check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "message": f"Error checking external APIs: {str(e)}"
        }


def check_filesystem() -> Dict[str, Any]:
    """Check file system permissions and required directories."""
    try:
        required_dirs = [
            settings.ml.DATA_DIR,
            settings.ml.CACHE_DIR,
            settings.ml.MODEL_DIR
        ]
        
        missing_dirs = []
        permission_errors = []
        
        for dir_path in required_dirs:
            if not os.path.exists(dir_path):
                try:
                    os.makedirs(dir_path, exist_ok=True)
                except Exception as e:
                    missing_dirs.append(f"{dir_path}: {str(e)}")
            
            # Test write permissions
            try:
                test_file = os.path.join(dir_path, ".health_check_test")
                with open(test_file, 'w') as f:
                    f.write("test")
                os.remove(test_file)
            except Exception as e:
                permission_errors.append(f"{dir_path}: {str(e)}")
        
        if missing_dirs or permission_errors:
            return {
                "status": "unhealthy",
                "message": "File system issues detected",
                "missing_directories": missing_dirs,
                "permission_errors": permission_errors
            }
        
        return {
            "status": "healthy",
            "message": "All required directories accessible"
        }
        
    except Exception as e:
        logger.error(f"Filesystem check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "message": f"Error checking filesystem: {str(e)}"
        }


@router.get("/ready")
def readiness_check(db: Session = Depends(get_db)):
    """
    Kubernetes-style readiness check.
    
    Returns 200 if the service is ready to accept traffic.
    """
    try:
        # Check database
        db.execute(text("SELECT 1"))
        
        # Check critical API keys
        if not settings.football_data.API_KEY or not settings.api_football.API_KEY:
            raise HTTPException(status_code=503, detail="API keys not configured")
        
        return {"status": "ready"}
        
    except Exception as e:
        logger.error(f"Readiness check failed: {str(e)}")
        raise HTTPException(status_code=503, detail="Service not ready")


@router.get("/live")
def liveness_check():
    """
    Kubernetes-style liveness check.

    Returns 200 if the service is alive.
    """
    return {"status": "alive", "timestamp": datetime.now().isoformat()}


@router.get("/ml-status")
def ml_status():
    """
    Report ML model loading status. Used to verify ML pipeline health
    without breaking anything — pure diagnostic endpoint.
    """
    info = {
        "numpy_version": None,
        "ml_service_loaded": False,
        "models_loaded": 0,
        "model_names": [],
        "historical_data_loaded": False,
        "elo_loaded": False,
        "dixon_coles_loaded": False,
        "errors": [],
    }

    try:
        import numpy as _np
        info["numpy_version"] = _np.__version__
    except Exception as e:
        info["errors"].append(f"numpy: {e}")

    try:
        from api.endpoints.ml_predictions import ml_service
        if ml_service is not None:
            info["ml_service_loaded"] = True
            info["models_loaded"] = len(getattr(ml_service, "api_models", {}))
            info["model_names"] = list(getattr(ml_service, "api_models", {}).keys())[:20]
            info["historical_data_loaded"] = getattr(ml_service, "api_df", None) is not None
    except Exception as e:
        info["errors"].append(f"ml_service: {e}")

    try:
        from pathlib import Path
        import json as _json
        models_dir = Path(__file__).resolve().parent.parent.parent / "models" / "api_football"
        elo_path = models_dir / "elo_ratings.json"
        dc_path = models_dir / "dixon_coles.json"
        if elo_path.exists():
            with open(elo_path) as f:
                elo = _json.load(f)
            info["elo_loaded"] = True
            # The file is {"ratings": {team: rating}, "match_count": ..., ...}
            ratings = elo.get("ratings", elo) if isinstance(elo, dict) else {}
            info["elo_team_count"] = len(ratings)
        if dc_path.exists():
            with open(dc_path) as f:
                dc = _json.load(f)
            info["dixon_coles_loaded"] = True
            # Dixon-Coles file uses similar structure
            dc_teams = dc.get("teams", dc.get("attack", dc)) if isinstance(dc, dict) else {}
            info["dixon_coles_team_count"] = len(dc_teams) if isinstance(dc_teams, dict) else 0
    except Exception as e:
        info["errors"].append(f"elo/dc: {e}")

    return info


@router.get("/ml-test")
def ml_test(home: str = "Real Madrid", away: str = "Barcelona"):
    """
    Run ML pipeline on a sample match. Pure diagnostic — verifies the
    models can actually produce predictions, not just load.
    """
    result = {
        "request": {"home": home, "away": away},
        "ml_available": False,
        "elo_lookup": {},
        "raw_predictions": {},
        "errors": [],
    }

    try:
        from pathlib import Path
        import json as _json
        models_dir = Path(__file__).resolve().parent.parent.parent / "models" / "api_football"
        with open(models_dir / "elo_ratings.json") as f:
            elo = _json.load(f)
        ratings = elo.get("ratings", {})
        result["elo_lookup"] = {
            "home_rating": ratings.get(home),
            "away_rating": ratings.get(away),
            "default": elo.get("default_rating", 1500),
        }
    except Exception as e:
        result["errors"].append(f"elo lookup: {e}")

    try:
        from api.endpoints.ml_predictions import ml_service
        if ml_service is None or not getattr(ml_service, "api_models", {}):
            result["errors"].append("ml_service has no models")
            return result
        result["ml_available"] = True

        import numpy as _np
        home_rating = result["elo_lookup"].get("home_rating") or 1500
        away_rating = result["elo_lookup"].get("away_rating") or 1500
        elo_diff = home_rating - away_rating

        for name, mdl in list(ml_service.api_models.items())[:6]:
            try:
                n_features = getattr(mdl, "n_features_in_", 20)
                X = _np.zeros((1, n_features))
                X[0, 0] = elo_diff / 100.0
                if hasattr(mdl, "predict_proba"):
                    proba = mdl.predict_proba(X)[0]
                    result["raw_predictions"][name] = [round(float(x), 3) for x in proba]
                else:
                    pred = mdl.predict(X)[0]
                    result["raw_predictions"][name] = round(float(pred), 3)
            except Exception as e:
                result["raw_predictions"][name] = f"error: {str(e)[:80]}"
    except Exception as e:
        result["errors"].append(f"ml test: {e}")

    return result
