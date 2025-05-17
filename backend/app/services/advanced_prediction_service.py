"""
Advanced Prediction Service Module

This module provides an advanced service for generating football match predictions.
It uses the more sophisticated ML models (XGBoost, LightGBM, Neural Networks, LSTM)
instead of the basic ensemble models.
"""

import os
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional, Tuple, Union
from datetime import datetime, timedelta

from app.ml.model_factory import model_factory
from app.services.api_client import APIClient
from app.services.prediction_categorizer import prediction_categorizer
from app.utils.common import setup_logging, load_json_file, save_json_file
from app.utils.config import settings
from app.models.fixture import Fixture
from app.models.prediction import Prediction

# Set up logging
logger = setup_logging(__name__)

# Import advanced feature engineering
try:
    from app.ml.advanced_feature_engineering import AdvancedFootballFeatureEngineer
    has_advanced_features = True
except ImportError:
    logger.warning("Advanced feature engineering not available, using basic features")
    has_advanced_features = False

class AdvancedPredictionService:
    """
    Service for generating football match predictions using advanced ML models.

    Features:
    - Uses advanced ML models (XGBoost, LightGBM, Neural Networks, LSTM)
    - Fetches fixtures from Football-Data.org API
    - Generates predictions with calibrated confidence scores
    - Categorizes predictions by odds
    - Generates rollover predictions
    """

    def __init__(self, db=None):
        """Initialize the prediction service."""
        # Initialize model factory
        self.model_factory = model_factory

        # Initialize API client for Football-Data.org
        self.api_client = APIClient(
            base_url="https://api.football-data.org/v4",
            headers={"X-Auth-Token": settings.FOOTBALL_DATA_KEY}
        )

        self.db = db

        # Ensure cache directory exists
        self.cache_dir = os.path.join(settings.ml.CACHE_DIR, "predictions")
        os.makedirs(self.cache_dir, exist_ok=True)

        # Define which advanced models to use for each prediction type
        self.model_mapping = {
            "match_result": "xgboost_match_result",  # Use XGBoost for match results
            "over_under": "nn_over_under_2_5",       # Use Neural Network for over/under
            "btts": "lightgbm_btts"                  # Use LightGBM for BTTS
        }

        # Initialize advanced feature engineering if available
        self.feature_engineer = None
        if has_advanced_features:
            try:
                self.feature_engineer = AdvancedFootballFeatureEngineer()
                logger.info("Advanced feature engineering initialized")

                # Initialize with historical data if available
                self._initialize_feature_engineer()
            except Exception as e:
                logger.error(f"Error initializing advanced feature engineering: {str(e)}")

    def _initialize_feature_engineer(self):
        """Initialize the feature engineer with historical data."""
        try:
            # Get historical data
            historical_data = self._get_historical_data()

            if not historical_data.empty:
                # Set historical data for feature engineering
                self.feature_engineer.set_historical_data(historical_data)
                logger.info(f"Feature engineer initialized with {len(historical_data)} historical matches")
            else:
                logger.warning("No historical data available for feature engineering")

        except Exception as e:
            logger.error(f"Error initializing feature engineer: {str(e)}")

    def get_predictions_for_date(self, date: str, force_update: bool = False) -> Dict[str, Any]:
        """
        Get predictions for fixtures on a specific date using advanced ML models.

        Args:
            date: Date in format YYYY-MM-DD
            force_update: Whether to force an update from the API

        Returns:
            Dictionary with predictions
        """
        # Check cache if not forcing update
        if not force_update:
            cache_file = os.path.join(self.cache_dir, f"advanced_predictions_{date}.json")
            cached_predictions = load_json_file(cache_file)

            if cached_predictions:
                logger.info(f"Using cached advanced predictions for {date}")
                return cached_predictions

        # Get fixtures for the date from Football-Data.org
        fixtures = self._get_fixtures_for_date(date)

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
                # Generate prediction using advanced models
                prediction = self._generate_prediction(fixture, historical_data)

                if prediction.get("status") == "success":
                    # Add fixture information
                    fixture_info = self._extract_fixture_info(fixture)

                    # Combine fixture info with predictions
                    prediction_with_info = {
                        "fixture": fixture_info,
                        "predictions": prediction.get("predictions", [])
                    }

                    all_predictions.append(prediction_with_info)

            except Exception as e:
                fixture_id = fixture.get("id", "unknown")
                logger.error(f"Error generating prediction for fixture {fixture_id}: {str(e)}")

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
        cache_file = os.path.join(self.cache_dir, f"advanced_predictions_{date}.json")
        save_json_file(cache_file, result)

        return result

    def _get_fixtures_for_date(self, date: str) -> List[Dict[str, Any]]:
        """
        Get fixtures for a specific date from Football-Data.org API.

        Args:
            date: Date in format YYYY-MM-DD

        Returns:
            List of fixtures
        """
        try:
            # Check if fixtures are already in the database
            if self.db:
                fixtures = self.db.get_fixtures_by_date(date)
                if fixtures:
                    logger.info(f"Using fixtures from database for {date}")
                    return fixtures

            # Fetch fixtures from Football-Data.org API
            response = self.api_client.get(f"/matches?date={date}")

            if response.get("status") == "error":
                logger.error(f"Error getting fixtures: {response.get('message')}")
                return []

            matches = response.get("matches", [])

            # Store fixtures in database for future use
            if self.db and matches:
                self.db.save_fixtures(matches, date)

            return matches

        except Exception as e:
            logger.error(f"Error fetching fixtures for {date}: {str(e)}")
            return []

    def _generate_prediction(self, fixture: Dict[str, Any], historical_data: pd.DataFrame) -> Dict[str, Any]:
        """
        Generate predictions for a fixture using advanced ML models.

        Args:
            fixture: Fixture data
            historical_data: Historical data for feature engineering

        Returns:
            Dictionary with predictions
        """
        try:
            # Extract teams
            home_team = fixture.get("homeTeam", {}).get("name", "")
            away_team = fixture.get("awayTeam", {}).get("name", "")

            if not home_team or not away_team:
                logger.warning(f"Missing team information for fixture {fixture.get('id', 'unknown')}")
                return {"status": "error", "message": "Missing team information"}

            # Create features for prediction
            features = self._create_features(fixture, historical_data)

            # Generate predictions using advanced models
            predictions = []

            # Match result prediction using XGBoost
            match_result_pred = self.model_factory.predict(
                self.model_mapping["match_result"],
                features
            )

            if match_result_pred.get("status") == "success":
                # Get uncertainty value if available, otherwise use a default
                uncertainty = match_result_pred.get("uncertainty", [10])[0]

                # Add prediction with uncertainty
                predictions.append({
                    "prediction_type": "Match Result",
                    "prediction": match_result_pred["predictions"][0],
                    "confidence": match_result_pred["confidence"][0],
                    "uncertainty": uncertainty,
                    "explanation": self._get_explanation(
                        "match_result",
                        match_result_pred["predictions"][0],
                        match_result_pred["confidence"][0],
                        home_team,
                        away_team,
                        uncertainty
                    )
                })

            # Over/Under prediction using Neural Network
            over_under_pred = self.model_factory.predict(
                self.model_mapping["over_under"],
                features
            )

            if over_under_pred.get("status") == "success":
                # Get uncertainty value if available, otherwise use a default
                uncertainty = over_under_pred.get("uncertainty", [10])[0]

                predictions.append({
                    "prediction_type": "Over/Under 2.5",
                    "prediction": "Over" if over_under_pred["predictions"][0] == 1 else "Under",
                    "confidence": over_under_pred["confidence"][0],
                    "uncertainty": uncertainty,
                    "explanation": self._get_explanation(
                        "over_under",
                        over_under_pred["predictions"][0],
                        over_under_pred["confidence"][0],
                        home_team,
                        away_team,
                        uncertainty
                    )
                })

            # BTTS prediction using LightGBM
            btts_pred = self.model_factory.predict(
                self.model_mapping["btts"],
                features
            )

            if btts_pred.get("status") == "success":
                # Get uncertainty value if available, otherwise use a default
                uncertainty = btts_pred.get("uncertainty", [10])[0]

                predictions.append({
                    "prediction_type": "Both Teams To Score",
                    "prediction": "Yes" if btts_pred["predictions"][0] == 1 else "No",
                    "confidence": btts_pred["confidence"][0],
                    "uncertainty": uncertainty,
                    "explanation": self._get_explanation(
                        "btts",
                        btts_pred["predictions"][0],
                        btts_pred["confidence"][0],
                        home_team,
                        away_team,
                        uncertainty
                    )
                })

            return {
                "status": "success",
                "predictions": predictions
            }

        except Exception as e:
            logger.error(f"Error generating prediction: {str(e)}")
            return {"status": "error", "message": str(e)}

    def _create_features(self, fixture: Dict[str, Any], historical_data: pd.DataFrame) -> pd.DataFrame:
        """
        Create features for prediction from fixture data and historical data.

        Args:
            fixture: Fixture data
            historical_data: Historical data for feature engineering

        Returns:
            DataFrame with features for prediction
        """
        # Try to use advanced feature engineering if available
        if self.feature_engineer is not None:
            try:
                # Format fixture data for the feature engineer
                formatted_fixture = {
                    "fixture": {
                        "id": fixture.get("id", "unknown"),
                        "date": fixture.get("utcDate", datetime.now().isoformat())
                    },
                    "teams": {
                        "home": {"name": fixture.get("homeTeam", {}).get("name", "unknown")},
                        "away": {"name": fixture.get("awayTeam", {}).get("name", "unknown")}
                    }
                }

                # Engineer features
                advanced_features = self.feature_engineer.engineer_features(formatted_fixture)

                if not advanced_features.empty:
                    logger.info(f"Using advanced feature engineering for fixture {fixture.get('id', 'unknown')}")
                    return advanced_features
                else:
                    logger.warning(f"Advanced feature engineering failed, falling back to basic features")
            except Exception as e:
                logger.error(f"Error using advanced feature engineering: {str(e)}")

        # Fall back to basic feature engineering
        logger.info(f"Using basic feature engineering for fixture {fixture.get('id', 'unknown')}")

        # Extract teams
        home_team = fixture.get("homeTeam", {}).get("name", "")
        away_team = fixture.get("awayTeam", {}).get("name", "")

        # Create basic features
        features = pd.DataFrame({
            "home_team": [home_team],
            "away_team": [away_team],
        })

        # Add team form features
        home_form, away_form = self._calculate_team_form(home_team, away_team, historical_data)
        features["home_form"] = [home_form]
        features["away_form"] = [away_form]

        # Add attack and defense strength
        home_attack, home_defense = self._calculate_team_strength(home_team, historical_data, "attack")
        away_attack, away_defense = self._calculate_team_strength(away_team, historical_data, "defense")
        features["home_attack"] = [home_attack]
        features["home_defense"] = [home_defense]
        features["away_attack"] = [away_attack]
        features["away_defense"] = [away_defense]

        # Add head-to-head features
        h2h_home_wins, h2h_away_wins, h2h_draws = self._calculate_h2h_stats(home_team, away_team, historical_data)
        features["h2h_home_wins"] = [h2h_home_wins]
        features["h2h_away_wins"] = [h2h_away_wins]
        features["h2h_draws"] = [h2h_draws]

        # Add league position difference
        league_position_diff = self._calculate_league_position_diff(home_team, away_team, historical_data)
        features["league_position_diff"] = [league_position_diff]

        # Add any additional features needed by the advanced models
        features["recent_goals_scored_home"] = [self._calculate_recent_goals(home_team, historical_data, "scored")]
        features["recent_goals_conceded_home"] = [self._calculate_recent_goals(home_team, historical_data, "conceded")]
        features["recent_goals_scored_away"] = [self._calculate_recent_goals(away_team, historical_data, "scored")]
        features["recent_goals_conceded_away"] = [self._calculate_recent_goals(away_team, historical_data, "conceded")]

        # Add match importance features (e.g., derby, cup final)
        features["is_derby"] = [self._is_derby(home_team, away_team)]
        features["is_important_match"] = [self._is_important_match(fixture)]

        return features

    def _calculate_team_form(self, home_team: str, away_team: str, historical_data: pd.DataFrame) -> Tuple[float, float]:
        """
        Calculate team form based on recent matches.

        Args:
            home_team: Home team name
            away_team: Away team name
            historical_data: Historical match data

        Returns:
            Tuple of (home_form, away_form) as float values between 0 and 1
        """
        # In a real implementation, this would analyze recent match results
        # For now, return default values if historical data is not available
        if historical_data.empty:
            return 0.5, 0.5

        # Default implementation - can be enhanced with actual historical data
        return 0.6, 0.5

    def _calculate_team_strength(self, team: str, historical_data: pd.DataFrame, strength_type: str) -> Tuple[float, float]:
        """
        Calculate team attack and defense strength.

        Args:
            team: Team name
            historical_data: Historical match data
            strength_type: Type of strength to calculate ('attack' or 'defense')

        Returns:
            Tuple of (attack_strength, defense_strength) as float values between 0 and 1
        """
        # In a real implementation, this would analyze goals scored/conceded
        # For now, return default values if historical data is not available
        if historical_data.empty:
            return 0.5, 0.5

        # Default implementation - can be enhanced with actual historical data
        return 0.6, 0.6

    def _calculate_h2h_stats(self, home_team: str, away_team: str, historical_data: pd.DataFrame) -> Tuple[float, float, float]:
        """
        Calculate head-to-head statistics between two teams.

        Args:
            home_team: Home team name
            away_team: Away team name
            historical_data: Historical match data

        Returns:
            Tuple of (home_wins, away_wins, draws) as proportions
        """
        # In a real implementation, this would analyze previous matches between these teams
        # For now, return default values if historical data is not available
        if historical_data.empty:
            return 0.4, 0.3, 0.3

        # Default implementation - can be enhanced with actual historical data
        return 0.4, 0.3, 0.3

    def _calculate_league_position_diff(self, home_team: str, away_team: str, historical_data: pd.DataFrame) -> float:
        """
        Calculate the difference in league positions between two teams.

        Args:
            home_team: Home team name
            away_team: Away team name
            historical_data: Historical match data

        Returns:
            Normalized difference in league positions (0-1 scale)
        """
        # In a real implementation, this would look up current league positions
        # For now, return a default value
        return 0.2

    def _calculate_recent_goals(self, team: str, historical_data: pd.DataFrame, goal_type: str) -> float:
        """
        Calculate the average number of goals scored or conceded by a team in recent matches.

        Args:
            team: Team name
            historical_data: Historical match data
            goal_type: Type of goals to calculate ('scored' or 'conceded')

        Returns:
            Average number of goals, normalized to 0-1 scale
        """
        # In a real implementation, this would calculate actual goal averages
        # For now, return default values
        if goal_type == "scored":
            return 0.6
        else:  # conceded
            return 0.4

    def _is_derby(self, home_team: str, away_team: str) -> float:
        """
        Determine if a match is a derby (rivalry match).

        Args:
            home_team: Home team name
            away_team: Away team name

        Returns:
            1.0 if derby, 0.0 if not (or a probability between 0-1)
        """
        # In a real implementation, this would check a database of rivalries
        # For now, return a default value
        return 0.0

    def _is_important_match(self, fixture: Dict[str, Any]) -> float:
        """
        Determine if a match is important (e.g., cup final, relegation battle).

        Args:
            fixture: Fixture data

        Returns:
            Importance score between 0-1
        """
        # In a real implementation, this would analyze competition stage, league positions, etc.
        # For now, return a default value
        return 0.5

    def _extract_fixture_info(self, fixture: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract relevant information from a fixture.

        Args:
            fixture: Fixture data

        Returns:
            Dictionary with fixture information
        """
        return {
            "fixture_id": fixture.get("id"),
            "date": fixture.get("utcDate"),
            "competition": fixture.get("competition", {}).get("name"),
            "home_team": fixture.get("homeTeam", {}).get("name"),
            "away_team": fixture.get("awayTeam", {}).get("name"),
            "home_team_logo": fixture.get("homeTeam", {}).get("crest"),
            "away_team_logo": fixture.get("awayTeam", {}).get("crest"),
            "status": fixture.get("status")
        }

    def _get_explanation(self, prediction_type: str, prediction: Any, confidence: float, home_team: str, away_team: str, uncertainty: float = None) -> str:
        """
        Generate an explanation for a prediction.

        Args:
            prediction_type: Type of prediction ('match_result', 'over_under', 'btts')
            prediction: Prediction value
            confidence: Confidence score
            home_team: Home team name
            away_team: Away team name
            uncertainty: Uncertainty value (optional)

        Returns:
            Explanation string
        """
        # Base explanation without uncertainty
        if prediction_type == "match_result":
            if prediction == "H":
                base_explanation = f"{home_team} is predicted to win with {confidence:.1f}% confidence"
            elif prediction == "A":
                base_explanation = f"{away_team} is predicted to win with {confidence:.1f}% confidence"
            else:
                base_explanation = f"A draw is predicted with {confidence:.1f}% confidence"
        elif prediction_type == "over_under":
            if prediction == "Over" or prediction == 1:
                base_explanation = f"Over 2.5 goals predicted with {confidence:.1f}% confidence"
            else:
                base_explanation = f"Under 2.5 goals predicted with {confidence:.1f}% confidence"
        elif prediction_type == "btts":
            if prediction == "Yes" or prediction == 1:
                base_explanation = f"Both teams to score: Yes with {confidence:.1f}% confidence"
            else:
                base_explanation = f"Both teams to score: No with {confidence:.1f}% confidence"
        else:
            base_explanation = f"Prediction with {confidence:.1f}% confidence"

        # Add uncertainty information if available
        if uncertainty is not None:
            # Categorize uncertainty
            if uncertainty < 10:
                uncertainty_level = "very low"
            elif uncertainty < 20:
                uncertainty_level = "low"
            elif uncertainty < 30:
                uncertainty_level = "moderate"
            elif uncertainty < 40:
                uncertainty_level = "high"
            else:
                uncertainty_level = "very high"

            # Add uncertainty to explanation
            return f"{base_explanation} (with {uncertainty_level} uncertainty of ±{uncertainty:.1f}%)"

        return base_explanation

    def _get_historical_data(self) -> pd.DataFrame:
        """
        Get historical data for feature engineering.

        Returns:
            DataFrame with historical match data
        """
        # In a real implementation, this would fetch data from a database or API
        # For now, return an empty DataFrame
        return pd.DataFrame()

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
