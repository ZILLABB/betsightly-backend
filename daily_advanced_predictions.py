#!/usr/bin/env python3
"""
Daily Advanced Predictions Script

This script generates daily predictions using the advanced ML models.
It fetches fixtures from Football-Data.org API and uses the advanced models to generate predictions.
"""

import os
import sys
import argparse
import logging
import pandas as pd
import numpy as np
import json
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple, Union

# Add the parent directory to the path so we can import from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ml.model_factory import model_factory
from app.ml.advanced_feature_engineering import AdvancedFootballFeatureEngineer
from app.services.advanced_prediction_service import AdvancedPredictionService
from app.utils.common import setup_logging, ensure_directory_exists
from app.utils.config import settings

# Set up logging
logger = setup_logging(__name__)

# Constants
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "advanced")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")
PREDICTIONS_DIR = os.path.join(RESULTS_DIR, "predictions")
GITHUB_DATASET_URL = "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data-2000-2025/main/data/Matches.csv"
FOOTBALL_DATA_KEY = settings.football_data.API_KEY
FOOTBALL_DATA_BASE_URL = settings.football_data.BASE_URL

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Generate daily predictions using advanced ML models")
    
    parser.add_argument(
        "--date",
        type=str,
        help="Date in format YYYY-MM-DD (default: today)"
    )
    
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force update predictions even if they already exist"
    )
    
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save predictions to file"
    )
    
    parser.add_argument(
        "--competitions",
        type=str,
        default="PL,PD,SA,BL1,FL1",
        help="Comma-separated list of competition codes (default: PL,PD,SA,BL1,FL1)"
    )
    
    return parser.parse_args()

def load_github_dataset():
    """
    Load the cached GitHub football dataset.

    Returns:
        DataFrame with football data
    """
    # Build cache path
    cache_dir = os.path.join(DATA_DIR, "github-football")
    cache_file = os.path.join(cache_dir, "Matches.csv")

    # Check if cache exists
    if os.path.exists(cache_file):
        logger.info(f"Loading cached GitHub dataset from {cache_file}")
        return pd.read_csv(cache_file, low_memory=False)
    else:
        logger.error(f"GitHub dataset not found at {cache_file}. Please run train_advanced_ml_models.py first.")
        return pd.DataFrame()

def fetch_fixtures(date_str: str, competitions: List[str], force: bool = False) -> List[Dict[str, Any]]:
    """
    Fetch fixtures from Football-Data.org API.

    Args:
        date_str: Date in format YYYY-MM-DD
        competitions: List of competition codes
        force: Force update fixtures even if they already exist

    Returns:
        List of fixtures
    """
    # Build cache path
    cache_dir = os.path.join(DATA_DIR, "fixtures")
    ensure_directory_exists(cache_dir)
    cache_file = os.path.join(cache_dir, f"fixtures_{date_str}.json")

    # Check if cache exists
    if os.path.exists(cache_file) and not force:
        logger.info(f"Loading cached fixtures from {cache_file}")
        with open(cache_file, "r") as f:
            return json.load(f)

    # Fetch fixtures from API
    all_fixtures = []

    for competition in competitions:
        try:
            logger.info(f"Fetching fixtures for competition {competition}")

            # Build API URL
            url = f"{FOOTBALL_DATA_BASE_URL}/competitions/{competition}/matches"
            params = {
                "dateFrom": date_str,
                "dateTo": date_str
            }
            headers = {
                "X-Auth-Token": FOOTBALL_DATA_KEY
            }

            # Make request
            response = requests.get(url, params=params, headers=headers)

            if response.status_code != 200:
                logger.error(f"Error fetching fixtures: {response.status_code}")
                continue

            # Parse response
            data = response.json()

            # Add fixtures to list
            fixtures = data.get("matches", [])
            logger.info(f"Found {len(fixtures)} fixtures for competition {competition}")

            all_fixtures.extend(fixtures)

        except Exception as e:
            logger.error(f"Error fetching fixtures for competition {competition}: {str(e)}")

    # Save fixtures to cache
    if all_fixtures:
        logger.info(f"Saving {len(all_fixtures)} fixtures to cache: {cache_file}")
        with open(cache_file, "w") as f:
            json.dump(all_fixtures, f, indent=2)
    else:
        logger.warning(f"No fixtures found for {date_str}")

    return all_fixtures

def format_fixture_for_prediction(fixture: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format fixture for prediction.

    Args:
        fixture: Fixture data from Football-Data.org API

    Returns:
        Formatted fixture for prediction
    """
    return {
        "fixture": {
            "id": fixture.get("id"),
            "date": fixture.get("utcDate")
        },
        "teams": {
            "home": {
                "name": fixture.get("homeTeam", {}).get("name")
            },
            "away": {
                "name": fixture.get("awayTeam", {}).get("name")
            }
        },
        "league": {
            "name": fixture.get("competition", {}).get("name")
        }
    }

def generate_predictions(fixtures: List[Dict[str, Any]], historical_data: pd.DataFrame) -> Dict[str, Any]:
    """
    Generate predictions for fixtures.

    Args:
        fixtures: List of fixtures
        historical_data: Historical data for feature engineering

    Returns:
        Dictionary with predictions
    """
    try:
        # Initialize advanced prediction service
        prediction_service = AdvancedPredictionService()
        
        # Initialize feature engineer with historical data
        feature_engineer = AdvancedFootballFeatureEngineer()
        feature_engineer.set_historical_data(historical_data)
        
        # Generate predictions for each fixture
        all_predictions = []
        
        for fixture in fixtures:
            try:
                # Format fixture for prediction
                formatted_fixture = format_fixture_for_prediction(fixture)
                
                # Engineer features
                features = feature_engineer.engineer_features(formatted_fixture)
                
                if features.empty:
                    logger.warning(f"Failed to engineer features for fixture {fixture.get('id')}")
                    continue
                
                # Generate predictions using different models
                fixture_predictions = []
                
                # Match result prediction using XGBoost
                match_result_pred = model_factory.predict("xgboost_match_result", features)
                
                if match_result_pred.get("status") == "success":
                    prediction = {
                        "fixture_id": fixture.get("id"),
                        "home_team": fixture.get("homeTeam", {}).get("name"),
                        "away_team": fixture.get("awayTeam", {}).get("name"),
                        "competition": fixture.get("competition", {}).get("name"),
                        "date": fixture.get("utcDate"),
                        "prediction_type": "match_result",
                        "prediction": match_result_pred["predictions"][0],
                        "confidence": match_result_pred["confidence"][0],
                        "uncertainty": match_result_pred.get("uncertainty", [10])[0],
                        "odds": calculate_odds(match_result_pred["confidence"][0] / 100)
                    }
                    
                    fixture_predictions.append(prediction)
                
                # Over/Under prediction using Neural Network
                over_under_pred = model_factory.predict("nn_over_under_2_5", features)
                
                if over_under_pred.get("status") == "success":
                    prediction = {
                        "fixture_id": fixture.get("id"),
                        "home_team": fixture.get("homeTeam", {}).get("name"),
                        "away_team": fixture.get("awayTeam", {}).get("name"),
                        "competition": fixture.get("competition", {}).get("name"),
                        "date": fixture.get("utcDate"),
                        "prediction_type": "over_under_2_5",
                        "prediction": "Over" if over_under_pred["predictions"][0] == 1 else "Under",
                        "confidence": over_under_pred["confidence"][0],
                        "uncertainty": over_under_pred.get("uncertainty", [10])[0],
                        "odds": calculate_odds(over_under_pred["confidence"][0] / 100)
                    }
                    
                    fixture_predictions.append(prediction)
                
                # BTTS prediction using LightGBM
                btts_pred = model_factory.predict("lightgbm_btts", features)
                
                if btts_pred.get("status") == "success":
                    prediction = {
                        "fixture_id": fixture.get("id"),
                        "home_team": fixture.get("homeTeam", {}).get("name"),
                        "away_team": fixture.get("awayTeam", {}).get("name"),
                        "competition": fixture.get("competition", {}).get("name"),
                        "date": fixture.get("utcDate"),
                        "prediction_type": "btts",
                        "prediction": "Yes" if btts_pred["predictions"][0] == 1 else "No",
                        "confidence": btts_pred["confidence"][0],
                        "uncertainty": btts_pred.get("uncertainty", [10])[0],
                        "odds": calculate_odds(btts_pred["confidence"][0] / 100)
                    }
                    
                    fixture_predictions.append(prediction)
                
                # Add fixture predictions to all predictions
                if fixture_predictions:
                    all_predictions.append({
                        "fixture": {
                            "id": fixture.get("id"),
                            "home_team": fixture.get("homeTeam", {}).get("name"),
                            "away_team": fixture.get("awayTeam", {}).get("name"),
                            "competition": fixture.get("competition", {}).get("name"),
                            "date": fixture.get("utcDate"),
                            "status": fixture.get("status")
                        },
                        "predictions": fixture_predictions
                    })
            
            except Exception as e:
                logger.error(f"Error generating predictions for fixture {fixture.get('id')}: {str(e)}")
        
        # Categorize predictions by odds
        categorized_predictions = categorize_predictions(all_predictions)
        
        return {
            "status": "success",
            "predictions": all_predictions,
            "categories": categorized_predictions
        }
        
    except Exception as e:
        logger.error(f"Error generating predictions: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }

def calculate_odds(probability: float) -> float:
    """
    Calculate odds based on probability.

    Args:
        probability: Probability (0-1)

    Returns:
        Odds value
    """
    # Add a small margin for the bookmaker
    margin = 0.1
    adjusted_probability = probability - margin
    
    # Ensure probability is between 0.1 and 0.9
    adjusted_probability = max(0.1, min(0.9, adjusted_probability))
    
    # Calculate odds: 1 / probability
    odds = 1.0 / adjusted_probability
    
    # Round to 2 decimal places
    return round(odds, 2)

def categorize_predictions(predictions: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Categorize predictions by odds.

    Args:
        predictions: List of predictions

    Returns:
        Dictionary with categorized predictions
    """
    try:
        # Initialize categories
        categories = {
            "odds_2": [],
            "odds_5": [],
            "odds_10": [],
            "rollover": []
        }
        
        # Flatten predictions
        flat_predictions = []
        
        for fixture_prediction in predictions:
            fixture = fixture_prediction.get("fixture", {})
            
            for prediction in fixture_prediction.get("predictions", []):
                flat_predictions.append({
                    "fixture": fixture,
                    "prediction": prediction
                })
        
        # Sort predictions by confidence (descending)
        flat_predictions.sort(key=lambda x: x["prediction"]["confidence"], reverse=True)
        
        # Select best predictions for each category
        for category, target_odds in [("odds_2", 2.0), ("odds_5", 5.0), ("odds_10", 10.0)]:
            # Find combinations of predictions that reach the target odds
            selected_predictions = select_predictions_for_odds(flat_predictions, target_odds)
            
            if selected_predictions:
                categories[category] = selected_predictions
        
        # Generate rollover predictions
        categories["rollover"] = generate_rollover_predictions(flat_predictions)
        
        return categories
        
    except Exception as e:
        logger.error(f"Error categorizing predictions: {str(e)}")
        return {}

def select_predictions_for_odds(predictions: List[Dict[str, Any]], target_odds: float) -> List[Dict[str, Any]]:
    """
    Select predictions to reach target odds.

    Args:
        predictions: List of predictions
        target_odds: Target odds value

    Returns:
        List of selected predictions
    """
    try:
        # Sort predictions by confidence (descending)
        sorted_predictions = sorted(predictions, key=lambda x: x["prediction"]["confidence"], reverse=True)
        
        # Initialize selected predictions
        selected_predictions = []
        current_odds = 1.0
        
        # Select predictions until target odds is reached
        for prediction in sorted_predictions:
            # Skip if prediction is already selected
            if any(p["fixture"]["id"] == prediction["fixture"]["id"] for p in selected_predictions):
                continue
            
            # Calculate new odds
            new_odds = current_odds * prediction["prediction"]["odds"]
            
            # If new odds exceed target, check if it's closer to target than current odds
            if new_odds > target_odds:
                if abs(new_odds - target_odds) < abs(current_odds - target_odds) and len(selected_predictions) < 3:
                    selected_predictions.append(prediction)
                    current_odds = new_odds
                continue
            
            # Add prediction to selected
            selected_predictions.append(prediction)
            current_odds = new_odds
            
            # If target odds reached, stop
            if current_odds >= target_odds:
                break
        
        return selected_predictions
        
    except Exception as e:
        logger.error(f"Error selecting predictions for odds: {str(e)}")
        return []

def generate_rollover_predictions(predictions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Generate rollover predictions.

    Args:
        predictions: List of predictions

    Returns:
        List of rollover predictions
    """
    try:
        # Sort predictions by confidence (descending)
        sorted_predictions = sorted(predictions, key=lambda x: x["prediction"]["confidence"], reverse=True)
        
        # Initialize rollover predictions
        rollover_predictions = []
        
        # Select top 10 predictions for rollover
        for i, prediction in enumerate(sorted_predictions[:10]):
            # Add rollover day
            prediction_with_rollover = prediction.copy()
            prediction_with_rollover["rollover_day"] = i + 1
            
            rollover_predictions.append(prediction_with_rollover)
        
        return rollover_predictions
        
    except Exception as e:
        logger.error(f"Error generating rollover predictions: {str(e)}")
        return []

def main():
    """Main function."""
    # Parse arguments
    args = parse_arguments()
    
    # Set date
    if args.date:
        date_str = args.date
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    # Ensure directories exist
    ensure_directory_exists(DATA_DIR)
    ensure_directory_exists(MODELS_DIR)
    ensure_directory_exists(RESULTS_DIR)
    ensure_directory_exists(PREDICTIONS_DIR)
    
    # Load historical data
    historical_data = load_github_dataset()
    
    if historical_data.empty:
        logger.error("Failed to load historical data")
        return
    
    # Fetch fixtures
    competitions = args.competitions.split(',')
    fixtures = fetch_fixtures(date_str, competitions, args.force)
    
    if not fixtures:
        logger.warning(f"No fixtures found for {date_str}")
        return
    
    # Generate predictions
    predictions = generate_predictions(fixtures, historical_data)
    
    if predictions.get("status") != "success":
        logger.error(f"Error generating predictions: {predictions.get('message')}")
        return
    
    # Save predictions if requested
    if args.save:
        predictions_file = os.path.join(PREDICTIONS_DIR, f"predictions_{date_str}.json")
        
        with open(predictions_file, "w") as f:
            json.dump(predictions, f, indent=2)
        
        logger.info(f"Predictions saved to {predictions_file}")
    
    # Print summary
    print(f"Generated predictions for {len(predictions.get('predictions', []))} fixtures on {date_str}")
    print(f"Categories:")
    for category, category_predictions in predictions.get("categories", {}).items():
        print(f"  {category}: {len(category_predictions)} predictions")
    
    logger.info("Prediction generation complete")

if __name__ == "__main__":
    main()
