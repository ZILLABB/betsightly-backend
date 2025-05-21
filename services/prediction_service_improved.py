"""
Prediction Service Module (Improved)

This module provides an improved service for generating football match predictions.
It uses the improved ensemble model and API client.
"""

import os
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple, Union
from datetime import datetime, timedelta

from app.ml.ensemble_model_improved import improved_ensemble_model
from app.services.api_client import APIClient
from app.services.prediction_categorizer import prediction_categorizer
from app.utils.common import setup_logging, load_json_file, save_json_file
from app.utils.config import settings
from app.models.fixture import Fixture
from app.models.prediction import Prediction

# Set up logging
logger = setup_logging(__name__)

class PredictionService:
    """
    Service for generating football match predictions.

    Features:
    - Fetches fixtures from API Football
    - Generates predictions using ensemble model
    - Categorizes predictions by odds
    - Generates rollover predictions
    """

    def __init__(self, db=None):
        """Initialize the prediction service."""
        self.ensemble_model = improved_ensemble_model
        self.api_client = APIClient(base_url="https://api-football-v1.p.rapidapi.com/v3", headers={"x-rapidapi-host": "api-football-v1.p.rapidapi.com", "x-rapidapi-key": settings.API_FOOTBALL_KEY})
        self.db = db

        # Ensure cache directory exists
        self.cache_dir = os.path.join(settings.ml.CACHE_DIR, "predictions")
        os.makedirs(self.cache_dir, exist_ok=True)

    def get_predictions_for_date(self, date: str, force_update: bool = False) -> Dict[str, Any]:
        """
        Get predictions for fixtures on a specific date.

        Args:
            date: Date in format YYYY-MM-DD
            force_update: Whether to force an update from the API

        Returns:
            Dictionary with predictions
        """
        # Check cache if not forcing update
        if not force_update:
            cache_file = os.path.join(self.cache_dir, f"predictions_{date}.json")
            cached_predictions = load_json_file(cache_file)

            if cached_predictions:
                logger.info(f"Using cached predictions for {date}")
                return cached_predictions

        # Get fixtures for the date
        fixtures_response = self.api_client.get_fixtures_improved(date=date)

        if fixtures_response.get("status") == "error":
            logger.error(f"Error getting fixtures: {fixtures_response.get('message')}")
            return {
                "status": "error",
                "message": f"Error getting fixtures: {fixtures_response.get('message')}"
            }

        fixtures = fixtures_response.get("response", [])

        if not fixtures:
            logger.warning(f"No fixtures found for {date}")
            return {
                "status": "success",
                "date": date,
                "predictions": [],
                "categories": {}
            }

        # Get historical data for feature engineering
        historical_data = self._get_historical_data()

        # Generate predictions for each fixture
        all_predictions = []

        for fixture in fixtures:
            try:
                # Skip fixtures that have already started or finished
                status = fixture.get("fixture", {}).get("status", {}).get("short")
                if status not in ["NS", "TBD", "PST", "CANC", "ABD", "AWD", "WO"]:
                    continue

                # Generate prediction
                prediction = self.ensemble_model.predict(fixture, historical_data)

                if prediction.get("status") == "success":
                    # Add fixture information
                    fixture_info = {
                        "fixture_id": fixture.get("fixture", {}).get("id"),
                        "date": fixture.get("fixture", {}).get("date"),
                        "league": fixture.get("league", {}).get("name"),
                        "home_team": fixture.get("teams", {}).get("home", {}).get("name"),
                        "away_team": fixture.get("teams", {}).get("away", {}).get("name")
                    }

                    # Combine fixture info with predictions
                    prediction_with_info = {
                        "fixture": fixture_info,
                        "predictions": prediction.get("predictions", [])
                    }

                    all_predictions.append(prediction_with_info)

            except Exception as e:
                logger.error(f"Error generating prediction for fixture {fixture.get('fixture', {}).get('id')}: {str(e)}")

        # Categorize predictions
        categorized_predictions = self._categorize_predictions(all_predictions)

        # Create result
        result = {
            "status": "success",
            "date": date,
            "predictions": all_predictions,
            "categories": categorized_predictions
        }

        # Cache the result
        cache_file = os.path.join(self.cache_dir, f"predictions_{date}.json")
        save_json_file(cache_file, result)

        return result

    def _get_historical_data(self) -> pd.DataFrame:
        """
        Get historical match data for feature engineering.

        Returns:
            DataFrame with historical match data
        """
        # Check if historical data is cached
        cache_file = os.path.join(self.cache_dir, "historical_data.csv")

        if os.path.exists(cache_file):
            # Check if cache is still valid (7 days)
            cache_time = datetime.fromtimestamp(os.path.getmtime(cache_file))
            if datetime.now() - cache_time < timedelta(days=7):
                try:
                    return pd.read_csv(cache_file)
                except Exception as e:
                    logger.warning(f"Error loading historical data cache: {str(e)}")

        # Get historical data from API
        # This would typically involve fetching data for multiple leagues and seasons
        # For simplicity, we'll just get the last 500 fixtures from the top 5 leagues
        leagues = [39, 140, 61, 78, 135]  # Premier League, La Liga, Ligue 1, Bundesliga, Serie A

        all_fixtures = []

        for league_id in leagues:
            try:
                fixtures_response = self.api_client.get_fixtures_improved(league=league_id, last=100)
                fixtures = fixtures_response.get("response", [])
                all_fixtures.extend(fixtures)
            except Exception as e:
                logger.error(f"Error getting historical data for league {league_id}: {str(e)}")

        # Convert to DataFrame
        if not all_fixtures:
            logger.warning("No historical data found")
            return pd.DataFrame()

        # Extract relevant data
        fixtures_data = []

        for fixture in all_fixtures:
            fixture_data = {
                "match_id": fixture.get("fixture", {}).get("id"),
                "date": fixture.get("fixture", {}).get("date"),
                "competition_name": fixture.get("league", {}).get("name"),
                "season": fixture.get("league", {}).get("season"),
                "home_team": fixture.get("teams", {}).get("home", {}).get("name"),
                "away_team": fixture.get("teams", {}).get("away", {}).get("name"),
                "home_score": fixture.get("goals", {}).get("home"),
                "away_score": fixture.get("goals", {}).get("away")
            }

            fixtures_data.append(fixture_data)

        df = pd.DataFrame(fixtures_data)

        # Save to cache
        try:
            df.to_csv(cache_file, index=False)
        except Exception as e:
            logger.warning(f"Error saving historical data cache: {str(e)}")

        return df

    def _categorize_predictions(self, predictions: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Categorize predictions by odds.

        Args:
            predictions: List of predictions

        Returns:
            Dictionary with categorized predictions
        """
        # Format predictions for the categorizer
        formatted_predictions = []

        for prediction in predictions:
            fixture = prediction.get("fixture", {})
            prediction_list = prediction.get("predictions", [])

            for pred in prediction_list:
                formatted_predictions.append({
                    "fixture": fixture,
                    "prediction": pred
                })

        # Use the prediction categorizer to generate optimized combinations
        categorized_predictions = prediction_categorizer.categorize_predictions(formatted_predictions)

        return categorized_predictions

    # The _generate_rollover_combinations method has been replaced by the prediction_categorizer

    def get_prediction_by_id(self, prediction_id: int):
        """Get a prediction by ID."""
        if not self.db:
            return None
        return self.db.query(Prediction).filter(Prediction.id == prediction_id).first()

    def get_prediction_by_fixture_id(self, fixture_id: int):
        """Get a prediction by fixture ID."""
        if not self.db:
            return None
        return self.db.query(Prediction).filter(Prediction.fixture_id == fixture_id).first()

    def get_predictions_by_date(self, date: datetime):
        """Get predictions by date."""
        if not self.db:
            return []
        start_date = datetime(date.year, date.month, date.day, 0, 0, 0)
        end_date = start_date + timedelta(days=1)
        return self.db.query(Prediction).join(Fixture).filter(
            Fixture.date >= start_date,
            Fixture.date < end_date
        ).all()
