"""
Optimize Highest Confidence Predictions

This script modifies the prediction system to ensure each football match appears exactly once
within each category, displaying only its highest-confidence prediction.
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

def normalize_team_name(name):
    """Normalize team names to handle duplicates like 'Alkmaar' and 'AZ Alkmaar'."""
    name = name.lower().strip()
    # Handle specific known duplicates
    if "alkmaar" in name:
        return "alkmaar"
    if "heerenveen" in name:
        return "heerenveen"
    if "twente" in name:
        return "twente"
    # Return the normalized name
    return name

def optimize_highest_confidence():
    """Optimize predictions to show only the highest confidence prediction for each match."""
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
        
        # Track used teams to avoid duplicates across categories
        used_teams = set()
        
        # Process categories in order of priority
        category_order = ["2_odds", "5_odds", "10_odds", "rollover"]
        category_combinations = {}
        
        for category in category_order:
            logger.info(f"Optimizing {category} category")
            
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
                    min_odds, max_odds = odds_ranges[category]
                    if min_odds <= combined_odds <= max_odds:
                        # For all categories, prioritize high confidence
                        if avg_confidence >= 0.75:  # Only include combinations with at least 75% confidence
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
            
            # Limit to 5 combinations
            best_combinations = best_combinations[:5]
            
            # Add day number for rollover
            if category == "rollover":
                for i, combo in enumerate(best_combinations):
                    combo["day"] = i + 1
            
            # Mark used teams
            for combo in best_combinations:
                for team in combo.get("teams", set()):
                    used_teams.add(team)
            
            # Store combinations for this category
            category_combinations[category] = best_combinations
            
            # Print combinations for this category
            logger.info(f"Found {len(best_combinations)} combinations for {category}")
            
            if best_combinations:
                sample_combo = best_combinations[0]
                logger.info(f"Sample combination - Combined odds: {sample_combo.get('combined_odds')}, Combined confidence: {sample_combo.get('combined_confidence')}")
                logger.info(f"Number of predictions in combination: {len(sample_combo.get('predictions', []))}")
                
                # Print predictions in the sample combination
                for i, (pred, fixture) in enumerate(zip(sample_combo.get("predictions", []), sample_combo.get("fixtures", []))):
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
        
        logger.info("Highest confidence optimization completed successfully")
    
    except Exception as e:
        logger.error(f"Error optimizing highest confidence: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        db.rollback()
    
    finally:
        # Close database session
        db.close()

if __name__ == "__main__":
    # Optimize highest confidence
    optimize_highest_confidence()
