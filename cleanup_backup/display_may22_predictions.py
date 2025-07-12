"""
Display May 22nd Predictions

This script retrieves and displays the categorized predictions for the May 22nd fixtures.
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

def display_categorized_predictions():
    """Retrieve and display the categorized predictions for May 22nd fixtures."""
    logger.info("Retrieving categorized predictions for May 22nd fixtures")
    
    # Create database session
    db = SessionLocal()
    
    try:
        # Import the models
        from ml_prediction_pipeline import Fixture, Prediction, PredictionCombination
        
        # Get fixtures for May 22nd (fixture_id >= 2000)
        fixtures = db.query(Fixture).filter(Fixture.fixture_id >= 2000).all()
        fixture_ids = [f.fixture_id for f in fixtures]
        
        logger.info(f"Found {len(fixtures)} fixtures for May 22nd")
        
        # Get all categories
        categories = ["2_odds", "5_odds", "10_odds", "rollover"]
        
        # Print header
        print("\n" + "="*80)
        print(f"PREDICTIONS FOR THURSDAY, MAY 22ND FIXTURES")
        print("="*80)
        
        # Print fixtures
        print("\nFIXTURES:")
        for fixture in fixtures:
            print(f"  {fixture.home_team} vs {fixture.away_team} ({fixture.league_name})")
        
        # Retrieve combinations for each category
        for category in categories:
            print("\n" + "="*80)
            print(f"CATEGORY: {category.upper()}")
            print("="*80)
            
            # Get combinations for this category
            combinations = db.query(PredictionCombination).filter(
                PredictionCombination.category == category
            ).order_by(
                PredictionCombination.combined_confidence.desc()
            ).all()
            
            if not combinations:
                print(f"No combinations found for {category}")
                continue
            
            print(f"Found {len(combinations)} combinations")
            
            # Process each combination
            for i, combo in enumerate(combinations):
                # Only include combinations that have predictions for May 22nd fixtures
                may22_predictions = [p for p in combo.predictions if p.fixture_id in fixture_ids]
                
                if not may22_predictions:
                    continue
                
                print(f"\nCombination {i+1}:")
                print(f"  Combined Odds: {combo.combined_odds:.2f}")
                print(f"  Combined Confidence: {combo.combined_confidence*100:.2f}%")
                
                if category == "rollover":
                    print(f"  Rollover Day: {combo.rollover_day}")
                
                print(f"  Predictions ({len(may22_predictions)}):")
                
                for pred in may22_predictions:
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
        
        # Print individual predictions for each fixture
        print("\n" + "="*80)
        print("INDIVIDUAL PREDICTIONS FOR EACH FIXTURE")
        print("="*80)
        
        for fixture in fixtures:
            print(f"\n{fixture.home_team} vs {fixture.away_team} ({fixture.league_name}):")
            
            # Get predictions for this fixture
            predictions = db.query(Prediction).filter(Prediction.fixture_id == fixture.fixture_id).all()
            
            for pred in predictions:
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
                
                print(f"  - {pred_text} (Odds: {pred.odds:.2f}, Confidence: {pred.confidence*100:.2f}%)")
        
        # Print best bets
        print("\n" + "="*80)
        print("BEST BETS FOR MAY 22ND")
        print("="*80)
        
        # Get all predictions for May 22nd fixtures
        all_predictions = db.query(Prediction).filter(Prediction.fixture_id.in_(fixture_ids)).all()
        
        # Sort by confidence
        all_predictions.sort(key=lambda p: p.confidence, reverse=True)
        
        # Print top 5 predictions
        print("\nTop 5 Highest Confidence Predictions:")
        for i, pred in enumerate(all_predictions[:5]):
            fixture = db.query(Fixture).filter(Fixture.fixture_id == pred.fixture_id).first()
            
            if fixture:
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
                
                print(f"{i+1}. {fixture.home_team} vs {fixture.away_team}: {pred_text} (Odds: {pred.odds:.2f}, Confidence: {pred.confidence*100:.2f}%)")
    
    except Exception as e:
        logger.error(f"Error displaying categorized predictions: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
    
    finally:
        # Close database session
        db.close()

if __name__ == "__main__":
    # Display categorized predictions
    display_categorized_predictions()
