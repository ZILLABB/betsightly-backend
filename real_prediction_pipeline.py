"""
End-to-End Test for BetSightly Prediction Pipeline with Real Data

This script tests the complete prediction pipeline using real data:
1. Fetching fixtures from the football-data.org API
2. Processing the fixture data and preparing it for the prediction models
3. Running the ML models to generate predictions for these fixtures
4. Categorizing the predictions into the four distinct odds groups
5. Storing the categorized predictions in the database
6. Retrieving the predictions via the API endpoints
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Add the app directory to the path so we can import our modules
sys.path.append(os.path.join(os.getcwd(), "app"))

# Import necessary modules
try:
    from database import Base, engine, SessionLocal
    from services.api_client import APIClient, FootballDataClient
    from services.prediction_service_improved import PredictionService
    import fixture
    import prediction
    import prediction_combination
    from utils.config import settings
except ImportError as e:
    logger.error(f"Error importing modules: {e}")
    logger.info("Make sure you're running this script from the project root directory")
    sys.exit(1)

def run_prediction_pipeline():
    """Execute the complete prediction pipeline with real data."""
    logger.info("Starting end-to-end test of the prediction pipeline with real data")
    
    # Create database session
    Session = sessionmaker(bind=engine)
    db = Session()
    
    try:
        # Step 1: Fetch tomorrow's fixtures from the football-data.org API
        logger.info("Step 1: Fetching tomorrow's fixtures from the football-data.org API")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        logger.info(f"Fetching fixtures for date: {tomorrow}")
        
        # Initialize the Football-Data.org API client
        football_data_client = FootballDataClient(
            api_key=settings.football_data.API_KEY,
            base_url=settings.football_data.BASE_URL
        )
        
        # Get tomorrow's matches
        fixtures_response = football_data_client.get_daily_matches(date_str=tomorrow)
        
        if "matches" not in fixtures_response:
            logger.error(f"Error fetching fixtures: {fixtures_response}")
            return
        
        fixtures = fixtures_response.get("matches", [])
        logger.info(f"Fetched {len(fixtures)} fixtures for tomorrow")
        
        if not fixtures:
            logger.warning(f"No fixtures found for {tomorrow}")
            return
        
        # Print a sample fixture
        if fixtures:
            logger.info(f"Sample fixture: {json.dumps(fixtures[0], indent=2)}")
        
        # Step 2: Process fixture data and prepare it for the prediction models
        logger.info("Step 2: Processing fixture data and preparing it for the prediction models")
        
        # Initialize the prediction service
        prediction_service = PredictionService(db)
        
        # Convert Football-Data.org fixtures to our format
        processed_fixtures = []
        for match in fixtures:
            try:
                fixture_data = {
                    "fixture": {
                        "id": match.get("id"),
                        "date": match.get("utcDate"),
                        "status": {"short": "NS", "long": "Not Started"}
                    },
                    "league": {
                        "id": match.get("competition", {}).get("id"),
                        "name": match.get("competition", {}).get("name"),
                        "country": match.get("competition", {}).get("area", {}).get("name"),
                        "season": match.get("season", {}).get("id")
                    },
                    "teams": {
                        "home": {
                            "id": match.get("homeTeam", {}).get("id"),
                            "name": match.get("homeTeam", {}).get("name")
                        },
                        "away": {
                            "id": match.get("awayTeam", {}).get("id"),
                            "name": match.get("awayTeam", {}).get("name")
                        }
                    },
                    "goals": {
                        "home": match.get("score", {}).get("fullTime", {}).get("home"),
                        "away": match.get("score", {}).get("fullTime", {}).get("away")
                    }
                }
                processed_fixtures.append(fixture_data)
                logger.info(f"Processed fixture: {fixture_data['teams']['home']['name']} vs {fixture_data['teams']['away']['name']}")
            except Exception as e:
                logger.error(f"Error processing fixture: {str(e)}")
        
        logger.info(f"Processed {len(processed_fixtures)} fixtures")
        
        # Step 3: Run the ML models to generate predictions
        logger.info("Step 3: Running ML models to generate predictions")
        
        # Get historical data for feature engineering
        logger.info("Fetching historical data for feature engineering")
        historical_data = prediction_service._get_historical_data()
        logger.info(f"Historical data shape: {historical_data.shape if hasattr(historical_data, 'shape') else 'N/A'}")
        
        # Generate predictions for each fixture
        all_predictions = []
        
        for fixture_data in processed_fixtures[:10]:  # Limit to 10 fixtures for testing
            try:
                fixture_id = fixture_data.get("fixture", {}).get("id")
                logger.info(f"Generating prediction for fixture: {fixture_id}")
                
                # Generate prediction using the ensemble model
                prediction = prediction_service.ensemble_model.predict(fixture_data, historical_data)
                
                if prediction.get("status") == "success":
                    # Add fixture information
                    fixture_info = {
                        "fixture_id": fixture_id,
                        "date": fixture_data.get("fixture", {}).get("date"),
                        "league": fixture_data.get("league", {}).get("name"),
                        "home_team": fixture_data.get("teams", {}).get("home", {}).get("name"),
                        "away_team": fixture_data.get("teams", {}).get("away", {}).get("name")
                    }
                    
                    # Combine fixture info with predictions
                    prediction_with_info = {
                        "fixture": fixture_info,
                        "predictions": prediction.get("predictions", [])
                    }
                    
                    all_predictions.append(prediction_with_info)
                    logger.info(f"Generated prediction for {fixture_info['home_team']} vs {fixture_info['away_team']}")
                
            except Exception as e:
                logger.error(f"Error generating prediction: {str(e)}")
        
        logger.info(f"Generated {len(all_predictions)} predictions")
        
        # Step 4: Categorize predictions into the four distinct odds groups
        logger.info("Step 4: Categorizing predictions into the four distinct odds groups")
        categorized_predictions = prediction_service._categorize_predictions(all_predictions)
        
        # Print categorized predictions
        for category, predictions in categorized_predictions.items():
            logger.info(f"Category: {category}, Number of combinations: {len(predictions)}")
            
            if predictions:
                sample_combo = predictions[0]
                logger.info(f"Sample combination - Combined odds: {sample_combo.get('combined_odds')}, Combined confidence: {sample_combo.get('combined_confidence')}")
                logger.info(f"Number of predictions in combination: {len(sample_combo.get('predictions', []))}")
        
        # Step 5: Store the categorized predictions in the database
        logger.info("Step 5: Storing the categorized predictions in the database")
        
        # Save fixtures to database
        for fixture_data in processed_fixtures[:10]:
            try:
                fixture_id = fixture_data.get("fixture", {}).get("id")
                fixture_date = fixture_data.get("fixture", {}).get("date")
                league_id = fixture_data.get("league", {}).get("id")
                league_name = fixture_data.get("league", {}).get("name")
                home_team_id = fixture_data.get("teams", {}).get("home", {}).get("id")
                home_team = fixture_data.get("teams", {}).get("home", {}).get("name")
                away_team_id = fixture_data.get("teams", {}).get("away", {}).get("id")
                away_team = fixture_data.get("teams", {}).get("away", {}).get("name")
                
                # Check if fixture already exists
                existing_fixture = db.query(fixture.Fixture).filter(fixture.Fixture.fixture_id == fixture_id).first()
                
                if not existing_fixture:
                    # Create new fixture
                    new_fixture = fixture.Fixture(
                        fixture_id=fixture_id,
                        date=fixture_date,
                        league_id=league_id,
                        league_name=league_name,
                        home_team_id=home_team_id,
                        home_team=home_team,
                        away_team_id=away_team_id,
                        away_team=away_team
                    )
                    
                    db.add(new_fixture)
                    logger.info(f"Added fixture to database: {home_team} vs {away_team}")
            
            except Exception as e:
                logger.error(f"Error saving fixture: {str(e)}")
        
        # Commit changes
        db.commit()
        
        # Save prediction combinations
        for category, combinations in categorized_predictions.items():
            logger.info(f"Saving {len(combinations)} combinations for category {category}")
            
            # Save combinations to database
            success = prediction_service.save_prediction_combinations(combinations, datetime.now())
            
            if success:
                logger.info(f"Successfully saved combinations for category {category}")
            else:
                logger.error(f"Failed to save combinations for category {category}")
        
        # Step 6: Retrieve the predictions via the API endpoints
        logger.info("Step 6: Retrieving the predictions via the API endpoints")
        
        # Simulate API endpoint calls
        for category in ["2_odds", "5_odds", "10_odds", "rollover"]:
            logger.info(f"Retrieving predictions for category: {category}")
            
            # Get predictions from database
            combinations = prediction_service.get_prediction_combinations_by_category(
                category=category,
                date=datetime.now(),
                limit=5
            )
            
            logger.info(f"Retrieved {len(combinations)} combinations for category {category}")
            
            if combinations:
                logger.info(f"Sample combination ID: {combinations[0].get('id')}")
                logger.info(f"Number of predictions in combination: {len(combinations[0].get('predictions', []))}")
        
        logger.info("End-to-end test completed successfully")
    
    except Exception as e:
        logger.error(f"Error in prediction pipeline: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
    
    finally:
        # Close database session
        db.close()

if __name__ == "__main__":
    # Initialize database
    Base.metadata.create_all(bind=engine)
    
    # Run the prediction pipeline
    run_prediction_pipeline()
