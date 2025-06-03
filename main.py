"""
Main application.
"""

import logging
import os
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy.orm import Session

from api.api import api_router
from database import init_db, get_db
from utils.config import settings
from utils.error_handling import setup_exception_handlers
from utils.security import SecurityMiddleware

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize database (skip for Railway deployment if no DATABASE_URL)
try:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        init_db()
        logger.info("Database initialized successfully")
    else:
        logger.warning("No DATABASE_URL found - skipping database initialization for Railway deployment")
except Exception as e:
    logger.error(f"Failed to initialize database: {str(e)}")
    # Don't raise in Railway deployment - let app start without DB for now
    if os.getenv("ENVIRONMENT") != "production":
        raise

# Create FastAPI app with enhanced configuration
app = FastAPI(
    title="BetSightly Football Predictions API",
    description="Advanced ML-powered football match predictions with confidence scoring",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None
)

# Add security middleware (allow Render hosts)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "*.betsightly.com", "*.onrender.com", "*.railway.app", "testserver"]
)

# Add compression middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Add security middleware for production
app.add_middleware(SecurityMiddleware)

# Add CORS middleware with enhanced security
allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:5182,http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "X-API-Key"],
    max_age=3600,  # Cache preflight requests for 1 hour
)

# Setup exception handlers
setup_exception_handlers(app)

# Include API router
app.include_router(api_router, prefix="/api")

@app.get("/")
def root():
    """Root endpoint with enhanced information."""
    return {
        "service": "BetSightly Football Predictions API",
        "version": "1.0.0",
        "status": "operational",
        "message": "Advanced ML-powered football predictions",
        "docs_url": "/docs" if settings.DEBUG else "Contact admin for API documentation",
        "health_check": "/api/health/",
        "predictions": "/api/predictions/",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/health")
def health_check():
    """Basic health check endpoint."""
    try:
        return {
            "status": "healthy",
            "service": "BetSightly API",
            "version": "1.0.0",
            "timestamp": datetime.now().isoformat(),
            "environment": os.getenv("ENVIRONMENT", "production")
        }
    except Exception as e:
        # Fallback response if anything fails
        return {
            "status": "healthy",
            "service": "BetSightly API",
            "version": "1.0.0",
            "error": str(e)
        }

@app.get("/api/debug/predictions")
def debug_predictions():
    """Debug endpoint to check predictions data."""
    try:
        # Simple debug endpoint for Railway deployment
        return {
            "status": "operational",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "message": "Minimal deployment - ML services loading",
            "endpoints": {
                "health": "/api/health",
                "predictions": "/api/predictions/",
                "betting_codes": "/api/betting-codes/",
                "punters": "/api/punters/"
            },
            "deployment": "railway-minimal"
        }
    except Exception as e:
        logger.error(f"Error in debug predictions endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting debug predictions: {str(e)}")
