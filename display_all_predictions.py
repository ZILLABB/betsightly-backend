"""
Display All Predictions

This script displays all predictions for all fixtures, organized by category.
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

def display_all_predictions():
    """Display all predictions for all fixtures, organized by category."""
    # Create database session
    db = SessionLocal()
    
    try:
        # Import the models
        from ml_prediction_pipeline import Fixture, Prediction, PredictionCombination
        
        # Get all fixtures
        fixtures = db.query(Fixture).all()
        fixture_ids = [f.fixture_id for f in fixtures]
        
        # Define frontend categories
        categories = {
            "2_odds": "SAFE BETS",
            "5_odds": "BALANCED RISK",
            "10_odds": "HIGH REWARD",
            "rollover": "DAILY ROLLOVER"
        }
        
        print("\n" + "="*80)
        print(f"PREDICTIONS FOR ALL FIXTURES")
        print("="*80)
        
        # Print fixtures
        print("\nFIXTURES:")
        for fixture in fixtures:
            print(f"  • {fixture.home_team} vs {fixture.away_team} ({fixture.league_name})")
        
        # Get all predictions for each fixture
        fixture_predictions = {}
        for fixture_id in fixture_ids:
            predictions = db.query(Prediction).filter(Prediction.fixture_id == fixture_id).all()
            fixture_predictions[fixture_id] = predictions
        
        # Get all combinations for each category
        category_combinations = {}
        for category in categories.keys():
            combinations = db.query(PredictionCombination).filter(
                PredictionCombination.category == category
            ).order_by(
                PredictionCombination.combined_confidence.desc()
            ).all()
            
            category_combinations[category] = combinations
        
        # Print categorized predictions
        print("\n" + "="*80)
        print("CATEGORIZED PREDICTIONS")
        print("="*80)
        
        for category, name in categories.items():
            combinations = category_combinations[category]
            
            print(f"\n{name} ({category}):")
            
            if not combinations:
                print("  No predictions in this category")
                continue
            
            # Get the best combination
            best_combo = combinations[0]
            
            print(f"  Combined Odds: {best_combo.combined_odds:.2f}")
            print(f"  Combined Confidence: {best_combo.combined_confidence*100:.0f}%")
            print("  Predictions:")
            
            for pred in best_combo.predictions:
                fixture = db.query(Fixture).filter(Fixture.fixture_id == pred.fixture_id).first()
                if fixture:
                    pred_text = format_prediction(pred, fixture)
                    print(f"    • {fixture.home_team} vs {fixture.away_team}: {pred_text} (Odds: {pred.odds:.2f}, Confidence: {pred.confidence*100:.0f}%)")
        
        # Print individual fixture predictions
        print("\n" + "="*80)
        print("INDIVIDUAL FIXTURE PREDICTIONS")
        print("="*80)
        
        for fixture in fixtures:
            print(f"\n{fixture.home_team} vs {fixture.away_team} ({fixture.league_name}):")
            
            predictions = fixture_predictions.get(fixture.fixture_id, [])
            predictions.sort(key=lambda p: p.confidence, reverse=True)
            
            for pred in predictions:
                pred_text = format_prediction(pred, fixture)
                print(f"  • {pred_text} (Odds: {pred.odds:.2f}, Confidence: {pred.confidence*100:.0f}%)")
        
        # Print best bets
        print("\n" + "="*80)
        print("BEST BETS OVERALL")
        print("="*80)
        
        # Get all predictions
        all_predictions = []
        for preds in fixture_predictions.values():
            all_predictions.extend(preds)
        
        # Sort by confidence
        all_predictions.sort(key=lambda p: p.confidence, reverse=True)
        
        # Print top 10 predictions
        print("\nTop 10 Highest Confidence Predictions:")
        for i, pred in enumerate(all_predictions[:10]):
            fixture = db.query(Fixture).filter(Fixture.fixture_id == pred.fixture_id).first()
            if fixture:
                pred_text = format_prediction(pred, fixture)
                print(f"{i+1}. {fixture.home_team} vs {fixture.away_team}: {pred_text} (Odds: {pred.odds:.2f}, Confidence: {pred.confidence*100:.0f}%)")
    
    except Exception as e:
        logger.error(f"Error displaying all predictions: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
    
    finally:
        # Close database session
        db.close()

if __name__ == "__main__":
    # Display all predictions
    display_all_predictions()
