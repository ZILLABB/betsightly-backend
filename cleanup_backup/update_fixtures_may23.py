"""
Update Fixtures for May 23rd

This script removes yesterday's fixtures (May 22nd) and adds new fixtures for today (May 23rd).
It then processes these fixtures through our advanced ML models to generate new predictions.
"""

import os
import sys
import json
import logging
from datetime import datetime
import uuid
from sqlalchemy import create_engine, delete
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
    from ml_prediction_pipeline import Fixture, Prediction, PredictionCombination, prediction_combination_items, MLPredictionService
except ImportError:
    logger.error("Could not import models from ml_prediction_pipeline. Make sure the file exists and is accessible.")
    sys.exit(1)

# Define the new fixtures for May 23rd
MAY_23_FIXTURES = [
    {
        "fixture_id": 2001,
        "date": "2023-05-23T18:30:00",
        "league_name": "Romania Liga 1",
        "home_team": "CFR Cluj",
        "away_team": "FCSB",
        "home_form": 2.1,
        "away_form": 2.3,
        "home_odds": 2.20,
        "draw_odds": 3.25,
        "away_odds": 3.10
    },
    {
        "fixture_id": 2002,
        "date": "2023-05-23T18:00:00",
        "league_name": "Serbia Super Liga",
        "home_team": "Čukarički",
        "away_team": "FK Železničar Pančevo",
        "home_form": 2.0,
        "away_form": 1.5,
        "home_odds": 1.65,
        "draw_odds": 3.60,
        "away_odds": 4.75
    },
    {
        "fixture_id": 2003,
        "date": "2023-05-23T14:00:00",
        "league_name": "South Korea K League 1",
        "home_team": "FC Anyang",
        "away_team": "Pohang Steelers",
        "home_form": 1.7,
        "away_form": 2.2,
        "home_odds": 3.10,
        "draw_odds": 3.30,
        "away_odds": 2.15
    },
    {
        "fixture_id": 2004,
        "date": "2023-05-23T14:30:00",
        "league_name": "South Korea K League 1",
        "home_team": "Jeju United FC",
        "away_team": "Jeonbuk Hyundai Motors",
        "home_form": 1.8,
        "away_form": 2.4,
        "home_odds": 3.50,
        "draw_odds": 3.40,
        "away_odds": 1.95
    },
    {
        "fixture_id": 2005,
        "date": "2023-05-23T17:00:00",
        "league_name": "UEFA Conference League",
        "home_team": "HNK Hajduk Split",
        "away_team": "Twente",
        "home_form": 1.9,
        "away_form": 2.1,
        "home_odds": 2.40,
        "draw_odds": 3.30,
        "away_odds": 2.80
    },
    {
        "fixture_id": 2006,
        "date": "2023-05-23T17:30:00",
        "league_name": "France Ligue 1/Germany 2. Bundesliga",
        "home_team": "Metz",
        "away_team": "Fortuna Düsseldorf",
        "home_form": 1.6,
        "away_form": 1.9,
        "home_odds": 2.70,
        "draw_odds": 3.30,
        "away_odds": 2.45
    },
    {
        "fixture_id": 2007,
        "date": "2023-05-23T10:00:00",
        "league_name": "UEFA Champions League",
        "home_team": "PSV",
        "away_team": "Leverkusen",
        "home_form": 2.3,
        "away_form": 2.5,
        "home_odds": 2.60,
        "draw_odds": 3.50,
        "away_odds": 2.50
    },
    {
        "fixture_id": 2008,
        "date": "2023-05-23T10:00:00",
        "league_name": "UEFA Champions League",
        "home_team": "Sturm Graz",
        "away_team": "Copenhagen",
        "home_form": 1.8,
        "away_form": 1.9,
        "home_odds": 2.35,
        "draw_odds": 3.25,
        "away_odds": 2.90
    },
    {
        "fixture_id": 2009,
        "date": "2023-05-23T11:00:00",
        "league_name": "UEFA Champions League",
        "home_team": "Benfica",
        "away_team": "VfB Stuttgart",
        "home_form": 2.4,
        "away_form": 2.2,
        "home_odds": 1.85,
        "draw_odds": 3.60,
        "away_odds": 3.80
    },
    {
        "fixture_id": 2010,
        "date": "2023-05-23T11:00:00",
        "league_name": "UEFA Conference League",
        "home_team": "Pogoń Szczecin",
        "away_team": "Hartberg",
        "home_form": 1.9,
        "away_form": 1.7,
        "home_odds": 1.75,
        "draw_odds": 3.50,
        "away_odds": 4.20
    },
    {
        "fixture_id": 2011,
        "date": "2023-05-23T17:00:00",
        "league_name": "Slovakia Super Liga",
        "home_team": "Dunajská Streda",
        "away_team": "Podbrezová",
        "home_form": 2.0,
        "away_form": 1.6,
        "home_odds": 1.70,
        "draw_odds": 3.60,
        "away_odds": 4.50
    },
    {
        "fixture_id": 2012,
        "date": "2023-05-23T16:30:00",
        "league_name": "Slovenia Prva Liga",
        "home_team": "Radomlje",
        "away_team": "Primorje Ajdovščina",
        "home_form": 1.7,
        "away_form": 1.5,
        "home_odds": 2.10,
        "draw_odds": 3.30,
        "away_odds": 3.20
    },
    {
        "fixture_id": 2013,
        "date": "2023-05-23T20:00:00",
        "league_name": "Spain La Liga",
        "home_team": "Betis",
        "away_team": "Valencia",
        "home_form": 2.1,
        "away_form": 1.8,
        "home_odds": 1.90,
        "draw_odds": 3.40,
        "away_odds": 3.80
    },
    {
        "fixture_id": 2014,
        "date": "2023-05-23T18:00:00",
        "league_name": "Sweden Division 2",
        "home_team": "Karlbergs",
        "away_team": "Hammarby Talang",
        "home_form": 1.6,
        "away_form": 1.8,
        "home_odds": 2.50,
        "draw_odds": 3.30,
        "away_odds": 2.60
    },
    {
        "fixture_id": 2015,
        "date": "2023-05-23T18:30:00",
        "league_name": "Sweden Division 2",
        "home_team": "Arlanda",
        "away_team": "Stocksund",
        "home_form": 1.7,
        "away_form": 1.6,
        "home_odds": 2.20,
        "draw_odds": 3.30,
        "away_odds": 2.90
    },
    {
        "fixture_id": 2016,
        "date": "2023-05-23T18:00:00",
        "league_name": "Sweden Division 2",
        "home_team": "Rosengård",
        "away_team": "Lunds",
        "home_form": 1.8,
        "away_form": 1.7,
        "home_odds": 2.30,
        "draw_odds": 3.30,
        "away_odds": 2.80
    },
    {
        "fixture_id": 2017,
        "date": "2023-05-23T18:00:00",
        "league_name": "Sweden Division 2",
        "home_team": "Torslanda",
        "away_team": "Trollhättans",
        "home_form": 1.7,
        "away_form": 1.6,
        "home_odds": 2.40,
        "draw_odds": 3.30,
        "away_odds": 2.70
    }
]

def update_fixtures():
    """Remove yesterday's fixtures and add new fixtures for today."""
    # Create database session
    db = SessionLocal()
    
    try:
        # Step 1: Remove yesterday's fixtures (May 22nd)
        logger.info("Removing yesterday's fixtures (May 22nd)...")
        
        # Get all fixtures from May 22nd
        may_22_fixtures = db.query(Fixture).filter(
            Fixture.date >= datetime(2023, 5, 22, 0, 0, 0),
            Fixture.date < datetime(2023, 5, 23, 0, 0, 0)
        ).all()
        
        # Get fixture IDs
        may_22_fixture_ids = [fixture.fixture_id for fixture in may_22_fixtures]
        logger.info(f"Found {len(may_22_fixture_ids)} fixtures from May 22nd")
        
        # Delete predictions for these fixtures
        if may_22_fixture_ids:
            # First, remove the fixtures from prediction combinations
            for fixture_id in may_22_fixture_ids:
                # Get predictions for this fixture
                predictions = db.query(Prediction).filter(Prediction.fixture_id == fixture_id).all()
                
                # Remove predictions from combinations
                for prediction in predictions:
                    # Remove from combinations
                    prediction.combinations = []
            
            # Commit changes
            db.commit()
            
            # Now delete the predictions
            for fixture_id in may_22_fixture_ids:
                db.query(Prediction).filter(Prediction.fixture_id == fixture_id).delete()
            
            # Commit changes
            db.commit()
            
            # Finally, delete the fixtures
            for fixture_id in may_22_fixture_ids:
                db.query(Fixture).filter(Fixture.fixture_id == fixture_id).delete()
            
            # Commit changes
            db.commit()
            
            logger.info(f"Deleted {len(may_22_fixture_ids)} fixtures and their predictions")
        
        # Step 2: Add new fixtures for today (May 23rd)
        logger.info("Adding new fixtures for today (May 23rd)...")
        
        # Initialize ML prediction service
        ml_prediction_service = MLPredictionService(db)
        
        # Process fixtures
        processed_fixtures = ml_prediction_service.process_fixtures(MAY_23_FIXTURES)
        logger.info(f"Processed {len(processed_fixtures)} fixtures for May 23rd")
        
        # Generate predictions using ML models
        all_predictions = ml_prediction_service.generate_predictions(processed_fixtures)
        logger.info(f"Generated {len(all_predictions)} predictions")
        
        # Categorize predictions
        categorized_predictions = ml_prediction_service.categorize_predictions(all_predictions)
        
        # Print categorized predictions
        for category, predictions in categorized_predictions.items():
            logger.info(f"Category: {category}, Number of combinations: {len(predictions)}")
            
            if predictions:
                sample_combo = predictions[0]
                logger.info(f"Sample combination - Combined odds: {sample_combo.get('combined_odds')}, Combined confidence: {sample_combo.get('combined_confidence')}")
                logger.info(f"Number of predictions in combination: {len(sample_combo.get('predictions', []))}")
                
                # Save combinations to database
                logger.info(f"Saving {len(predictions)} combinations for category {category}")
                success = ml_prediction_service.save_prediction_combinations(predictions, category)
                
                if success:
                    logger.info(f"Successfully saved combinations for category {category}")
                else:
                    logger.error(f"Failed to save combinations for category {category}")
        
        logger.info("Fixtures update completed successfully")
    
    except Exception as e:
        logger.error(f"Error updating fixtures: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        db.rollback()
    
    finally:
        # Close database session
        db.close()

if __name__ == "__main__":
    # Update fixtures
    update_fixtures()
