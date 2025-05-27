"""
Optimize Category Selections

This script optimizes the prediction categories to ensure each category contains unique games
with the best possible selections.
"""

import os
import sys
import json
import logging
from datetime import datetime
import itertools
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Create a SQLite database connection
DATABASE_URL = "sqlite:///real_predictions.db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def format_prediction(pred, fixture):
    """Format a prediction into a readable string."""
    if pred.prediction_type == "match_result":
        if pred.match_result_pred == "home":
            return f"{fixture.home_team} to win"
        elif pred.match_result_pred == "draw":
            return "Draw"
        else:
            return f"{fixture.away_team} to win"
    elif pred.prediction_type == "over_under":
        return f"{'Over' if pred.over_under_pred == 'over' else 'Under'} 2.5 goals"
    elif pred.prediction_type == "btts":
        return f"BTTS: {'Yes' if pred.btts_pred == 'yes' else 'No'}"
    else:
        return pred.prediction_type

def get_fixture_key(fixture_id, prediction_type):
    """Generate a unique key for a fixture and prediction type combination."""
    return f"{fixture_id}_{prediction_type}"

def optimize_categories():
    """Optimize the prediction categories to ensure each category contains unique games."""
    # Create database session
    db = SessionLocal()
    
    try:
        # Import the models
        from ml_prediction_pipeline import Fixture, Prediction, PredictionCombination, prediction_combination_items
        
        # Get all fixtures
        fixtures = db.query(Fixture).all()
        fixture_map = {f.fixture_id: f for f in fixtures}
        
        # Get all predictions
        all_predictions = db.query(Prediction).all()
        
        # Sort predictions by confidence (highest first)
        all_predictions.sort(key=lambda p: p.confidence, reverse=True)
        
        # Group predictions by fixture and prediction type
        prediction_groups = {}
        for pred in all_predictions:
            key = get_fixture_key(pred.fixture_id, pred.prediction_type)
            if key not in prediction_groups:
                prediction_groups[key] = []
            prediction_groups[key].append(pred)
        
        # Define target odds for each category
        target_odds = {
            "2_odds": 2.0,
            "5_odds": 5.0,
            "10_odds": 10.0,
            "rollover": 3.0
        }
        
        # Define allowed odds ranges for each category
        odds_ranges = {
            "2_odds": (1.5, 2.5),
            "5_odds": (3.5, 6.5),
            "10_odds": (7.0, 13.0),
            "rollover": (2.5, 3.5)
        }
        
        # Track used fixture keys to avoid duplicates across categories
        used_fixture_keys = set()
        
        # Process categories in order of priority
        category_order = ["rollover", "10_odds", "5_odds", "2_odds"]
        category_combinations = {}
        
        for category in category_order:
            logger.info(f"Optimizing {category} category")
            
            # Get available predictions (excluding already used fixtures)
            available_predictions = []
            for pred in all_predictions:
                key = get_fixture_key(pred.fixture_id, pred.prediction_type)
                if key not in used_fixture_keys:
                    available_predictions.append(pred)
            
            # Sort by confidence (highest first)
            available_predictions.sort(key=lambda p: p.confidence, reverse=True)
            
            # Try combinations of different sizes
            best_combinations = []
            
            # Try combinations of 1-4 predictions
            for size in range(1, min(5, len(available_predictions) + 1)):
                for combo in itertools.combinations(available_predictions, size):
                    # Check if all fixtures in the combination are unique
                    fixture_keys = set()
                    unique_combo = True
                    
                    for pred in combo:
                        key = get_fixture_key(pred.fixture_id, pred.prediction_type)
                        if key in fixture_keys:
                            unique_combo = False
                            break
                        fixture_keys.add(key)
                    
                    if not unique_combo:
                        continue
                    
                    # Calculate combined odds
                    combined_odds = 1.0
                    combined_confidence = 0.0
                    
                    for pred in combo:
                        combined_odds *= pred.odds
                        combined_confidence += pred.confidence
                    
                    # Calculate average confidence
                    avg_confidence = combined_confidence / len(combo) if combo else 0.0
                    
                    # Check if combined odds are within the allowed range
                    min_odds, max_odds = odds_ranges[category]
                    if min_odds <= combined_odds <= max_odds:
                        best_combinations.append({
                            "id": f"combo_{uuid.uuid4()}",
                            "predictions": list(combo),
                            "combined_odds": combined_odds,
                            "combined_confidence": avg_confidence
                        })
            
            # Sort by combined confidence (highest first)
            best_combinations.sort(key=lambda x: x.get("combined_confidence", 0), reverse=True)
            
            # Limit to 5 combinations
            best_combinations = best_combinations[:5]
            
            # Add day number for rollover
            if category == "rollover":
                for i, combo in enumerate(best_combinations):
                    combo["day"] = i + 1
            
            # Mark used fixture keys
            for combo in best_combinations:
                for pred in combo.get("predictions", []):
                    key = get_fixture_key(pred.fixture_id, pred.prediction_type)
                    used_fixture_keys.add(key)
            
            # Store combinations for this category
            category_combinations[category] = best_combinations
            
            # Print combinations for this category
            logger.info(f"Found {len(best_combinations)} combinations for {category}")
            
            if best_combinations:
                sample_combo = best_combinations[0]
                logger.info(f"Sample combination - Combined odds: {sample_combo.get('combined_odds')}, Combined confidence: {sample_combo.get('combined_confidence')}")
                logger.info(f"Number of predictions in combination: {len(sample_combo.get('predictions', []))}")
                
                # Print predictions in the sample combination
                for pred in sample_combo.get("predictions", []):
                    fixture = fixture_map.get(pred.fixture_id)
                    if fixture:
                        pred_text = format_prediction(pred, fixture)
                        logger.info(f"  - {fixture.home_team} vs {fixture.away_team}: {pred_text} (Odds: {pred.odds:.2f}, Confidence: {pred.confidence*100:.0f}%)")
        
        # Save optimized combinations to database
        for category, combinations in category_combinations.items():
            logger.info(f"Saving {len(combinations)} combinations for {category}")
            
            # Delete existing combinations for this category
            db.query(PredictionCombination).filter(
                PredictionCombination.category == category
            ).delete()
            
            # Save new combinations
            for combo in combinations:
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
                for pred in combo.get("predictions", []):
                    combination.predictions.append(pred)
            
            # Commit changes
            db.commit()
            logger.info(f"Successfully saved combinations for {category}")
        
        logger.info("Category optimization completed successfully")
    
    except Exception as e:
        logger.error(f"Error optimizing categories: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        db.rollback()
    
    finally:
        # Close database session
        db.close()

if __name__ == "__main__":
    # Optimize categories
    optimize_categories()
