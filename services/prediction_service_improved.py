"""
Prediction Service Module (Improved)

This module provides an improved service for generating football match predictions.
It uses the improved ensemble model and API client.
"""

import os
import uuid
import itertools
import pandas as pd
from typing import Dict, List, Any
from datetime import datetime, timedelta

from ml.ensemble_model_improved import improved_ensemble_model
from services.api_client import APIClient
from services.prediction_categorizer import prediction_categorizer
from utils.common import setup_logging, load_json_file, save_json_file
from utils.config import settings
from fixture import Fixture
from prediction import Prediction

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
        self.api_client = APIClient(
            base_url="https://api-football-v1.p.rapidapi.com/v3",
            headers={
                "x-rapidapi-host": "api-football-v1.p.rapidapi.com",
                "x-rapidapi-key": settings.api_football.API_KEY
            }
        )
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

    def categorize_predictions(self, predictions: List[Any]) -> Dict[str, List[Any]]:
        """
        Public method to categorize predictions.

        Args:
            predictions: List of prediction objects or dictionaries

        Returns:
            Dictionary with categorized predictions
        """
        # Convert prediction objects to dictionaries if needed
        formatted_predictions = []

        for pred in predictions:
            if hasattr(pred, 'to_dict'):
                # It's a prediction object
                pred_dict = pred.to_dict()
                formatted_predictions.append({
                    "fixture": {
                        "fixture_id": pred_dict.get("fixture_id"),
                        "home_team": pred_dict.get("homeTeam"),
                        "away_team": pred_dict.get("awayTeam"),
                        "date": pred_dict.get("date"),
                        "league": pred_dict.get("league")
                    },
                    "prediction": pred_dict
                })
            else:
                # It's already a dictionary
                formatted_predictions.append(pred)

        # Use the internal categorization method
        return self._categorize_predictions(formatted_predictions)

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

    def get_prediction_combinations_by_category(self, category: str, date: datetime, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get prediction combinations for a specific category from the database.

        Args:
            category: Category name (2_odds, 5_odds, 10_odds, rollover)
            date: Date to get combinations for
            limit: Maximum number of combinations to return

        Returns:
            List of prediction combinations
        """
        if not self.db:
            logger.warning("No database connection available")
            return []

        try:
            # Import here to avoid circular imports
            from prediction_combination import PredictionCombination

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

    def save_prediction_combinations(self, combinations: List[Dict[str, Any]], date: datetime) -> bool:
        """
        Save prediction combinations to the database.

        Args:
            combinations: List of prediction combinations
            date: Date of the combinations

        Returns:
            True if successful, False otherwise
        """
        if not self.db:
            logger.warning("No database connection available")
            return False

        try:
            # Import here to avoid circular imports
            from prediction_combination import PredictionCombination
            from prediction import Prediction

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
                    prediction_id = pred_dict.get("id")

                    if prediction_id:
                        # Get existing prediction
                        prediction = self.db.query(Prediction).filter(
                            Prediction.id == prediction_id
                        ).first()
                    else:
                        # Create new prediction
                        prediction = Prediction(
                            fixture_id=pred_dict.get("fixture_id"),
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
                            confidence=pred_dict.get("confidence"),
                            combo_id=combination.id
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

    # The _generate_rollover_combinations method has been replaced by the prediction_categorizer

    def create_prediction_combinations(self, predictions: List[Any], target_odds: float) -> List[Dict[str, Any]]:
        """
        Create combinations of predictions to reach target odds.

        Args:
            predictions: List of predictions
            target_odds: Target combined odds

        Returns:
            List of prediction combinations
        """
        if not predictions:
            return []

        # Sort by confidence (highest first)
        sorted_predictions = sorted(
            predictions,
            key=lambda p: p.confidence if hasattr(p, 'confidence') else p.get('confidence', 0),
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
                    # Handle both dictionary and object formats
                    if hasattr(pred, 'odds'):
                        odds = pred.odds or 1.0
                        confidence = pred.confidence or 0.0
                    else:
                        odds = pred.get('odds', 1.0)
                        confidence = pred.get('confidence', 0.0)

                    combined_odds *= odds
                    combined_confidence += confidence

                # Calculate average confidence
                avg_confidence = combined_confidence / len(combo) if combo else 0.0

                # Check if combined odds are close to target
                if combined_odds >= target_odds * 0.8 and combined_odds <= target_odds * 1.2:
                    # Convert predictions to dictionaries
                    pred_dicts = []
                    for pred in combo:
                        if hasattr(pred, 'to_dict'):
                            pred_dicts.append(pred.to_dict())
                        else:
                            pred_dicts.append(pred)

                    combinations.append({
                        "id": f"combo_{uuid.uuid4()}",
                        "predictions": pred_dicts,
                        "combined_odds": combined_odds,
                        "combined_confidence": avg_confidence
                    })

        # Sort by combined confidence (highest first)
        sorted_combinations = sorted(
            combinations,
            key=lambda x: x.get("combined_confidence", 0),
            reverse=True
        )

        return sorted_combinations

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
