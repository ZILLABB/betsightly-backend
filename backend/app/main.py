"""
Main application.
"""

from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.api import api_router
from app.database import init_db

# Initialize database
init_db()

# Create FastAPI app
app = FastAPI(
    title="Football Predictions API",
    description="API for football match predictions",
    version="0.1.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
app.include_router(api_router, prefix="/api")

@app.get("/")
def root():
    """Root endpoint."""
    return {
        "message": "Welcome to the Football Predictions API",
        "docs_url": "/docs",
        "redoc_url": "/redoc"
    }

@app.get("/api/health")
def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "message": "API is running",
        "timestamp": str(datetime.now())
    }

@app.get("/api/debug/predictions")
def debug_predictions():
    """Debug endpoint to check predictions data."""
    from app.database import get_db
    from app.services.prediction_service_improved import PredictionService

    # Get database session
    db = next(get_db())

    # Get prediction service
    prediction_service = PredictionService(db)

    # Get all predictions by date (today)
    today_date = datetime.now().strftime("%Y-%m-%d")
    predictions_data = prediction_service.get_predictions_for_date(today_date)

    # Return debug info
    return {
        "status": predictions_data.get("status", "unknown"),
        "date": predictions_data.get("date", today_date),
        "predictions_count": len(predictions_data.get("predictions", [])),
        "categories": {
            category: len(predictions)
            for category, predictions in predictions_data.get("categories", {}).items()
        },
        "endpoints": {
            "all_predictions": "/api/predictions?categorized=true",
            "category_predictions": "/api/predictions/category/{category}",
            "best_predictions_by_category": "/api/predictions/best/{category}",
            "all_best_predictions": "/api/predictions/best"
        }
    }
