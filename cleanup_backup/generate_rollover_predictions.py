"""
Generate Rollover Predictions

This script generates rollover predictions for May 23rd.
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

# Import models from ml_prediction_pipeline
sys.path.append(os.getcwd())
try:
    from ml_prediction_pipeline import Fixture, Prediction, PredictionCombination, prediction_combination_items
except ImportError:
    logger.error("Could not import models from ml_prediction_pipeline. Make sure the file exists and is accessible.")
    sys.exit(1)

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

def normalize_team_name(name):
    """Normalize team names to handle duplicates."""
    name = name.lower().strip()
    return name

def generate_rollover_predictions():
    """Generate rollover predictions for May 23rd."""
    # Create database session
    db = SessionLocal()
    
    try:
        # Get all fixtures for May 23rd
        may_23_fixtures = db.query(Fixture).filter(
            Fixture.date >= datetime(2023, 5, 23, 0, 0, 0),
            Fixture.date < datetime(2023, 5, 24, 0, 0, 0)
        ).all()
        
        fixture_map = {f.fixture_id: f for f in may_23_fixtures}
        logger.info(f"Found {len(fixture_map)} fixtures for May 23rd")
        
        # Get all predictions for May 23rd fixtures
        all_predictions = []
        for fixture_id in fixture_map.keys():
            predictions = db.query(Prediction).filter(Prediction.fixture_id == fixture_id).all()
            all_predictions.extend(predictions)
        
        logger.info(f"Found {len(all_predictions)} predictions for May 23rd fixtures")
        
        # Group predictions by fixture
        predictions_by_fixture = {}
        for pred in all_predictions:
            if pred.fixture_id not in predictions_by_fixture:
                predictions_by_fixture[pred.fixture_id] = []
            predictions_by_fixture[pred.fixture_id].append(pred)
        
        # For each fixture, find the highest confidence prediction
        best_predictions_by_fixture = {}
        for fixture_id, predictions in predictions_by_fixture.items():
            # Sort by confidence (highest first)
            sorted_predictions = sorted(predictions, key=lambda p: p.confidence, reverse=True)
            # Take the highest confidence prediction
            best_predictions_by_fixture[fixture_id] = sorted_predictions[0]
        
        logger.info(f"Identified {len(best_predictions_by_fixture)} highest confidence predictions")
        
        # Get teams already used in other categories
        used_teams = set()
        for category in ["2_odds", "5_odds", "10_odds"]:
            combinations = db.query(PredictionCombination).filter(
                PredictionCombination.category == category
            ).all()
            
            for combo in combinations:
                for pred in combo.predictions:
                    fixture = fixture_map.get(pred.fixture_id)
                    if fixture:
                        used_teams.add(normalize_team_name(fixture.home_team))
                        used_teams.add(normalize_team_name(fixture.away_team))
        
        logger.info(f"Found {len(used_teams)} teams already used in other categories")
        
        # Get available predictions (excluding already used teams)
        available_predictions = []
        for fixture_id, pred in best_predictions_by_fixture.items():
            fixture = fixture_map.get(fixture_id)
            if not fixture:
                continue
            
            # Normalize team names
            home_team = normalize_team_name(fixture.home_team)
            away_team = normalize_team_name(fixture.away_team)
            
            # Skip if either team has been used
            if home_team in used_teams or away_team in used_teams:
                continue
            
            available_predictions.append((pred, fixture))
        
        # Sort by confidence (highest first)
        available_predictions.sort(key=lambda x: x[0].confidence, reverse=True)
        
        logger.info(f"Found {len(available_predictions)} available predictions for rollover")
        
        # Define target odds for rollover
        target_odds = 3.0
        min_odds = 2.5
        max_odds = 3.5
        
        # Try combinations of different sizes
        best_combinations = []
        
        # Try combinations of 1-4 predictions
        for size in range(1, min(5, len(available_predictions) + 1)):
            for combo in itertools.combinations(available_predictions, size):
                # Check if all fixtures in the combination are unique
                teams_in_combo = set()
                unique_combo = True
                
                for pred, fixture in combo:
                    home_team = normalize_team_name(fixture.home_team)
                    away_team = normalize_team_name(fixture.away_team)
                    
                    if home_team in teams_in_combo or away_team in teams_in_combo:
                        unique_combo = False
                        break
                    
                    teams_in_combo.add(home_team)
                    teams_in_combo.add(away_team)
                
                if not unique_combo:
                    continue
                
                # Calculate combined odds
                combined_odds = 1.0
                combined_confidence = 0.0
                
                for pred, _ in combo:
                    combined_odds *= pred.odds
                    combined_confidence += pred.confidence
                
                # Calculate average confidence
                avg_confidence = combined_confidence / len(combo) if combo else 0.0
                
                # Check if combined odds are within the allowed range
                if min_odds <= combined_odds <= max_odds:
                    # For rollover, prioritize high confidence
                    if avg_confidence >= 0.65:  # Only include combinations with at least 65% confidence
                        best_combinations.append({
                            "id": f"combo_{uuid.uuid4()}",
                            "predictions": [pred for pred, _ in combo],
                            "fixtures": [fixture for _, fixture in combo],
                            "combined_odds": combined_odds,
                            "combined_confidence": avg_confidence,
                            "teams": teams_in_combo
                        })
        
        # Sort by combined confidence (highest first)
        best_combinations.sort(key=lambda x: x.get("combined_confidence", 0), reverse=True)
        
        # Limit to 10 combinations (for 10-day rollover)
        best_combinations = best_combinations[:10]
        
        # Add day number for rollover
        for i, combo in enumerate(best_combinations):
            combo["day"] = i + 1
        
        logger.info(f"Generated {len(best_combinations)} rollover combinations")
        
        # Print rollover combinations
        for i, combo in enumerate(best_combinations):
            logger.info(f"Rollover Day {combo.get('day')}: Combined Odds: {combo.get('combined_odds')}, Combined Confidence: {combo.get('combined_confidence')}")
            logger.info(f"Number of predictions: {len(combo.get('predictions', []))}")
            
            for j, (pred, fixture) in enumerate(zip(combo.get("predictions", []), combo.get("fixtures", []))):
                pred_text = format_prediction(pred, fixture)
                logger.info(f"  - {fixture.home_team} vs {fixture.away_team}: {pred_text} (Odds: {pred.odds:.2f}, Confidence: {pred.confidence*100:.0f}%)")
        
        # Save rollover combinations to database
        logger.info(f"Saving {len(best_combinations)} combinations for rollover")
        
        # Delete existing combinations for rollover
        db.query(PredictionCombination).filter(
            PredictionCombination.category == "rollover"
        ).delete()
        
        # Save new combinations
        for combo in best_combinations:
            # Create combination record
            combination = PredictionCombination(
                id=combo.get("id", f"rollover_{uuid.uuid4()}"),
                category="rollover",
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
        logger.info(f"Successfully saved combinations for rollover")
        
        logger.info("Rollover predictions generated successfully")
    
    except Exception as e:
        logger.error(f"Error generating rollover predictions: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        db.rollback()
    
    finally:
        # Close database session
        db.close()

if __name__ == "__main__":
    # Generate rollover predictions
    generate_rollover_predictions()
