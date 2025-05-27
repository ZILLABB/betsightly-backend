"""
Display May 23rd Predictions

This script displays the predictions for May 23rd in a readable format.
"""

import os
import sys
import json
import logging
from datetime import datetime
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
    from ml_prediction_pipeline import Fixture, Prediction, PredictionCombination
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

def display_may23_predictions():
    """Display the predictions for May 23rd."""
    # Create database session
    db = SessionLocal()
    
    try:
        # Define frontend categories
        categories = {
            "2_odds": "SAFE BETS",
            "5_odds": "BALANCED RISK",
            "10_odds": "HIGH REWARD",
            "rollover": "DAILY ROLLOVER"
        }
        
        print("\n" + "="*80)
        print(f"MAY 23RD PREDICTIONS")
        print("="*80)
        
        # Get all combinations for each category
        for category, name in categories.items():
            # Get combinations for this category
            combinations = db.query(PredictionCombination).filter(
                PredictionCombination.category == category
            ).order_by(
                PredictionCombination.combined_confidence.desc()
            ).all()
            
            print(f"\n{name} ({category}):")
            
            if not combinations:
                print("  No predictions in this category")
                continue
            
            # Get the best combination
            best_combo = combinations[0]
            
            print(f"  Combined Odds: {best_combo.combined_odds:.2f}")
            print(f"  Combined Confidence: {best_combo.combined_confidence*100:.0f}%")
            print("  Predictions:")
            
            # Track fixtures to check for duplicates
            fixtures = set()
            
            for pred in best_combo.predictions:
                fixture = db.query(Fixture).filter(Fixture.fixture_id == pred.fixture_id).first()
                if fixture:
                    pred_text = format_prediction(pred, fixture)
                    print(f"    • {fixture.home_team} vs {fixture.away_team}: {pred_text} (Odds: {pred.odds:.2f}, Confidence: {pred.confidence*100:.0f}%)")
                    
                    # Check for duplicates
                    if pred.fixture_id in fixtures:
                        print(f"      WARNING: Duplicate fixture detected!")
                    fixtures.add(pred.fixture_id)
        
        # Print rollover details
        rollover_combinations = db.query(PredictionCombination).filter(
            PredictionCombination.category == "rollover"
        ).order_by(
            PredictionCombination.rollover_day
        ).all()
        
        if rollover_combinations:
            print("\n" + "="*80)
            print(f"DAILY ROLLOVER DETAILS")
            print("="*80)
            
            for combo in rollover_combinations:
                print(f"\nDay {combo.rollover_day}:")
                print(f"  Combined Odds: {combo.combined_odds:.2f}")
                print(f"  Combined Confidence: {combo.combined_confidence*100:.0f}%")
                print("  Predictions:")
                
                for pred in combo.predictions:
                    fixture = db.query(Fixture).filter(Fixture.fixture_id == pred.fixture_id).first()
                    if fixture:
                        pred_text = format_prediction(pred, fixture)
                        print(f"    • {fixture.home_team} vs {fixture.away_team}: {pred_text} (Odds: {pred.odds:.2f}, Confidence: {pred.confidence*100:.0f}%)")
        
        # Check for duplicates across categories
        print("\n" + "="*80)
        print("CHECKING FOR DUPLICATES ACROSS CATEGORIES")
        print("="*80)
        
        # Get all combinations
        all_combinations = {}
        for category in categories.keys():
            combinations = db.query(PredictionCombination).filter(
                PredictionCombination.category == category
            ).order_by(
                PredictionCombination.combined_confidence.desc()
            ).all()
            
            all_combinations[category] = combinations
        
        # Track teams across categories
        teams_by_category = {}
        
        for category, combinations in all_combinations.items():
            if not combinations:
                continue
            
            # Check the best combination
            best_combo = combinations[0]
            teams_in_category = set()
            
            for pred in best_combo.predictions:
                fixture = db.query(Fixture).filter(Fixture.fixture_id == pred.fixture_id).first()
                if fixture:
                    home_team = normalize_team_name(fixture.home_team)
                    away_team = normalize_team_name(fixture.away_team)
                    teams_in_category.add(home_team)
                    teams_in_category.add(away_team)
            
            teams_by_category[category] = teams_in_category
        
        # Check for duplicates
        duplicate_found = False
        for category1, teams1 in teams_by_category.items():
            for category2, teams2 in teams_by_category.items():
                if category1 != category2:
                    common_teams = teams1.intersection(teams2)
                    if common_teams:
                        duplicate_found = True
                        print(f"Duplicate teams found between {category1} and {category2}:")
                        for team in common_teams:
                            print(f"  - {team}")
        
        if not duplicate_found:
            print("No duplicate teams found across categories!")
        
        # Print summary
        print("\n" + "="*80)
        print("SUMMARY OF MAY 23RD PREDICTIONS")
        print("="*80)
        
        for category, name in categories.items():
            combinations = all_combinations[category]
            
            if not combinations:
                print(f"{name}: No predictions")
                continue
            
            best_combo = combinations[0]
            print(f"{name}:")
            print(f"  Combined Odds: {best_combo.combined_odds:.2f}")
            print(f"  Combined Confidence: {best_combo.combined_confidence*100:.0f}%")
            print(f"  Number of Predictions: {len(best_combo.predictions)}")
            
            # List the fixtures
            fixtures_list = []
            for pred in best_combo.predictions:
                fixture = db.query(Fixture).filter(Fixture.fixture_id == pred.fixture_id).first()
                if fixture:
                    pred_text = format_prediction(pred, fixture)
                    fixtures_list.append(f"{fixture.home_team} vs {fixture.away_team}: {pred_text}")
            
            print(f"  Fixtures: {', '.join(fixtures_list)}")
        
        # Print API endpoints
        print("\n" + "="*80)
        print("API ENDPOINTS FOR ACCESSING PREDICTIONS")
        print("="*80)
        
        print("\nAll Categories Endpoint:")
        print("  GET http://localhost:8000/api/predictions/categories")
        
        print("\nSpecific Category Endpoints:")
        for category in categories.keys():
            print(f"  GET http://localhost:8000/api/predictions/category/{category}")
        
        print("\nBest Predictions Endpoint:")
        print("  GET http://localhost:8000/api/predictions/best")
        
        print("\nBest Category Prediction Endpoints:")
        for category in categories.keys():
            print(f"  GET http://localhost:8000/api/predictions/best/{category}")
    
    except Exception as e:
        logger.error(f"Error displaying May 23rd predictions: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
    
    finally:
        # Close database session
        db.close()

if __name__ == "__main__":
    # Display May 23rd predictions
    display_may23_predictions()
