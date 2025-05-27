"""
Retrieve Categorized Predictions

This script retrieves the categorized predictions from the database
and displays them in a structured format.
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

def retrieve_categorized_predictions():
    """Retrieve categorized predictions from the database."""
    logger.info("Retrieving categorized predictions from the database")
    
    # Create database session
    db = SessionLocal()
    
    try:
        # Import the models from the real_fixtures_prediction.py file
        sys.path.append(os.getcwd())
        from real_fixtures_prediction import PredictionCombination, Prediction, Fixture
        
        # Get all categories
        categories = ["2_odds", "5_odds", "10_odds", "rollover"]
        
        # Retrieve combinations for each category
        all_categories = {}
        
        for category in categories:
            logger.info(f"\n=== {category.upper()} CATEGORY ===")
            
            # Get combinations for this category
            combinations = db.query(PredictionCombination).filter(
                PredictionCombination.category == category
            ).order_by(
                PredictionCombination.combined_confidence.desc()
            ).all()
            
            logger.info(f"Found {len(combinations)} combinations")
            
            # Process each combination
            category_combinations = []
            
            for i, combo in enumerate(combinations):
                logger.info(f"\nCombination {i+1}:")
                logger.info(f"  Combined Odds: {combo.combined_odds:.2f}")
                logger.info(f"  Combined Confidence: {combo.combined_confidence*100:.2f}%")
                
                if category == "rollover":
                    logger.info(f"  Rollover Day: {combo.rollover_day}")
                
                # Get predictions in this combination
                predictions = combo.predictions
                
                logger.info(f"  Predictions ({len(predictions)}):")
                
                for pred in predictions:
                    # Get fixture details
                    fixture = db.query(Fixture).filter(Fixture.fixture_id == pred.fixture_id).first()
                    
                    if fixture:
                        match_info = f"{fixture.home_team} vs {fixture.away_team}"
                        
                        # Format prediction based on type
                        if pred.prediction_type == "match_result":
                            if pred.match_result_pred == "home":
                                pred_text = f"{fixture.home_team} to win"
                            elif pred.match_result_pred == "draw":
                                pred_text = "Draw"
                            else:
                                pred_text = f"{fixture.away_team} to win"
                        elif pred.prediction_type == "over_under":
                            pred_text = f"{'Over' if pred.over_under_pred == 'over' else 'Under'} 2.5 goals"
                        elif pred.prediction_type == "btts":
                            pred_text = f"Both Teams to Score: {'Yes' if pred.btts_pred == 'yes' else 'No'}"
                        else:
                            pred_text = pred.prediction_type
                        
                        logger.info(f"    - {match_info}: {pred_text} (Odds: {pred.odds:.2f}, Confidence: {pred.confidence*100:.2f}%)")
                
                # Add to category combinations
                category_combinations.append({
                    "id": combo.id,
                    "combined_odds": combo.combined_odds,
                    "combined_confidence": combo.combined_confidence,
                    "rollover_day": combo.rollover_day,
                    "predictions": [p.to_dict() for p in predictions]
                })
            
            # Add to all categories
            all_categories[category] = category_combinations
        
        # Format for frontend
        frontend_format = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "categories": {
                "safe_bets": {
                    "name": "Safe Bets",
                    "description": "Lower odds, higher confidence predictions",
                    "target_odds": 2.0,
                    "predictions": all_categories.get("2_odds", [])
                },
                "balanced_bets": {
                    "name": "Balanced Risk",
                    "description": "Medium odds, balanced risk-reward",
                    "target_odds": 5.0,
                    "predictions": all_categories.get("5_odds", [])
                },
                "high_reward": {
                    "name": "High Reward",
                    "description": "Higher odds, higher potential returns",
                    "target_odds": 10.0,
                    "predictions": all_categories.get("10_odds", [])
                },
                "rollover": {
                    "name": "10-Day Rollover",
                    "description": "Daily predictions for a 10-day rollover strategy",
                    "target_odds": 3.0,
                    "days": format_rollover_days(all_categories.get("rollover", []))
                }
            }
        }
        
        logger.info("\n=== FRONTEND FORMAT ===")
        logger.info(json.dumps(frontend_format, indent=2, default=str))
    
    except Exception as e:
        logger.error(f"Error retrieving categorized predictions: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
    
    finally:
        # Close database session
        db.close()

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
    # Retrieve categorized predictions
    retrieve_categorized_predictions()
