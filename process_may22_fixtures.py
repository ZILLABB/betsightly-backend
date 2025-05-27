"""
Process May 22nd Fixtures

This script processes the fixtures for Thursday, May 22nd and generates predictions
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

# Define the fixtures for May 22nd
MAY22_FIXTURES = [
    {
        "fixture_id": 2001,
        "date": "2023-05-22T20:00:00",
        "league_name": "Scottish Premiership Play-offs",
        "home_team": "Livingston",
        "away_team": "Ross County",
        "home_form": 1.8,  # Estimated form based on league position
        "away_form": 1.5,
        "home_odds": 2.0,  # 1/1 in decimal
        "draw_odds": 3.4,  # 12/5 in decimal
        "away_odds": 3.6   # 13/5 in decimal
    },
    {
        "fixture_id": 2002,
        "date": "2023-05-22T17:45:00",
        "league_name": "Dutch Eredivisie Europa League Play-offs",
        "home_team": "AZ Alkmaar",
        "away_team": "Heerenveen",
        "home_form": 2.2,  # Estimated form based on league position
        "away_form": 1.6,
        "home_odds": 1.44,  # 4/9 in decimal
        "draw_odds": 4.6,   # 18/5 in decimal
        "away_odds": 5.75   # 19/4 in decimal
    },
    {
        "fixture_id": 2003,
        "date": "2023-05-22T20:00:00",
        "league_name": "Dutch Eredivisie Europa League Play-offs",
        "home_team": "FC Twente",
        "away_team": "NEC Nijmegen",
        "home_form": 2.0,  # Estimated form based on league position
        "away_form": 1.7,
        "home_odds": 1.62,  # 8/13 in decimal
        "draw_odds": 4.0,   # 3/1 in decimal
        "away_odds": 4.5    # 7/2 in decimal
    },
    {
        "fixture_id": 2004,
        "date": "2023-05-22T19:30:00",
        "league_name": "German Bundesliga Relegation Playoffs",
        "home_team": "1. FC Heidenheim 1846",
        "away_team": "SV 07 Elversberg",
        "home_form": 1.9,  # Estimated form based on league position
        "away_form": 1.6,
        "home_odds": 2.2,   # 6/5 in decimal
        "draw_odds": 3.5,   # 5/2 in decimal
        "away_odds": 3.0    # 2/1 in decimal
    },
    {
        "fixture_id": 2005,
        "date": "2023-05-22T16:00:00",
        "league_name": "Greek Super League",
        "home_team": "Levadiakos",
        "away_team": "Volos NFC",
        "home_form": 1.6,  # Estimated form based on league position
        "away_form": 1.4,
        "home_odds": 1.6,   # 3/5 in decimal
        "draw_odds": 3.6,   # 13/5 in decimal
        "away_odds": 4.5    # 7/2 in decimal
    },
    {
        "fixture_id": 2006,
        "date": "2023-05-22T16:00:00",
        "league_name": "Greek Super League",
        "home_team": "Panetolikos",
        "away_team": "Panserraikos",
        "home_form": 1.7,  # Estimated form based on league position
        "away_form": 1.3,
        "home_odds": 1.55,  # 11/20 in decimal
        "draw_odds": 3.6,   # 13/5 in decimal
        "away_odds": 5.0    # 4/1 in decimal
    },
    {
        "fixture_id": 2007,
        "date": "2023-05-22T18:00:00",
        "league_name": "Greek Super League",
        "home_team": "Athens Kallithea",
        "away_team": "Lamia",
        "home_form": 1.8,  # Estimated form based on league position
        "away_form": 1.4,
        "home_odds": 1.44,  # 4/9 in decimal
        "draw_odds": 4.0,   # 3/1 in decimal
        "away_odds": 5.5    # 9/2 in decimal
    },
    {
        "fixture_id": 2008,
        "date": "2023-05-22T18:00:00",
        "league_name": "Swedish Allsvenskan",
        "home_team": "Hammarby IF",
        "away_team": "Mjällby AIF",
        "home_form": 1.9,  # Estimated form based on league position
        "away_form": 1.5,
        "home_odds": 1.67,  # 4/6 in decimal
        "draw_odds": 3.75,  # 11/4 in decimal
        "away_odds": 4.5    # 7/2 in decimal
    },
    {
        "fixture_id": 2009,
        "date": "2023-05-22T18:00:00",
        "league_name": "Swedish Allsvenskan",
        "home_team": "Malmo FF",
        "away_team": "AIK",
        "home_form": 2.1,  # Estimated form based on league position
        "away_form": 1.8,
        "home_odds": 1.7,   # 7/10 in decimal
        "draw_odds": 3.6,   # 13/5 in decimal
        "away_odds": 4.5    # Not provided, estimated
    }
]

def process_may22_fixtures():
    """Process the May 22nd fixtures and generate predictions."""
    logger.info("Starting to process May 22nd fixtures")
    
    # Create database session
    db = SessionLocal()
    
    try:
        # Initialize ML prediction service
        ml_prediction_service = MLPredictionService(db)
        
        # Step 1: Process fixtures
        logger.info("Step 1: Processing fixtures")
        processed_fixtures = ml_prediction_service.process_fixtures(MAY22_FIXTURES)
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
        
        logger.info("\nMay 22nd fixtures processing completed successfully")
    
    except Exception as e:
        logger.error(f"Error processing May 22nd fixtures: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
    
    finally:
        # Close database session
        db.close()

if __name__ == "__main__":
    # Process May 22nd fixtures
    process_may22_fixtures()
