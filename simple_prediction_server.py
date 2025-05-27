"""
Simple Prediction Server

This script creates a simple FastAPI server that serves the prediction endpoints
using the data from our real_predictions.db database.
"""

import os
import sys
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import json

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="BetSightly Predictions API",
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

# Database connection
def get_db_connection():
    """Get a database connection."""
    conn = sqlite3.connect("real_predictions.db")
    conn.row_factory = sqlite3.Row
    return conn

@app.get("/")
def root():
    """Root endpoint."""
    return {
        "message": "Welcome to the BetSightly Predictions API",
        "endpoints": {
            "all_categories": "/api/predictions/categories",
            "category_predictions": "/api/predictions/category/{category}",
            "best_predictions": "/api/predictions/best",
            "best_category_predictions": "/api/predictions/best/{category}"
        }
    }

@app.get("/api/health")
def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "message": "API is running",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

@app.get("/api/predictions")
def get_predictions(categorized: bool = False):
    """
    Compatibility endpoint for the old API structure.

    If categorized=true, returns the same as /api/predictions/categories.
    """
    if categorized:
        return get_all_prediction_categories()
    else:
        # Return a simple list of all predictions
        try:
            conn = get_db_connection()

            # Get all predictions
            cursor = conn.execute(
                """
                SELECT p.*, f.home_team, f.away_team, f.league_name, f.date
                FROM predictions p
                JOIN fixtures f ON p.fixture_id = f.fixture_id
                ORDER BY p.confidence DESC
                LIMIT 100
                """
            )

            predictions = []
            for row in cursor.fetchall():
                prediction = dict(row)
                predictions.append(prediction)

            conn.close()

            return {
                "status": "success",
                "predictions": predictions
            }

        except Exception as e:
            logger.error(f"Error getting predictions: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error getting predictions: {str(e)}")

@app.get("/api/predictions/categories")
def get_all_prediction_categories():
    """
    Get all prediction categories for a specific date.

    Returns a structured response with all categories and their predictions,
    optimized for frontend rendering.
    """
    try:
        conn = get_db_connection()

        # Get all prediction combinations
        combinations_by_category = {}

        for category in ["2_odds", "5_odds", "10_odds", "rollover"]:
            # Get combinations for this category
            cursor = conn.execute(
                """
                SELECT id, category, combined_odds, combined_confidence, rollover_day
                FROM prediction_combinations
                WHERE category = ?
                ORDER BY combined_confidence DESC
                LIMIT 5
                """,
                (category,)
            )

            combinations = []
            for row in cursor.fetchall():
                combo = dict(row)

                # Get predictions for this combination
                predictions_cursor = conn.execute(
                    """
                    SELECT p.*
                    FROM predictions p
                    JOIN prediction_combination_items pci ON p.id = pci.prediction_id
                    WHERE pci.combination_id = ?
                    """,
                    (combo["id"],)
                )

                predictions = []
                for pred_row in predictions_cursor.fetchall():
                    prediction = dict(pred_row)

                    # Get fixture details
                    fixture_cursor = conn.execute(
                        """
                        SELECT *
                        FROM fixtures
                        WHERE fixture_id = ?
                        """,
                        (prediction["fixture_id"],)
                    )

                    fixture = dict(fixture_cursor.fetchone() or {})
                    prediction["fixture"] = fixture

                    predictions.append(prediction)

                combo["predictions"] = predictions
                combinations.append(combo)

            combinations_by_category[category] = combinations

        conn.close()

        # Format response for frontend
        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "categories": {
                "safe_bets": {
                    "name": "Safe Bets",
                    "description": "Lower odds, higher confidence predictions",
                    "target_odds": 2.0,
                    "predictions": combinations_by_category.get("2_odds", [])
                },
                "balanced_bets": {
                    "name": "Balanced Risk",
                    "description": "Medium odds, balanced risk-reward",
                    "target_odds": 5.0,
                    "predictions": combinations_by_category.get("5_odds", [])
                },
                "high_reward": {
                    "name": "High Reward",
                    "description": "Higher odds, higher potential returns",
                    "target_odds": 10.0,
                    "predictions": combinations_by_category.get("10_odds", [])
                },
                "rollover": {
                    "name": "10-Day Rollover",
                    "description": "Daily predictions for a 10-day rollover strategy",
                    "target_odds": 3.0,
                    "days": format_rollover_days(combinations_by_category.get("rollover", []))
                }
            }
        }

    except Exception as e:
        logger.error(f"Error getting prediction categories: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting prediction categories: {str(e)}")

@app.get("/api/predictions/category/{category}")
def get_predictions_by_category(category: str):
    """
    Get predictions by category.

    Args:
        category: Category to get predictions for (2_odds, 5_odds, 10_odds, rollover)
    """
    try:
        # Validate category
        valid_categories = ["2_odds", "5_odds", "10_odds", "rollover"]
        if category not in valid_categories:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid category. Must be one of: {', '.join(valid_categories)}"
            )

        conn = get_db_connection()

        # Get combinations for this category
        cursor = conn.execute(
            """
            SELECT id, category, combined_odds, combined_confidence, rollover_day
            FROM prediction_combinations
            WHERE category = ?
            ORDER BY combined_confidence DESC
            LIMIT 5
            """,
            (category,)
        )

        combinations = []
        for row in cursor.fetchall():
            combo = dict(row)

            # Get predictions for this combination
            predictions_cursor = conn.execute(
                """
                SELECT p.*
                FROM predictions p
                JOIN prediction_combination_items pci ON p.id = pci.prediction_id
                WHERE pci.combination_id = ?
                """,
                (combo["id"],)
            )

            predictions = []
            for pred_row in predictions_cursor.fetchall():
                prediction = dict(pred_row)

                # Get fixture details
                fixture_cursor = conn.execute(
                    """
                    SELECT *
                    FROM fixtures
                    WHERE fixture_id = ?
                    """,
                    (prediction["fixture_id"],)
                )

                fixture = dict(fixture_cursor.fetchone() or {})
                prediction["fixture"] = fixture

                predictions.append(prediction)

            combo["predictions"] = predictions
            combinations.append(combo)

        conn.close()

        return combinations

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting predictions for category {category}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting predictions: {str(e)}")

@app.get("/api/predictions/best")
def get_all_best_predictions():
    """
    Get the best predictions for all categories.
    """
    try:
        conn = get_db_connection()

        # Get best combinations for each category
        result = {}

        for category in ["2_odds", "5_odds", "10_odds", "rollover"]:
            # Get best combination for this category
            cursor = conn.execute(
                """
                SELECT id, category, combined_odds, combined_confidence, rollover_day
                FROM prediction_combinations
                WHERE category = ?
                ORDER BY combined_confidence DESC
                LIMIT 1
                """,
                (category,)
            )

            row = cursor.fetchone()
            if row:
                combo = dict(row)

                # Get predictions for this combination
                predictions_cursor = conn.execute(
                    """
                    SELECT p.*
                    FROM predictions p
                    JOIN prediction_combination_items pci ON p.id = pci.prediction_id
                    WHERE pci.combination_id = ?
                    """,
                    (combo["id"],)
                )

                predictions = []
                for pred_row in predictions_cursor.fetchall():
                    prediction = dict(pred_row)

                    # Get fixture details
                    fixture_cursor = conn.execute(
                        """
                        SELECT *
                        FROM fixtures
                        WHERE fixture_id = ?
                        """,
                        (prediction["fixture_id"],)
                    )

                    fixture = dict(fixture_cursor.fetchone() or {})
                    prediction["fixture"] = fixture

                    predictions.append(prediction)

                combo["predictions"] = predictions
                result[category] = [combo]

        conn.close()

        return result

    except Exception as e:
        logger.error(f"Error getting best predictions: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting best predictions: {str(e)}")

@app.get("/api/predictions/best/{category}")
def get_best_predictions_by_category(category: str):
    """
    Get the best predictions for a specific category.

    Args:
        category: Category to get predictions for (2_odds, 5_odds, 10_odds, rollover)
    """
    try:
        # Validate category
        valid_categories = ["2_odds", "5_odds", "10_odds", "rollover"]

        # Handle the case where category might have double underscores
        if category == "2__odds":
            category = "2_odds"
        elif category == "5__odds":
            category = "5_odds"
        elif category == "10__odds":
            category = "10_odds"

        if category not in valid_categories:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid category. Must be one of: {', '.join(valid_categories)}"
            )

        conn = get_db_connection()

        # Get best combination for this category
        cursor = conn.execute(
            """
            SELECT id, category, combined_odds, combined_confidence, rollover_day
            FROM prediction_combinations
            WHERE category = ?
            ORDER BY combined_confidence DESC
            LIMIT 1
            """,
            (category,)
        )

        row = cursor.fetchone()
        if not row:
            return {"predictions": []}

        combo = dict(row)

        # Get predictions for this combination
        predictions_cursor = conn.execute(
            """
            SELECT p.*
            FROM predictions p
            JOIN prediction_combination_items pci ON p.id = pci.prediction_id
            WHERE pci.combination_id = ?
            """,
            (combo["id"],)
        )

        predictions = []
        for pred_row in predictions_cursor.fetchall():
            prediction = dict(pred_row)

            # Get fixture details
            fixture_cursor = conn.execute(
                """
                SELECT *
                FROM fixtures
                WHERE fixture_id = ?
                """,
                (prediction["fixture_id"],)
            )

            fixture = dict(fixture_cursor.fetchone() or {})
            prediction["fixture"] = fixture

            predictions.append(prediction)

        combo["predictions"] = predictions

        conn.close()

        return combo

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting best predictions for category {category}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting best predictions: {str(e)}")

def format_rollover_days(rollover_combinations):
    """Format rollover combinations by day."""
    # Group by day
    days_dict = {}

    for combo in rollover_combinations:
        day = combo.get("rollover_day", 1)
        if day not in days_dict:
            days_dict[day] = []
        days_dict[day].append(combo)

    # Format days
    days = []

    for day_num in range(1, 11):  # 10 days
        if day_num in days_dict:
            # Use the best combination for this day
            best_combo = days_dict[day_num][0]
            days.append({
                "day": day_num,
                "predictions": best_combo.get("predictions", []),
                "combined_odds": best_combo.get("combined_odds", 3.0),
                "combined_confidence": best_combo.get("combined_confidence", 0)
            })
        else:
            # Empty day
            days.append({
                "day": day_num,
                "predictions": [],
                "combined_odds": 0,
                "combined_confidence": 0
            })

    return days

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
