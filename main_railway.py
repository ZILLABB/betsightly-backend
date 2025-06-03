"""
Minimal Railway-compatible main application.
"""

import os
import logging
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create minimal FastAPI app
app = FastAPI(
    title="BetSightly API",
    description="Football Predictions API",
    version="1.0.0"
)

# Add CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for Railway
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    """Root endpoint."""
    return {
        "service": "BetSightly API",
        "status": "operational",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
        "environment": os.getenv("ENVIRONMENT", "production")
    }

@app.get("/api/health")
def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "BetSightly API",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
        "environment": os.getenv("ENVIRONMENT", "production")
    }

@app.get("/api/predictions/")
def get_predictions():
    """Basic predictions endpoint."""
    return {
        "status": "success",
        "message": "Railway deployment successful",
        "predictions": [
            {
                "id": 1,
                "home_team": "Arsenal",
                "away_team": "Chelsea",
                "prediction": "Arsenal Win",
                "odds": 2.1,
                "confidence": 0.75
            }
        ],
        "categories": {
            "2_odds": [{"home_team": "Arsenal", "away_team": "Chelsea", "prediction": "Arsenal Win"}],
            "5_odds": [],
            "10_odds": [],
            "rollover": []
        }
    }

@app.get("/api/betting-codes/")
def get_betting_codes():
    """Basic betting codes endpoint."""
    return {
        "status": "success",
        "betting_codes": [],
        "message": "Railway deployment successful"
    }

@app.get("/api/punters/")
def get_punters():
    """Basic punters endpoint."""
    return {
        "status": "success",
        "punters": [],
        "message": "Railway deployment successful"
    }

@app.get("/api/bookmakers/")
def get_bookmakers():
    """Basic bookmakers endpoint."""
    return {
        "status": "success",
        "bookmakers": [],
        "message": "Railway deployment successful"
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
