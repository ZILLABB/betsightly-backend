"""
Display Predictions in Frontend Categories

This script retrieves and displays the predictions in the categories that the frontend uses:
- 2 odds (Safe Bets)
- 5 odds (Balanced Risk)
- 10 odds (High Reward)
- Rollover (Daily Rollover)
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

def display_frontend_categories():
    """Retrieve and display the predictions in the frontend categories."""
    # Create database session
    db = SessionLocal()
    
    try:
        # Import the models
        from ml_prediction_pipeline import Fixture, Prediction, PredictionCombination
        
        # Get fixtures for May 22nd (fixture_id >= 2000)
        fixtures = db.query(Fixture).filter(Fixture.fixture_id >= 2000).all()
        fixture_ids = [f.fixture_id for f in fixtures]
        
        # Define frontend categories
        frontend_categories = {
            "2_odds": {"name": "Safe Bets", "description": "Lower odds, higher confidence predictions", "target_odds": 2.0},
            "5_odds": {"name": "Balanced Risk", "description": "Medium odds, balanced risk-reward", "target_odds": 5.0},
            "10_odds": {"name": "High Reward", "description": "Higher odds, higher potential returns", "target_odds": 10.0},
            "rollover": {"name": "Daily Rollover", "description": "Daily accumulator with moderate odds", "target_odds": 3.0}
        }
        
        # Print header
        print("\n" + "="*100)
        print(f"PREDICTIONS FOR THURSDAY, MAY 22ND FIXTURES - FRONTEND CATEGORIES")
        print("="*100)
        
        # Get all combinations for each category
        all_combinations = {}
        for category in frontend_categories.keys():
            combinations = db.query(PredictionCombination).filter(
                PredictionCombination.category == category
            ).order_by(
                PredictionCombination.combined_confidence.desc()
            ).all()
            
            # Filter combinations to only include those with May 22nd fixtures
            may22_combinations = []
            for combo in combinations:
                may22_preds = [p for p in combo.predictions if p.fixture_id in fixture_ids]
                if may22_preds:
                    may22_combinations.append({
                        "id": combo.id,
                        "category": combo.category,
                        "combined_odds": combo.combined_odds,
                        "combined_confidence": combo.combined_confidence,
                        "rollover_day": combo.rollover_day,
                        "predictions": may22_preds
                    })
            
            all_combinations[category] = may22_combinations
        
        # Display each category
        for category, info in frontend_categories.items():
            print("\n" + "="*100)
            print(f"{info['name'].upper()} ({category})")
            print(f"Description: {info['description']}")
            print(f"Target Odds: {info['target_odds']}")
            print("="*100)
            
            combinations = all_combinations[category]
            
            if not combinations:
                print(f"No combinations found for {info['name']}")
                continue
            
            # Display the best combination
            best_combo = combinations[0]
            print(f"\nBest Combination:")
            print(f"  Combined Odds: {best_combo['combined_odds']:.2f}")
            print(f"  Combined Confidence: {best_combo['combined_confidence']*100:.2f}%")
            
            if category == "rollover":
                print(f"  Rollover Day: {best_combo['rollover_day']}")
            
            print(f"  Predictions:")
            
            for pred in best_combo['predictions']:
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
                    
                    print(f"    - {match_info}: {pred_text} (Odds: {pred.odds:.2f}, Confidence: {pred.confidence*100:.2f}%)")
            
            # Display all combinations
            print(f"\nAll Combinations ({len(combinations)}):")
            for i, combo in enumerate(combinations):
                if i > 0:  # Skip the best combination which we already displayed
                    print(f"\nCombination {i+1}:")
                    print(f"  Combined Odds: {combo['combined_odds']:.2f}")
                    print(f"  Combined Confidence: {combo['combined_confidence']*100:.2f}%")
                    
                    if category == "rollover":
                        print(f"  Rollover Day: {combo['rollover_day']}")
                    
                    print(f"  Predictions:")
                    
                    for pred in combo['predictions']:
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
                            
                            print(f"    - {match_info}: {pred_text} (Odds: {pred.odds:.2f}, Confidence: {pred.confidence*100:.2f}%)")
        
        # Print summary of best bets across all categories
        print("\n" + "="*100)
        print("SUMMARY OF BEST BETS FOR MAY 22ND")
        print("="*100)
        
        for category, info in frontend_categories.items():
            combinations = all_combinations[category]
            
            if combinations:
                best_combo = combinations[0]
                print(f"\n{info['name']} ({category}):")
                print(f"  Combined Odds: {best_combo['combined_odds']:.2f}")
                print(f"  Combined Confidence: {best_combo['combined_confidence']*100:.2f}%")
                print(f"  Number of Predictions: {len(best_combo['predictions'])}")
                
                # List the fixtures
                fixtures_list = []
                for pred in best_combo['predictions']:
                    fixture = db.query(Fixture).filter(Fixture.fixture_id == pred.fixture_id).first()
                    if fixture:
                        fixtures_list.append(f"{fixture.home_team} vs {fixture.away_team}")
                
                print(f"  Fixtures: {', '.join(fixtures_list)}")
    
    except Exception as e:
        logger.error(f"Error displaying frontend categories: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
    
    finally:
        # Close database session
        db.close()

if __name__ == "__main__":
    # Display frontend categories
    display_frontend_categories()
