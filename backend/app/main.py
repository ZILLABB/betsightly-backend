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
    from app.services.prediction_service import PredictionService

    # Get database session
    db = next(get_db())

    # Get prediction service
    prediction_service = PredictionService(db)

    # Get all predictions by date (today)
    today_predictions = prediction_service.get_predictions_by_date(datetime.now())

    # Categorize predictions
    categorized = prediction_service.categorize_predictions(today_predictions)

    # Create combinations
    combinations = {}
    if categorized["2_odds"]:
        combinations["2_odds"] = prediction_service.create_prediction_combinations(
            categorized["2_odds"], 2.0
        )
    if categorized["5_odds"]:
        combinations["5_odds"] = prediction_service.create_prediction_combinations(
            categorized["5_odds"], 5.0
        )
    if categorized["10_odds"]:
        combinations["10_odds"] = prediction_service.create_prediction_combinations(
            categorized["10_odds"], 10.0
        )

    # Return debug info
    return {
        "today_predictions": len(today_predictions),
        "categorized": {
            "2_odds": len(categorized["2_odds"]),
            "5_odds": len(categorized["5_odds"]),
            "10_odds": len(categorized["10_odds"]),
            "rollover": len(categorized["rollover"])
        },
        "combinations": {
            "2_odds": len(combinations.get("2_odds", [])),
            "5_odds": len(combinations.get("5_odds", [])),
            "10_odds": len(combinations.get("10_odds", []))
        },
        "sample_prediction": today_predictions[0].to_dict() if today_predictions else None,
        "endpoints": {
            "all_predictions": "/api/predictions?categorized=true",
            "category_predictions": "/api/predictions/category/{category}",
            "best_predictions_by_category": "/api/predictions/best/{category}",
            "all_best_predictions": "/api/predictions/best"
        }
    }
