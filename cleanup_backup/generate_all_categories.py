"""
Generate All Categories

This script ensures we have predictions in all categories (2 odds, 5 odds, 10 odds, rollover)
by relaxing the odds matching criteria.
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
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Create a SQLite database connection
DATABASE_URL = "sqlite:///real_predictions.db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def generate_all_categories():
    """Generate predictions for all categories."""
    # Create database session
    db = SessionLocal()
    
    try:
        # Import the models
        from ml_prediction_pipeline import Fixture, Prediction, PredictionCombination, prediction_combination_items
        
        # Get fixtures for May 22nd (fixture_id >= 2000)
        fixtures = db.query(Fixture).filter(Fixture.fixture_id >= 2000).all()
        fixture_ids = [f.fixture_id for f in fixtures]
        
        # Get all predictions for these fixtures
        all_predictions = []
        for fixture_id in fixture_ids:
            predictions = db.query(Prediction).filter(Prediction.fixture_id == fixture_id).all()
            
            # Group predictions by fixture
            fixture = db.query(Fixture).filter(Fixture.fixture_id == fixture_id).first()
            
            if fixture:
                fixture_info = {
                    "fixture_id": fixture.fixture_id,
                    "date": fixture.date,
                    "league": fixture.league_name,
                    "home_team": fixture.home_team,
                    "away_team": fixture.away_team
                }
                
                # Convert predictions to dictionary format
                preds = []
                for pred in predictions:
                    pred_dict = {
                        "type": pred.prediction_type,
                        "odds": pred.odds,
                        "confidence": pred.confidence * 100,
                        "fixture": fixture_info
                    }
                    
                    if pred.prediction_type == "match_result":
                        pred_dict["prediction"] = pred.match_result_pred
                        pred_dict["home_win"] = pred.home_win_pred * 100 if pred.home_win_pred else 0
                        pred_dict["draw"] = pred.draw_pred * 100 if pred.draw_pred else 0
                        pred_dict["away_win"] = pred.away_win_pred * 100 if pred.away_win_pred else 0
                    elif pred.prediction_type == "over_under":
                        pred_dict["prediction"] = pred.over_under_pred
                        pred_dict["over_2_5"] = pred.over_2_5_pred * 100 if pred.over_2_5_pred else 0
                        pred_dict["under_2_5"] = pred.under_2_5_pred * 100 if pred.under_2_5_pred else 0
                    elif pred.prediction_type == "btts":
                        pred_dict["prediction"] = pred.btts_pred
                        pred_dict["btts_yes"] = pred.btts_yes_pred * 100 if pred.btts_yes_pred else 0
                        pred_dict["btts_no"] = pred.btts_no_pred * 100 if pred.btts_no_pred else 0
                    
                    preds.append(pred_dict)
                
                all_predictions.append({
                    "fixture": fixture_info,
                    "predictions": preds
                })
        
        # Define categories and target odds
        categories = {
            "2_odds": 2.0,
            "5_odds": 5.0,
            "10_odds": 10.0,
            "rollover": 3.0
        }
        
        # Create combinations for each category with relaxed criteria
        for category, target_odds in categories.items():
            logger.info(f"Generating combinations for {category} (target odds: {target_odds})")
            
            # Extract individual predictions
            individual_predictions = []
            for pred_group in all_predictions:
                fixture = pred_group.get("fixture", {})
                for pred in pred_group.get("predictions", []):
                    # Add fixture info to prediction
                    pred_with_fixture = pred.copy()
                    pred_with_fixture["fixture"] = fixture
                    individual_predictions.append(pred_with_fixture)
            
            # Sort by confidence (highest first)
            sorted_predictions = sorted(
                individual_predictions,
                key=lambda p: p.get("confidence", 0),
                reverse=True
            )
            
            # Try combinations of different sizes
            combinations = []
            
            # Try combinations of 1-4 predictions
            for size in range(1, min(5, len(sorted_predictions) + 1)):
                for combo in itertools.combinations(sorted_predictions, size):
                    # Calculate combined odds
                    combined_odds = 1.0
                    combined_confidence = 0.0
                    
                    for pred in combo:
                        odds = pred.get("odds", 1.0)
                        confidence = pred.get("confidence", 0.0)
                        
                        combined_odds *= odds
                        combined_confidence += confidence
                    
                    # Calculate average confidence
                    avg_confidence = combined_confidence / len(combo) if combo else 0.0
                    
                    # Use relaxed criteria for odds matching
                    # For 2 odds: 1.5-2.5
                    # For 5 odds: 3.5-6.5
                    # For 10 odds: 7.0-13.0
                    # For rollover: 2.5-3.5
                    if category == "2_odds" and 1.5 <= combined_odds <= 2.5:
                        combinations.append({
                            "id": f"combo_{uuid.uuid4()}",
                            "predictions": list(combo),
                            "combined_odds": combined_odds,
                            "combined_confidence": avg_confidence
                        })
                    elif category == "5_odds" and 3.5 <= combined_odds <= 6.5:
                        combinations.append({
                            "id": f"combo_{uuid.uuid4()}",
                            "predictions": list(combo),
                            "combined_odds": combined_odds,
                            "combined_confidence": avg_confidence
                        })
                    elif category == "10_odds" and 7.0 <= combined_odds <= 13.0:
                        combinations.append({
                            "id": f"combo_{uuid.uuid4()}",
                            "predictions": list(combo),
                            "combined_odds": combined_odds,
                            "combined_confidence": avg_confidence
                        })
                    elif category == "rollover" and 2.5 <= combined_odds <= 3.5:
                        combinations.append({
                            "id": f"combo_{uuid.uuid4()}",
                            "predictions": list(combo),
                            "combined_odds": combined_odds,
                            "combined_confidence": avg_confidence
                        })
            
            # Sort by combined confidence (highest first)
            sorted_combinations = sorted(
                combinations,
                key=lambda x: x.get("combined_confidence", 0),
                reverse=True
            )
            
            # Limit to 5 combinations
            best_combinations = sorted_combinations[:5]
            
            # Add day number for rollover
            if category == "rollover":
                for i, combo in enumerate(best_combinations):
                    combo["day"] = i + 1
            
            # Save combinations to database
            if best_combinations:
                logger.info(f"Saving {len(best_combinations)} combinations for {category}")
                
                # Delete existing combinations for this category
                db.query(PredictionCombination).filter(
                    PredictionCombination.category == category
                ).delete()
                
                # Save new combinations
                for combo in best_combinations:
                    # Create combination record
                    combination = PredictionCombination(
                        id=combo.get("id", f"{category}_{uuid.uuid4()}"),
                        category=category,
                        combined_odds=combo.get("combined_odds", 0),
                        combined_confidence=combo.get("combined_confidence", 0),
                        rollover_day=combo.get("day")
                    )
                    
                    # Add to database
                    db.add(combination)
                    db.flush()  # Flush to get the ID
                    
                    # Add predictions to combination
                    for pred_dict in combo.get("predictions", []):
                        # Get fixture info
                        fixture = pred_dict.get("fixture", {})
                        fixture_id = fixture.get("fixture_id")
                        prediction_type = pred_dict.get("type")
                        
                        if fixture_id and prediction_type:
                            # Find prediction in database
                            prediction = db.query(Prediction).filter(
                                Prediction.fixture_id == fixture_id,
                                Prediction.prediction_type == prediction_type
                            ).first()
                            
                            # Add prediction to combination
                            if prediction:
                                combination.predictions.append(prediction)
                
                # Commit changes
                db.commit()
                logger.info(f"Successfully saved combinations for {category}")
            else:
                logger.warning(f"No combinations found for {category}")
        
        logger.info("All categories generated successfully")
    
    except Exception as e:
        logger.error(f"Error generating all categories: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        db.rollback()
    
    finally:
        # Close database session
        db.close()

if __name__ == "__main__":
    # Generate all categories
    generate_all_categories()
