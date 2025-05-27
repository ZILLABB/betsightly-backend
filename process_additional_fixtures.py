"""
Process Additional Fixtures

This script processes additional fixtures for May 22nd and generates predictions
using the advanced ML models.
"""

import os
import sys
import json
import logging
import uuid
import itertools
from datetime import datetime
import pandas as pd
import numpy as np
import joblib
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Import the ML prediction pipeline
from ml_prediction_pipeline import MLPredictionService, Base, Fixture, Prediction, PredictionCombination, prediction_combination_items

# Create a SQLite database for testing
DATABASE_URL = "sqlite:///real_predictions.db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Define the additional fixtures for May 22nd
ADDITIONAL_FIXTURES = [
    {
        "fixture_id": 3001,
        "date": "2023-05-22T17:00:00",
        "league_name": "Bulgaria - Bulgarian Cup",
        "home_team": "Ludogorets",
        "away_team": "PFC CSKA Sofia",
        "home_form": 2.0,  # Estimated form based on league position
        "away_form": 1.8,
        "home_odds": 2.45,
        "draw_odds": 3.10,
        "away_odds": 2.90
    },
    {
        "fixture_id": 3002,
        "date": "2023-05-22T17:05:00",
        "league_name": "Saudi Arabia - Saudi Pro League",
        "home_team": "Al-Akhdoud Club",
        "away_team": "Al-Raed Club",
        "home_form": 1.7,  # Estimated form based on league position
        "away_form": 1.5,
        "home_odds": 1.72,
        "draw_odds": 4.00,
        "away_odds": 4.50
    },
    {
        "fixture_id": 3003,
        "date": "2023-05-22T17:15:00",
        "league_name": "Saudi Arabia - Saudi Pro League",
        "home_team": "Damac FC",
        "away_team": "AL Fateh SC",
        "home_form": 1.6,  # Estimated form based on league position
        "away_form": 1.9,
        "home_odds": 3.10,
        "draw_odds": 3.70,
        "away_odds": 2.20
    },
    {
        "fixture_id": 3004,
        "date": "2023-05-22T17:45:00",
        "league_name": "Netherlands - Eredivisie",
        "home_team": "Alkmaar",
        "away_team": "SC Heerenveen",
        "home_form": 2.2,  # Estimated form based on league position
        "away_form": 1.6,
        "home_odds": 1.48,
        "draw_odds": 4.75,
        "away_odds": 6.10
    },
    {
        "fixture_id": 3005,
        "date": "2023-05-22T18:00:00",
        "league_name": "Sweden - Allsvenskan",
        "home_team": "Hammarby IF",
        "away_team": "Mjallby AIF",
        "home_form": 1.9,  # Estimated form based on league position
        "away_form": 1.5,
        "home_odds": 1.76,
        "draw_odds": 3.80,
        "away_odds": 4.50
    },
    {
        "fixture_id": 3006,
        "date": "2023-05-22T18:00:00",
        "league_name": "Sweden - Allsvenskan",
        "home_team": "Malmo",
        "away_team": "AIK",
        "home_form": 2.1,  # Estimated form based on league position
        "away_form": 1.8,
        "home_odds": 1.76,
        "draw_odds": 3.80,
        "away_odds": 4.60
    },
    {
        "fixture_id": 3007,
        "date": "2023-05-22T19:00:00",
        "league_name": "Saudi Arabia - Saudi Pro League",
        "home_team": "Al Ahli Saudi FC",
        "away_team": "Al-Ittifaq FC",
        "home_form": 2.0,  # Estimated form based on league position
        "away_form": 1.6,
        "home_odds": 1.44,
        "draw_odds": 5.00,
        "away_odds": 6.50
    },
    {
        "fixture_id": 3008,
        "date": "2023-05-22T19:30:00",
        "league_name": "Germany - Bundesliga",
        "home_team": "Heidenheim",
        "away_team": "SV 07 Elversberg",
        "home_form": 1.9,  # Estimated form based on league position
        "away_form": 1.6,
        "home_odds": 2.30,
        "draw_odds": 3.60,
        "away_odds": 3.20
    },
    {
        "fixture_id": 3009,
        "date": "2023-05-22T19:30:00",
        "league_name": "Switzerland - Super League",
        "home_team": "Grasshopper Club Zurich",
        "away_team": "FC St. Gallen 1879",
        "home_form": 1.7,  # Estimated form based on league position
        "away_form": 1.8,
        "home_odds": 1.90,
        "draw_odds": 3.90,
        "away_odds": 3.60
    },
    {
        "fixture_id": 3010,
        "date": "2023-05-22T20:00:00",
        "league_name": "Netherlands - Eredivisie",
        "home_team": "FC Twente Enschede",
        "away_team": "NEC Nijmegen",
        "home_form": 2.0,  # Estimated form based on league position
        "away_form": 1.7,
        "home_odds": 1.68,
        "draw_odds": 4.10,
        "away_odds": 4.70
    },
    {
        "fixture_id": 3011,
        "date": "2023-05-22T10:00:00",
        "league_name": "Ukraine - U19",
        "home_team": "Obolon Kyiv",
        "away_team": "FC Livyi Bereh Kyiv U19",
        "home_form": 1.8,  # Estimated form based on league position
        "away_form": 1.4,
        "home_odds": 1.63,
        "draw_odds": 3.80,  # Estimated draw odds
        "away_odds": 5.20   # Estimated away odds
    }
]

def process_additional_fixtures():
    """Process the additional fixtures and generate predictions."""
    logger.info("Starting to process additional fixtures")
    
    # Create database session
    db = SessionLocal()
    
    try:
        # Initialize ML prediction service
        ml_prediction_service = MLPredictionService(db)
        
        # Step 1: Process fixtures
        logger.info("Step 1: Processing fixtures")
        processed_fixtures = ml_prediction_service.process_fixtures(ADDITIONAL_FIXTURES)
        logger.info(f"Processed {len(processed_fixtures)} fixtures")
        
        # Step 2: Generate predictions using ML models
        logger.info("Step 2: Generating predictions using ML models")
        all_predictions = ml_prediction_service.generate_predictions(processed_fixtures)
        logger.info(f"Generated {len(all_predictions)} predictions")
        
        # Step 3: Categorize predictions
        logger.info("Step 3: Categorizing predictions")
        categorized_predictions = ml_prediction_service.categorize_predictions(all_predictions)
        
        # Print categorized predictions
        for category, predictions in categorized_predictions.items():
            logger.info(f"Category: {category}, Number of combinations: {len(predictions)}")
            
            if predictions:
                sample_combo = predictions[0]
                logger.info(f"Sample combination - Combined odds: {sample_combo.get('combined_odds')}, Combined confidence: {sample_combo.get('combined_confidence')}")
                logger.info(f"Number of predictions in combination: {len(sample_combo.get('predictions', []))}")
                
                # Save combinations to database
                logger.info(f"Saving {len(predictions)} combinations for category {category}")
                success = ml_prediction_service.save_prediction_combinations(predictions, category)
                
                if success:
                    logger.info(f"Successfully saved combinations for category {category}")
                else:
                    logger.error(f"Failed to save combinations for category {category}")
        
        # Step 4: Print detailed predictions for each fixture
        logger.info("\nDetailed predictions for each fixture:")
        for prediction in all_predictions:
            fixture = prediction.get("fixture", {})
            home_team = fixture.get("home_team")
            away_team = fixture.get("away_team")
            
            logger.info(f"\n{home_team} vs {away_team}:")
            
            for pred in prediction.get("predictions", []):
                pred_type = pred.get("type")
                
                if pred_type == "match_result":
                    result = pred.get("prediction")
                    confidence = pred.get("confidence")
                    odds = pred.get("odds")
                    
                    if result == "home":
                        logger.info(f"  Match Result: {home_team} to win (Confidence: {confidence}%, Odds: {odds})")
                    elif result == "draw":
                        logger.info(f"  Match Result: Draw (Confidence: {confidence}%, Odds: {odds})")
                    elif result == "away":
                        logger.info(f"  Match Result: {away_team} to win (Confidence: {confidence}%, Odds: {odds})")
                
                elif pred_type == "over_under":
                    result = pred.get("prediction")
                    confidence = pred.get("confidence")
                    odds = pred.get("odds")
                    
                    logger.info(f"  Over/Under: {result.capitalize()} 2.5 goals (Confidence: {confidence}%, Odds: {odds})")
                
                elif pred_type == "btts":
                    result = pred.get("prediction")
                    confidence = pred.get("confidence")
                    odds = pred.get("odds")
                    
                    logger.info(f"  Both Teams to Score: {result.capitalize()} (Confidence: {confidence}%, Odds: {odds})")
        
        logger.info("\nAdditional fixtures processing completed successfully")
    
    except Exception as e:
        logger.error(f"Error processing additional fixtures: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
    
    finally:
        # Close database session
        db.close()

if __name__ == "__main__":
    # Process additional fixtures
    process_additional_fixtures()
