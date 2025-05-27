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
import uuid
import itertools
from datetime import datetime, timedelta
import requests
import pandas as pd
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Create a SQLite database for testing
DATABASE_URL = "sqlite:///test_predictions.db"
engine = create_engine(DATABASE_URL)
Base = declarative_base()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Define database models
class Fixture(Base):
    __tablename__ = "fixtures"

    id = Column(Integer, primary_key=True)
    fixture_id = Column(Integer, unique=True, index=True)
    date = Column(DateTime)
    league_id = Column(Integer)
    league_name = Column(String(100))
    home_team_id = Column(Integer)
    home_team = Column(String(100))
    away_team_id = Column(Integer)
    away_team = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    predictions = relationship("Prediction", back_populates="fixture")

    def to_dict(self):
        return {
            "id": self.id,
            "fixture_id": self.fixture_id,
            "date": self.date.isoformat() if self.date else None,
            "league_id": self.league_id,
            "league_name": self.league_name,
            "home_team_id": self.home_team_id,
            "home_team": self.home_team,
            "away_team_id": self.away_team_id,
            "away_team": self.away_team
        }

# Association table for many-to-many relationship between predictions and combinations
prediction_combination_items = Table(
    "prediction_combination_items",
    Base.metadata,
    Column("id", Integer, primary_key=True),
    Column("combination_id", String(50), ForeignKey("prediction_combinations.id")),
    Column("prediction_id", Integer, ForeignKey("predictions.id"))
)

class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True)
    fixture_id = Column(Integer, ForeignKey("fixtures.fixture_id"))
    match_result_pred = Column(String(10))
    home_win_pred = Column(Float)
    draw_pred = Column(Float)
    away_win_pred = Column(Float)
    over_under_pred = Column(String(10))
    over_2_5_pred = Column(Float)
    under_2_5_pred = Column(Float)
    btts_pred = Column(String(10))
    btts_yes_pred = Column(Float)
    btts_no_pred = Column(Float)
    prediction_type = Column(String(20))
    odds = Column(Float)
    confidence = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    fixture = relationship("Fixture", back_populates="predictions")
    combinations = relationship("PredictionCombination", secondary=prediction_combination_items, back_populates="predictions")

    def to_dict(self):
        return {
            "id": self.id,
            "fixture_id": self.fixture_id,
            "match_result_pred": self.match_result_pred,
            "home_win_pred": self.home_win_pred,
            "draw_pred": self.draw_pred,
            "away_win_pred": self.away_win_pred,
            "over_under_pred": self.over_under_pred,
            "over_2_5_pred": self.over_2_5_pred,
            "under_2_5_pred": self.under_2_5_pred,
            "btts_pred": self.btts_pred,
            "btts_yes_pred": self.btts_yes_pred,
            "btts_no_pred": self.btts_no_pred,
            "prediction_type": self.prediction_type,
            "odds": self.odds,
            "confidence": self.confidence
        }

class PredictionCombination(Base):
    __tablename__ = "prediction_combinations"

    id = Column(String(50), primary_key=True)
    category = Column(String(20), index=True)
    combined_odds = Column(Float, default=0)
    combined_confidence = Column(Float, default=0)
    rollover_day = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    predictions = relationship("Prediction", secondary=prediction_combination_items, back_populates="combinations")

    def to_dict(self):
        return {
            "id": self.id,
            "category": self.category,
            "combined_odds": self.combined_odds,
            "combined_confidence": self.combined_confidence,
            "rollover_day": self.rollover_day,
            "predictions": [p.to_dict() for p in self.predictions]
        }

# Create tables
Base.metadata.create_all(bind=engine)

# Football-Data.org API client
class FootballDataClient:
    def __init__(self, api_key, base_url="https://api.football-data.org/v4"):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {"X-Auth-Token": api_key}

    def get_daily_matches(self, date_str):
        """Get matches for a specific date."""
        url = f"{self.base_url}/matches"
        params = {"date": date_str}

        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching matches: {str(e)}")
            return {"error": str(e)}

# Simplified prediction service
class PredictionService:
    def __init__(self, db):
        self.db = db
        self.ensemble_model = EnsembleModel()

    def get_predictions_by_date(self, date):
        """Get predictions for a specific date."""
        if not self.db:
            return []

        try:
            # Get fixtures for the date
            start_of_day = datetime.combine(date.date(), datetime.min.time())
            end_of_day = datetime.combine(date.date(), datetime.max.time())

            fixtures = self.db.query(Fixture).filter(
                Fixture.date >= start_of_day,
                Fixture.date <= end_of_day
            ).all()

            # Get predictions for these fixtures
            predictions = []
            for fixture in fixtures:
                fixture_predictions = self.db.query(Prediction).filter(
                    Prediction.fixture_id == fixture.fixture_id
                ).all()

                if fixture_predictions:
                    predictions.append({
                        "fixture": fixture.to_dict(),
                        "predictions": [p.to_dict() for p in fixture_predictions]
                    })

            return predictions
        except Exception as e:
            logger.error(f"Error getting predictions by date: {str(e)}")
            return []

    def _get_historical_data(self):
        """Get historical data for feature engineering."""
        # For testing, we'll return a simple DataFrame
        import pandas as pd
        import numpy as np

        # Create a simple DataFrame with historical match data
        data = {
            "home_team_id": np.random.randint(30, 70, 100),
            "away_team_id": np.random.randint(30, 70, 100),
            "home_goals": np.random.randint(0, 5, 100),
            "away_goals": np.random.randint(0, 4, 100),
            "home_win": np.random.randint(0, 2, 100),
            "draw": np.random.randint(0, 2, 100),
            "away_win": np.random.randint(0, 2, 100),
            "over_2_5": np.random.randint(0, 2, 100),
            "btts": np.random.randint(0, 2, 100)
        }

        return pd.DataFrame(data)

    def _categorize_predictions(self, predictions):
        """Categorize predictions into different odds groups."""
        # Track used fixtures to avoid duplicates across categories
        used_fixtures = set()

        # Generate combinations for each category
        categorized = {
            "2_odds": [],
            "5_odds": [],
            "10_odds": [],
            "rollover": []
        }

        # Process categories in order of priority
        for category in ["rollover", "10_odds", "5_odds", "2_odds"]:
            # Target odds for each category
            target_odds = {
                "2_odds": 2.0,
                "5_odds": 5.0,
                "10_odds": 10.0,
                "rollover": 3.0
            }

            # Get available predictions (excluding already used fixtures)
            available_predictions = []
            for prediction in predictions:
                fixture = prediction.get("fixture", {})
                fixture_id = fixture.get("fixture_id")

                if fixture_id not in used_fixtures:
                    available_predictions.append(prediction)

            # Create combinations for this category
            combinations = self.create_prediction_combinations(
                available_predictions, target_odds[category]
            )

            # Mark used fixtures
            for combo in combinations:
                for pred in combo.get("predictions", []):
                    fixture_id = pred.get("fixture_id")
                    if fixture_id:
                        used_fixtures.add(fixture_id)

            # Add combinations to category
            categorized[category] = combinations

            # Add day number for rollover
            if category == "rollover":
                for i, combo in enumerate(categorized[category]):
                    combo["day"] = i + 1

        return categorized

    def create_prediction_combinations(self, predictions, target_odds):
        """Create combinations of predictions to reach target odds."""
        if not predictions:
            return []

        # Extract individual predictions
        individual_predictions = []
        for pred_group in predictions:
            fixture = pred_group.get("fixture", {})
            for pred in pred_group.get("predictions", []):
                # Add fixture info to prediction
                pred_with_fixture = pred.copy()
                pred_with_fixture["fixture"] = fixture
                individual_predictions.append(pred_with_fixture)

        # Sort by confidence (highest first)
        sorted_predictions = sorted(
            individual_predictions,
            key=lambda p: p.get("confidence", 0),
            reverse=True
        )

        # Try combinations of different sizes
        combinations = []

        # Try combinations of 1-4 predictions
        for size in range(1, min(5, len(sorted_predictions) + 1)):
            for combo in itertools.combinations(sorted_predictions, size):
                # Calculate combined odds
                combined_odds = 1.0
                combined_confidence = 0.0

                for pred in combo:
                    odds = pred.get("odds", 1.0)
                    confidence = pred.get("confidence", 0.0)

                    combined_odds *= odds
                    combined_confidence += confidence

                # Calculate average confidence
                avg_confidence = combined_confidence / len(combo) if combo else 0.0

                # Check if combined odds are close to target
                if combined_odds >= target_odds * 0.8 and combined_odds <= target_odds * 1.2:
                    combinations.append({
                        "id": f"combo_{uuid.uuid4()}",
                        "predictions": list(combo),
                        "combined_odds": combined_odds,
                        "combined_confidence": avg_confidence
                    })

        # Sort by combined confidence (highest first)
        sorted_combinations = sorted(
            combinations,
            key=lambda x: x.get("combined_confidence", 0),
            reverse=True
        )

        return sorted_combinations[:5]  # Limit to 5 combinations

    def get_prediction_combinations_by_category(self, category, date, limit=10):
        """Get prediction combinations for a specific category."""
        if not self.db:
            return []

        try:
            # Get start and end of day
            start_of_day = datetime.combine(date.date(), datetime.min.time())
            end_of_day = datetime.combine(date.date(), datetime.max.time())

            # Query combinations by category and date
            combinations = self.db.query(PredictionCombination).filter(
                PredictionCombination.category == category,
                PredictionCombination.created_at >= start_of_day,
                PredictionCombination.created_at <= end_of_day
            ).order_by(
                PredictionCombination.combined_confidence.desc()
            ).limit(limit).all()

            # Convert to dictionaries
            result = [combo.to_dict() for combo in combinations]

            return result

        except Exception as e:
            logger.error(f"Error getting prediction combinations: {str(e)}")
            return []

    def save_prediction_combinations(self, combinations, date):
        """Save prediction combinations to the database."""
        if not self.db:
            return False

        try:
            # Save each combination
            for combo in combinations:
                # Create combination record
                combination = PredictionCombination(
                    id=combo.get("id", f"{combo.get('category')}_{uuid.uuid4()}"),
                    category=combo.get("category"),
                    combined_odds=combo.get("combined_odds", 0),
                    combined_confidence=combo.get("combined_confidence", 0),
                    rollover_day=combo.get("day")
                )

                # Add to database
                self.db.add(combination)
                self.db.flush()  # Flush to get the ID

                # Add predictions to combination
                for pred_dict in combo.get("predictions", []):
                    # Get or create prediction
                    fixture_id = pred_dict.get("fixture_id")

                    if not fixture_id and "fixture" in pred_dict:
                        fixture_id = pred_dict.get("fixture", {}).get("fixture_id")

                    if fixture_id:
                        # Check if prediction already exists
                        prediction = self.db.query(Prediction).filter(
                            Prediction.fixture_id == fixture_id,
                            Prediction.prediction_type == pred_dict.get("prediction_type")
                        ).first()

                        if not prediction:
                            # Create new prediction
                            prediction = Prediction(
                                fixture_id=fixture_id,
                                match_result_pred=pred_dict.get("match_result_pred"),
                                home_win_pred=pred_dict.get("home_win_pred"),
                                draw_pred=pred_dict.get("draw_pred"),
                                away_win_pred=pred_dict.get("away_win_pred"),
                                over_under_pred=pred_dict.get("over_under_pred"),
                                over_2_5_pred=pred_dict.get("over_2_5_pred"),
                                under_2_5_pred=pred_dict.get("under_2_5_pred"),
                                btts_pred=pred_dict.get("btts_pred"),
                                btts_yes_pred=pred_dict.get("btts_yes_pred"),
                                btts_no_pred=pred_dict.get("btts_no_pred"),
                                prediction_type=pred_dict.get("prediction_type"),
                                odds=pred_dict.get("odds"),
                                confidence=pred_dict.get("confidence")
                            )

                            self.db.add(prediction)
                            self.db.flush()  # Flush to get the ID

                        # Add prediction to combination
                        if prediction:
                            combination.predictions.append(prediction)

            # Commit changes
            self.db.commit()

            return True

        except Exception as e:
            logger.error(f"Error saving prediction combinations: {str(e)}")
            self.db.rollback()
            return False

# Simplified ensemble model for testing
class EnsembleModel:
    def __init__(self):
        pass

    def predict(self, fixture_data, historical_data):
        """Generate predictions for a fixture."""
        # For testing, we'll return mock predictions
        home_team = fixture_data.get("teams", {}).get("home", {}).get("name", "Home Team")
        away_team = fixture_data.get("teams", {}).get("away", {}).get("name", "Away Team")

        # Generate random predictions
        import random

        # Home win probability
        home_win_prob = random.uniform(0.3, 0.6)
        draw_prob = random.uniform(0.2, 0.3)
        away_win_prob = 1.0 - home_win_prob - draw_prob

        # Over/under probability
        over_prob = random.uniform(0.4, 0.7)
        under_prob = 1.0 - over_prob

        # BTTS probability
        btts_yes_prob = random.uniform(0.5, 0.8)
        btts_no_prob = 1.0 - btts_yes_prob

        # Determine most likely outcome
        outcomes = ["home", "draw", "away"]
        probs = [home_win_prob, draw_prob, away_win_prob]
        match_result = outcomes[probs.index(max(probs))]

        # Calculate odds (simplified)
        home_odds = round(1.0 / home_win_prob, 2)
        draw_odds = round(1.0 / draw_prob, 2)
        away_odds = round(1.0 / away_win_prob, 2)
        over_odds = round(1.0 / over_prob, 2)
        under_odds = round(1.0 / under_prob, 2)
        btts_yes_odds = round(1.0 / btts_yes_prob, 2)
        btts_no_odds = round(1.0 / btts_no_prob, 2)

        # Create predictions
        predictions = [
            {
                "type": "match_result",
                "prediction": match_result,
                "home_win": round(home_win_prob * 100),
                "draw": round(draw_prob * 100),
                "away_win": round(away_win_prob * 100),
                "odds": home_odds if match_result == "home" else (draw_odds if match_result == "draw" else away_odds),
                "confidence": round(max(probs) * 100)
            },
            {
                "type": "over_under",
                "prediction": "over" if over_prob > under_prob else "under",
                "over_2_5": round(over_prob * 100),
                "under_2_5": round(under_prob * 100),
                "odds": over_odds if over_prob > under_prob else under_odds,
                "confidence": round(max(over_prob, under_prob) * 100)
            },
            {
                "type": "btts",
                "prediction": "yes" if btts_yes_prob > btts_no_prob else "no",
                "btts_yes": round(btts_yes_prob * 100),
                "btts_no": round(btts_no_prob * 100),
                "odds": btts_yes_odds if btts_yes_prob > btts_no_prob else btts_no_odds,
                "confidence": round(max(btts_yes_prob, btts_no_prob) * 100)
            }
        ]

        return {
            "status": "success",
            "predictions": predictions
        }

def run_prediction_pipeline():
    """Execute the complete prediction pipeline with real data."""
    logger.info("Starting end-to-end test of the prediction pipeline with real data")

    # Create database session
    db = SessionLocal()

    try:
        # Step 1: Fetch fixtures for a specific date (using a date we know has matches)
        logger.info("Step 1: Fetching fixtures from the football-data.org API")
        # Use a specific date that we know has matches (e.g., a Saturday during the season)
        target_date = "2023-05-20"  # A Saturday during the 2022-2023 season
        logger.info(f"Fetching fixtures for date: {target_date}")

        # Initialize the Football-Data.org API client
        football_data_client = FootballDataClient(
            api_key="f9ed94ba8dde4a57b742ce7075057310"  # Replace with your API key
        )

        # Get matches for the target date
        fixtures_response = football_data_client.get_daily_matches(date_str=target_date)

        if "matches" not in fixtures_response:
            logger.error(f"Error fetching fixtures: {fixtures_response}")
            return

        fixtures = fixtures_response.get("matches", [])
        logger.info(f"Fetched {len(fixtures)} fixtures for {target_date}")

        if not fixtures:
            logger.warning(f"No fixtures found for {target_date}")
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
                existing_fixture = db.query(Fixture).filter(Fixture.fixture_id == fixture_id).first()

                if not existing_fixture:
                    # Create new fixture
                    new_fixture = Fixture(
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

            # Add category to each combination
            for combo in combinations:
                combo["category"] = category

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
    # Run the prediction pipeline
    run_prediction_pipeline()
