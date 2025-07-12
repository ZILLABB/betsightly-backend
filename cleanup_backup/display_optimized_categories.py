"""
Display Optimized Categories

This script displays the optimized prediction categories with unique games.
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

def display_optimized_categories():
    """Display the optimized prediction categories."""
    # Create database session
    db = SessionLocal()
    
    try:
        # Import the models
        from ml_prediction_pipeline import Fixture, Prediction, PredictionCombination
        
        # Define frontend categories
        categories = {
            "2_odds": "SAFE BETS",
            "5_odds": "BALANCED RISK",
            "10_odds": "HIGH REWARD",
            "rollover": "DAILY ROLLOVER"
        }
        
        print("\n" + "="*80)
        print(f"OPTIMIZED PREDICTION CATEGORIES")
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
            
            # Track fixture IDs to check for duplicates
            fixture_ids = set()
            
            for pred in best_combo.predictions:
                fixture = db.query(Fixture).filter(Fixture.fixture_id == pred.fixture_id).first()
                if fixture:
                    pred_text = format_prediction(pred, fixture)
                    print(f"    • {fixture.home_team} vs {fixture.away_team}: {pred_text} (Odds: {pred.odds:.2f}, Confidence: {pred.confidence*100:.0f}%)")
                    
                    # Check for duplicates
                    if pred.fixture_id in fixture_ids:
                        print(f"      WARNING: Duplicate fixture detected!")
                    fixture_ids.add(pred.fixture_id)
            
            # Print all combinations
            print(f"\n  All Combinations ({len(combinations)}):")
            for i, combo in enumerate(combinations):
                print(f"    Combination {i+1}:")
                print(f"      Combined Odds: {combo.combined_odds:.2f}")
                print(f"      Combined Confidence: {combo.combined_confidence*100:.0f}%")
                
                if category == "rollover":
                    print(f"      Rollover Day: {combo.rollover_day}")
                
                print(f"      Predictions:")
                
                for pred in combo.predictions:
                    fixture = db.query(Fixture).filter(Fixture.fixture_id == pred.fixture_id).first()
                    if fixture:
                        pred_text = format_prediction(pred, fixture)
                        print(f"        - {fixture.home_team} vs {fixture.away_team}: {pred_text} (Odds: {pred.odds:.2f}, Confidence: {pred.confidence*100:.0f}%)")
        
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
        
        # Track fixture IDs and prediction types across categories
        fixture_prediction_map = {}
        
        for category, combinations in all_combinations.items():
            if not combinations:
                continue
            
            # Check the best combination
            best_combo = combinations[0]
            
            for pred in best_combo.predictions:
                key = f"{pred.fixture_id}_{pred.prediction_type}"
                
                if key in fixture_prediction_map:
                    existing_category = fixture_prediction_map[key]
                    fixture = db.query(Fixture).filter(Fixture.fixture_id == pred.fixture_id).first()
                    
                    if fixture:
                        pred_text = format_prediction(pred, fixture)
                        print(f"DUPLICATE: {fixture.home_team} vs {fixture.away_team}: {pred_text}")
                        print(f"  - Found in both {existing_category} and {category}")
                else:
                    fixture_prediction_map[key] = category
        
        if not fixture_prediction_map:
            print("No duplicates found across categories!")
        
        # Print summary
        print("\n" + "="*80)
        print("SUMMARY OF OPTIMIZED CATEGORIES")
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
    
    except Exception as e:
        logger.error(f"Error displaying optimized categories: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
    
    finally:
        # Close database session
        db.close()

if __name__ == "__main__":
    # Display optimized categories
    display_optimized_categories()
