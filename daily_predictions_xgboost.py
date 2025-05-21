#!/usr/bin/env python3
"""
Daily Football Predictions with XGBoost Models

This script runs daily predictions using the XGBoost models.
It handles the entire pipeline from data fetching to prediction generation.
"""

import os
import sys
import pandas as pd
import numpy as np
import requests
import logging
import joblib
from datetime import datetime, timedelta
import argparse
import time
import traceback
import uuid

# Add parent directory to path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(backend_dir)
os.chdir(backend_dir)  # Change to backend directory to ensure .env is found

# Import settings module
from app.utils.config import settings, FOOTBALL_DATA_KEY, FOOTBALL_DATA_BASE_URL
from app.services.api_client import FootballDataClient
from app.database import SessionLocal
from app.models.fixture import Fixture
from app.models.prediction import Prediction

# Set up logging
log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
os.makedirs(log_dir, exist_ok=True)

# Use current date for log file name
today = datetime.now()
# The year is correctly 2025
log_file = os.path.join(log_dir, f"xgboost_predictions_{today.strftime('%Y-%m-%d')}.log")

# Configure logging with correct date format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "xgboost")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")
GITHUB_DATASET_URL = "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data-2000-2025/main/data/Matches.csv"

# Initialize Football-Data.org client
football_data_client = FootballDataClient(api_key=FOOTBALL_DATA_KEY, base_url=FOOTBALL_DATA_BASE_URL)

# Competition IDs for major leagues
COMPETITIONS = {
    "PL": "Premier League (England)",
    "PD": "La Liga (Spain)",
    "SA": "Serie A (Italy)",
    "BL1": "Bundesliga (Germany)",
    "FL1": "Ligue 1 (France)",
    "CL": "Champions League",
    "EC": "European Championship",
    "WC": "World Cup"
}

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Run daily football predictions with XGBoost models")

    # Always use today's date by default but ensure correct year (2024)
    today = datetime.now()
    correct_date = today.replace(year=2024)
    date_str = correct_date.strftime("%Y-%m-%d")

    parser.add_argument(
        "--date",
        type=str,
        default=date_str,
        help=f"Date for predictions (YYYY-MM-DD), defaults to today ({date_str})"
    )

    parser.add_argument(
        "--competitions",
        type=str,
        default="PL,PD,SA,BL1,FL1",
        help="Comma-separated list of competition codes (e.g., PL,PD,SA,BL1,FL1)"
    )

    parser.add_argument(
        "--output",
        type=str,
        default=os.path.join(RESULTS_DIR, f"xgboost_predictions_{datetime.now().strftime('%Y-%m-%d')}.csv"),
        help="Output file path"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force fetching fixtures from API even if cached"
    )

    parser.add_argument(
        "--save-to-db",
        action="store_true",
        help="Save predictions to database"
    )

    return parser.parse_args()

def ensure_directory_exists(directory):
    """Ensure a directory exists."""
    os.makedirs(directory, exist_ok=True)

def load_github_dataset():
    """
    Load the cached GitHub football dataset.

    Returns:
        DataFrame with football data
    """
    # Build cache path
    cache_dir = os.path.join(DATA_DIR, "github-football")
    ensure_directory_exists(cache_dir)
    cache_file = os.path.join(cache_dir, "Matches.csv")

    # Check if cache exists
    if os.path.exists(cache_file):
        logger.info(f"Loading cached GitHub dataset from {cache_file}")
        return pd.read_csv(cache_file, low_memory=False)

    # Download data
    try:
        logger.info(f"Downloading GitHub football dataset...")
        response = requests.get(GITHUB_DATASET_URL)

        if response.status_code != 200:
            logger.error(f"Error downloading dataset: {response.status_code}")
            return pd.DataFrame()

        # Save to cache
        with open(cache_file, "wb") as f:
            f.write(response.content)

        # Read data
        df = pd.read_csv(cache_file, low_memory=False)

        logger.info(f"Downloaded {len(df)} matches from GitHub")
        return df

    except Exception as e:
        logger.error(f"Error downloading dataset: {str(e)}")
        return pd.DataFrame()

def fetch_fixtures_from_api(date_str, competitions=None, force=False):
    """
    Fetch fixtures from Football-Data.org.

    Args:
        date_str: Date string in YYYY-MM-DD format
        competitions: Comma-separated list of competition codes (e.g., "PL,PD,SA")
        force: Force fetching from API even if cached

    Returns:
        DataFrame with fixtures data
    """
    # Build cache path
    cache_dir = os.path.join(DATA_DIR, "fixtures")
    ensure_directory_exists(cache_dir)
    cache_file = os.path.join(cache_dir, f"fixtures_{date_str}.csv")

    # Check if cache exists and not forcing refresh
    if os.path.exists(cache_file) and not force:
        logger.info(f"Loading cached fixtures from {cache_file}")
        return pd.read_csv(cache_file)

    # Check database for fixtures
    try:
        db = SessionLocal()
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        start_date = datetime(date_obj.year, date_obj.month, date_obj.day, 0, 0, 0)
        end_date = start_date + timedelta(days=1)

        fixtures = db.query(Fixture).filter(
            Fixture.date >= start_date,
            Fixture.date < end_date
        ).all()

        if fixtures and not force:
            logger.info(f"Found {len(fixtures)} fixtures in database for {date_str}")
            fixtures_data = []

            for fixture in fixtures:
                fixtures_data.append({
                    "fixture_id": fixture.fixture_id,
                    "date": fixture.date.isoformat(),
                    "league_id": fixture.league_id,
                    "league_name": fixture.league_name,
                    "home_team_id": fixture.home_team_id,
                    "home_team": fixture.home_team,
                    "away_team_id": fixture.away_team_id,
                    "away_team": fixture.away_team,
                    "home_odds": fixture.home_odds,
                    "draw_odds": fixture.draw_odds,
                    "away_odds": fixture.away_odds
                })

            fixtures_df = pd.DataFrame(fixtures_data)
            return fixtures_df
    except Exception as e:
        logger.warning(f"Failed to check database for fixtures: {str(e)}")

    # Fetch fixtures from API using our client
    logger.info(f"Fetching fixtures for {date_str} from Football-Data.org...")

    fixtures_data = []

    # Default competitions if none provided
    if not competitions:
        competitions = "PL,PD,SA,BL1,FL1"

    competitions_list = competitions.split(",")

    # Try fetching all matches for the date first (more efficient with free tier)
    try:
        # Get all matches for this date
        response = football_data_client.get_daily_matches(
            date_str=date_str,
            use_cache=not force
        )

        # Check if response contains matches
        if "matches" in response and response["matches"]:
            logger.info(f"Found {len(response['matches'])} fixtures across all competitions")

            # Process matches
            for match in response["matches"]:
                # Check if match is in requested competitions
                competition_code = match["competition"].get("code", "")
                if competitions_list and competition_code not in competitions_list:
                    continue

                # Create fixture data
                fixture_data = {
                    "fixture_id": match["id"],
                    "date": match["utcDate"],
                    "league_id": match["competition"]["id"],
                    "league_name": match["competition"]["name"],
                    "home_team_id": match["homeTeam"]["id"],
                    "home_team": match["homeTeam"]["name"],
                    "away_team_id": match["awayTeam"]["id"],
                    "away_team": match["awayTeam"]["name"],
                    "home_odds": 0,
                    "draw_odds": 0,
                    "away_odds": 0
                }

                fixtures_data.append(fixture_data)

            # If we found fixtures, return them
            if fixtures_data:
                fixtures_df = pd.DataFrame(fixtures_data)
                fixtures_df.to_csv(cache_file, index=False)
                return fixtures_df

    except Exception as e:
        logger.error(f"Error fetching fixtures: {str(e)}")

    # Create DataFrame
    fixtures_df = pd.DataFrame(fixtures_data)

    # Check if fixtures were found
    if fixtures_df.empty:
        logger.warning(f"No fixtures found for any competition on {date_str}")
        return fixtures_df

    # Save to cache
    fixtures_df.to_csv(cache_file, index=False)

    logger.info(f"Fetched {len(fixtures_df)} fixtures for {date_str}")

    return fixtures_df

def find_similar_team_name(team_name, team_names_list):
    """
    Find the most similar team name in the list.

    Args:
        team_name: Team name to find
        team_names_list: List of team names to search in

    Returns:
        Most similar team name
    """
    # Check for exact match
    if team_name in team_names_list:
        return team_name

    # Check for case-insensitive match
    for name in team_names_list:
        if team_name.lower() == name.lower():
            return name

    # Check for partial match
    for name in team_names_list:
        if team_name.lower() in name.lower() or name.lower() in team_name.lower():
            return name

    # Return original name if no match found
    return team_name

def get_team_data(team_name, github_df):
    """
    Get team data from GitHub dataset.

    Args:
        team_name: Team name
        github_df: DataFrame with GitHub football data

    Returns:
        Dictionary with team data
    """
    # Get home matches
    home_matches = github_df[github_df["HomeTeam"] == team_name].sort_values("MatchDate", ascending=False).head(10)

    # Get away matches
    away_matches = github_df[github_df["AwayTeam"] == team_name].sort_values("MatchDate", ascending=False).head(10)

    # Calculate form (last 5 matches)
    form = 0
    form3 = 0
    match_count = 0

    for _, match in pd.concat([home_matches, away_matches]).sort_values("MatchDate", ascending=False).iterrows():
        if match_count < 5:
            # Calculate form points
            if match["HomeTeam"] == team_name:
                if match["FTResult"] == "H":
                    form += 3
                elif match["FTResult"] == "D":
                    form += 1
            else:
                if match["FTResult"] == "A":
                    form += 3
                elif match["FTResult"] == "D":
                    form += 1

        if match_count < 3:
            # Calculate form3 points
            if match["HomeTeam"] == team_name:
                if match["FTResult"] == "H":
                    form3 += 3
                elif match["FTResult"] == "D":
                    form3 += 1
            else:
                if match["FTResult"] == "A":
                    form3 += 3
                elif match["FTResult"] == "D":
                    form3 += 1

        match_count += 1

    # Calculate average stats
    home_stats = home_matches.mean(numeric_only=True)
    away_stats = away_matches.mean(numeric_only=True)

    # Create team data dictionary
    team_data = {
        "form": form / 15 if match_count > 0 else 0.5,  # Max form is 15 points (5 wins)
        "form3": form3 / 9 if match_count > 0 else 0.5,  # Max form3 is 9 points (3 wins)
        "shots": (home_stats.get("HomeShots", 0) + away_stats.get("AwayShots", 0)) / 2 / 20,
        "target": (home_stats.get("HomeTarget", 0) + away_stats.get("AwayTarget", 0)) / 2 / 10,
        "fouls": (home_stats.get("HomeFouls", 0) + away_stats.get("AwayFouls", 0)) / 2 / 15,
        "corners": (home_stats.get("HomeCorners", 0) + away_stats.get("AwayCorners", 0)) / 2 / 10,
        "yellow": (home_stats.get("HomeYellow", 0) + away_stats.get("AwayYellow", 0)) / 2 / 5,
        "red": (home_stats.get("HomeRed", 0) + away_stats.get("AwayRed", 0)) / 2 / 1
    }

    return team_data

def get_h2h_data(home_team, away_team, github_df):
    """
    Get head-to-head data from GitHub dataset.

    Args:
        home_team: Home team name
        away_team: Away team name
        github_df: DataFrame with GitHub football data

    Returns:
        Dictionary with H2H data
    """
    # Get H2H matches
    h2h_matches = github_df[
        ((github_df["HomeTeam"] == home_team) & (github_df["AwayTeam"] == away_team)) |
        ((github_df["HomeTeam"] == away_team) & (github_df["AwayTeam"] == home_team))
    ].sort_values("MatchDate", ascending=False).head(5)

    # Calculate H2H stats
    home_wins = 0
    away_wins = 0
    draws = 0
    total_goals = 0
    btts_count = 0

    for _, match in h2h_matches.iterrows():
        if match["HomeTeam"] == home_team and match["FTResult"] == "H":
            home_wins += 1
        elif match["HomeTeam"] == away_team and match["FTResult"] == "H":
            away_wins += 1
        elif match["FTResult"] == "D":
            draws += 1

        # Calculate goals
        home_goals = match["FTHome"]
        away_goals = match["FTAway"]
        total_goals += home_goals + away_goals

        # Calculate BTTS
        if home_goals > 0 and away_goals > 0:
            btts_count += 1

    # Create H2H data dictionary
    h2h_data = {
        "h2h_home_wins": home_wins / 5 if len(h2h_matches) > 0 else 0.5,
        "h2h_away_wins": away_wins / 5 if len(h2h_matches) > 0 else 0.5,
        "h2h_draws": draws / 5 if len(h2h_matches) > 0 else 0.5,
        "h2h_avg_goals": total_goals / len(h2h_matches) / 5 if len(h2h_matches) > 0 else 0.5,
        "h2h_btts_rate": btts_count / len(h2h_matches) if len(h2h_matches) > 0 else 0.5
    }

    return h2h_data

def prepare_features(fixtures_df, github_df):
    """
    Prepare features for prediction.

    Args:
        fixtures_df: DataFrame with fixtures
        github_df: DataFrame with GitHub football data

    Returns:
        DataFrame with features for prediction
    """
    logger.info("Preparing features for prediction...")

    # Get unique team names from GitHub dataset
    github_teams = set(github_df["HomeTeam"].unique()) | set(github_df["AwayTeam"].unique())

    # Prepare features for each fixture
    features_list = []

    for _, fixture in fixtures_df.iterrows():
        # Get team names
        home_team = fixture["home_team"]
        away_team = fixture["away_team"]

        # Find similar team names in GitHub dataset
        github_home_team = find_similar_team_name(home_team, github_teams)
        github_away_team = find_similar_team_name(away_team, github_teams)

        # Get team data
        home_data = get_team_data(github_home_team, github_df)
        away_data = get_team_data(github_away_team, github_df)

        # Get H2H data
        h2h_data = get_h2h_data(github_home_team, github_away_team, github_df)

        # Create feature dictionary
        feature_dict = {
            "fixture_id": fixture["fixture_id"],
            "date": fixture["date"],
            "league_id": fixture["league_id"],
            "league_name": fixture["league_name"],
            "home_team": home_team,
            "away_team": away_team,

            # Home team features
            "home_form": home_data["form"],
            "home_form3": home_data["form3"],
            "home_shots": home_data["shots"],
            "home_target": home_data["target"],
            "home_fouls": home_data["fouls"],
            "home_corners": home_data["corners"],
            "home_yellow": home_data["yellow"],
            "home_red": home_data["red"],

            # Away team features
            "away_form": away_data["form"],
            "away_form3": away_data["form3"],
            "away_shots": away_data["shots"],
            "away_target": away_data["target"],
            "away_fouls": away_data["fouls"],
            "away_corners": away_data["corners"],
            "away_yellow": away_data["yellow"],
            "away_red": away_data["red"],

            # H2H features
            "h2h_home_wins": h2h_data["h2h_home_wins"],
            "h2h_away_wins": h2h_data["h2h_away_wins"],
            "h2h_draws": h2h_data["h2h_draws"],
            "h2h_avg_goals": h2h_data["h2h_avg_goals"],
            "h2h_btts_rate": h2h_data["h2h_btts_rate"],

            # Odds features
            "home_odds": fixture["home_odds"] if "home_odds" in fixture and fixture["home_odds"] > 0 else 2.5,
            "draw_odds": fixture["draw_odds"] if "draw_odds" in fixture and fixture["draw_odds"] > 0 else 3.5,
            "away_odds": fixture["away_odds"] if "away_odds" in fixture and fixture["away_odds"] > 0 else 3.0,

            # Derived features
            "home_win_prob": 1/fixture["home_odds"] if "home_odds" in fixture and fixture["home_odds"] > 0 else 0.33,
            "draw_prob": 1/fixture["draw_odds"] if "draw_odds" in fixture and fixture["draw_odds"] > 0 else 0.33,
            "away_win_prob": 1/fixture["away_odds"] if "away_odds" in fixture and fixture["away_odds"] > 0 else 0.33
        }

        features_list.append(feature_dict)

    # Create DataFrame
    features_df = pd.DataFrame(features_list)

    # Handle missing values
    features_df = features_df.fillna(0)

    logger.info(f"Prepared features for {len(features_df)} fixtures")

    return features_df

def load_xgboost_models():
    """
    Load XGBoost models.

    Returns:
        Dictionary with loaded models
    """
    logger.info("Loading XGBoost models...")

    models = {}
    model_types = [
        "match_result", "over_1_5", "over_2_5", "over_3_5", "btts",
        "clean_sheet_home", "clean_sheet_away", "win_to_nil_home", "win_to_nil_away"
    ]

    for model_type in model_types:
        model_path = os.path.join(MODELS_DIR, f"{model_type}_model.joblib")

        if os.path.exists(model_path):
            try:
                models[model_type] = joblib.load(model_path)
                logger.info(f"Loaded {model_type} model from {model_path}")
            except Exception as e:
                logger.error(f"Error loading {model_type} model: {str(e)}")
        else:
            logger.warning(f"{model_type} model not found at {model_path}")

    return models

def make_predictions(features_df, models):
    """
    Make predictions using XGBoost models.

    Args:
        features_df: DataFrame with features
        models: Dictionary with loaded models

    Returns:
        DataFrame with predictions
    """
    logger.info("Making predictions...")

    # Create copy of features DataFrame
    predictions_df = features_df.copy()

    # Select feature columns for prediction and map to the names used during training
    # Create a mapping from our current feature names to the names used during training
    feature_mapping = {
        "home_form": "home_form",
        "home_form3": "homeform3",
        "home_shots": "homeshots",
        "home_target": "hometarget",
        "home_fouls": "homefouls",
        "home_corners": "homecorners",
        "home_yellow": "homeyellow",
        "home_red": "homered",
        "away_form": "away_form",
        "away_form3": "awayform3",
        "away_shots": "awayshots",
        "away_target": "awaytarget",
        "away_fouls": "awayfouls",
        "away_corners": "awaycorners",
        "away_yellow": "awayyellow",
        "away_red": "awayred",
        "h2h_home_wins": "h2h_home_wins",
        "h2h_away_wins": "h2h_away_wins",
        "h2h_draws": "h2h_draws",
        "h2h_avg_goals": "h2h_avg_goals",
        "h2h_btts_rate": "h2h_btts_rate",
        "home_win_prob": "home_win_prob",
        "draw_prob": "draw_prob",
        "away_win_prob": "away_win_prob",
        "home_odds": "home_odds",
        "draw_odds": "draw_odds",
        "away_odds": "away_odds"
    }

    # Rename columns to match training names
    prediction_features = predictions_df.copy()
    for new_name, old_name in feature_mapping.items():
        if new_name in prediction_features.columns:
            prediction_features[old_name] = prediction_features[new_name]

    # Use the feature names that were used during training
    feature_cols = [
        "home_form", "homeform3", "homeshots", "hometarget", "homefouls", "homecorners", "homeyellow", "homered",
        "away_form", "awayform3", "awayshots", "awaytarget", "awayfouls", "awaycorners", "awayyellow", "awayred",
        "h2h_home_wins", "h2h_away_wins", "h2h_draws", "h2h_avg_goals", "h2h_btts_rate",
        "home_win_prob", "draw_prob", "away_win_prob"
    ]

    # Make predictions for each model
    for model_type, model in models.items():
        try:
            # Get features from the renamed DataFrame
            X = prediction_features[feature_cols]

            # Make predictions
            y_pred = model.predict(X)
            y_proba = model.predict_proba(X)

            # Add predictions to DataFrame
            predictions_df[f"{model_type}_pred"] = y_pred

            # Add confidence scores
            if model_type == "match_result":
                # For match result, we have 3 classes (H, D, A)
                predictions_df[f"{model_type}_confidence"] = [float(p.max()) * 100 for p in y_proba]

                # Add individual probabilities
                predictions_df["home_win_pred_prob"] = [float(p[0]) for p in y_proba]
                predictions_df["draw_pred_prob"] = [float(p[1]) for p in y_proba]
                predictions_df["away_win_pred_prob"] = [float(p[2]) for p in y_proba]
            else:
                # For binary models, we have 2 classes (0, 1)
                predictions_df[f"{model_type}_confidence"] = [float(p[1]) * 100 for p in y_proba]

            logger.info(f"Made predictions for {model_type} model")
        except Exception as e:
            logger.error(f"Error making predictions for {model_type} model: {str(e)}")

    # Map match result predictions to labels
    if "match_result_pred" in predictions_df.columns:
        predictions_df["match_result_label"] = predictions_df["match_result_pred"].map({0: "H", 1: "D", 2: "A"})

    return predictions_df

def generate_bet_selections(predictions_df):
    """
    Generate bet selections from predictions.

    Args:
        predictions_df: DataFrame with predictions

    Returns:
        Dictionary with bet selections
    """
    logger.info("Generating bet selections...")

    # Create selections dictionary
    selections = {
        "2_odds": [],
        "5_odds": [],
        "10_odds": [],
        "rollover_3_odds": []
    }

    # Filter fixtures with high confidence
    high_conf_df = predictions_df[
        (predictions_df["match_result_confidence"] > 70) |
        (predictions_df["btts_confidence"] > 70) |
        (predictions_df["over_2_5_confidence"] > 70)
    ].copy()

    # Sort by confidence
    high_conf_df = high_conf_df.sort_values("match_result_confidence", ascending=False)

    # Generate 2 odds selections
    for _, fixture in high_conf_df.iterrows():
        # Skip if we already have enough selections
        if len(selections["2_odds"]) >= 3:
            break

        # Create selection
        selection = {
            "fixture_id": fixture["fixture_id"],
            "home_team": fixture["home_team"],
            "away_team": fixture["away_team"],
            "league_name": fixture["league_name"],
            "date": fixture["date"],
            "bet_type": "",
            "prediction": "",
            "confidence": 0,
            "odds": 0
        }

        # Choose best bet type based on confidence
        if fixture["match_result_confidence"] > 70:
            # Match result
            selection["bet_type"] = "Match Result"
            selection["prediction"] = fixture["match_result_label"]
            selection["confidence"] = fixture["match_result_confidence"]

            if fixture["match_result_label"] == "H":
                selection["odds"] = fixture["home_odds"]
            elif fixture["match_result_label"] == "D":
                selection["odds"] = fixture["draw_odds"]
            else:
                selection["odds"] = fixture["away_odds"]
        elif fixture["btts_confidence"] > 70:
            # BTTS
            selection["bet_type"] = "Both Teams to Score"
            selection["prediction"] = "Yes" if fixture["btts_pred"] == 1 else "No"
            selection["confidence"] = fixture["btts_confidence"]
            selection["odds"] = 1.8  # Default odds for BTTS
        elif fixture["over_2_5_confidence"] > 70:
            # Over/Under
            selection["bet_type"] = "Over/Under 2.5"
            selection["prediction"] = "Over" if fixture["over_2_5_pred"] == 1 else "Under"
            selection["confidence"] = fixture["over_2_5_confidence"]
            selection["odds"] = 1.9  # Default odds for Over/Under

        # Add selection if odds are between 1.5 and 2.5
        if 1.5 <= selection["odds"] <= 2.5:
            selections["2_odds"].append(selection)

    # Generate 5 odds selections
    high_conf_df = high_conf_df.sort_values("btts_confidence", ascending=False)

    for _, fixture in high_conf_df.iterrows():
        # Skip if we already have enough selections
        if len(selections["5_odds"]) >= 3:
            break

        # Skip if already used in 2 odds
        if any(s["fixture_id"] == fixture["fixture_id"] for s in selections["2_odds"]):
            continue

        # Create selection
        selection = {
            "fixture_id": fixture["fixture_id"],
            "home_team": fixture["home_team"],
            "away_team": fixture["away_team"],
            "league_name": fixture["league_name"],
            "date": fixture["date"],
            "bet_type": "",
            "prediction": "",
            "confidence": 0,
            "odds": 0
        }

        # Choose best bet type based on confidence
        if fixture["btts_confidence"] > 65 and fixture["over_2_5_confidence"] > 65:
            # BTTS & Over 2.5
            selection["bet_type"] = "BTTS & Over 2.5"
            selection["prediction"] = "Yes & Over" if fixture["btts_pred"] == 1 and fixture["over_2_5_pred"] == 1 else "No & Under"
            selection["confidence"] = (fixture["btts_confidence"] + fixture["over_2_5_confidence"]) / 2
            selection["odds"] = 2.2  # Default odds for BTTS & Over 2.5
        elif fixture["match_result_confidence"] > 65 and fixture["btts_confidence"] > 65:
            # Match Result & BTTS
            selection["bet_type"] = "Match Result & BTTS"
            selection["prediction"] = f"{fixture['match_result_label']} & Yes" if fixture["btts_pred"] == 1 else f"{fixture['match_result_label']} & No"
            selection["confidence"] = (fixture["match_result_confidence"] + fixture["btts_confidence"]) / 2
            selection["odds"] = 3.5  # Default odds for Match Result & BTTS
        elif fixture["clean_sheet_home_confidence"] > 70:
            # Clean Sheet Home
            selection["bet_type"] = "Clean Sheet Home"
            selection["prediction"] = "Yes" if fixture["clean_sheet_home_pred"] == 1 else "No"
            selection["confidence"] = fixture["clean_sheet_home_confidence"]
            selection["odds"] = 2.8  # Default odds for Clean Sheet
        elif fixture["win_to_nil_home_confidence"] > 70:
            # Win to Nil Home
            selection["bet_type"] = "Win to Nil Home"
            selection["prediction"] = "Yes" if fixture["win_to_nil_home_pred"] == 1 else "No"
            selection["confidence"] = fixture["win_to_nil_home_confidence"]
            selection["odds"] = 3.2  # Default odds for Win to Nil

        # Add selection if odds are between 2.5 and 5.0
        if 2.5 <= selection["odds"] <= 5.0:
            selections["5_odds"].append(selection)

    # Generate 10 odds selections
    high_conf_df = high_conf_df.sort_values("over_3_5_confidence", ascending=False)

    for _, fixture in high_conf_df.iterrows():
        # Skip if we already have enough selections
        if len(selections["10_odds"]) >= 3:
            break

        # Skip if already used in 2 odds or 5 odds
        if any(s["fixture_id"] == fixture["fixture_id"] for s in selections["2_odds"] + selections["5_odds"]):
            continue

        # Create selection
        selection = {
            "fixture_id": fixture["fixture_id"],
            "home_team": fixture["home_team"],
            "away_team": fixture["away_team"],
            "league_name": fixture["league_name"],
            "date": fixture["date"],
            "bet_type": "",
            "prediction": "",
            "confidence": 0,
            "odds": 0
        }

        # Choose best bet type based on confidence
        if fixture["match_result_confidence"] > 65 and fixture["over_2_5_confidence"] > 65:
            # Match Result & Over 2.5
            selection["bet_type"] = "Match Result & Over 2.5"
            selection["prediction"] = f"{fixture['match_result_label']} & Over" if fixture["over_2_5_pred"] == 1 else f"{fixture['match_result_label']} & Under"
            selection["confidence"] = (fixture["match_result_confidence"] + fixture["over_2_5_confidence"]) / 2
            selection["odds"] = 3.8  # Default odds for Match Result & Over 2.5
        elif fixture["over_3_5_confidence"] > 65:
            # Over 3.5
            selection["bet_type"] = "Over/Under 3.5"
            selection["prediction"] = "Over" if fixture["over_3_5_pred"] == 1 else "Under"
            selection["confidence"] = fixture["over_3_5_confidence"]
            selection["odds"] = 2.7  # Default odds for Over 3.5
        elif fixture["win_to_nil_away_confidence"] > 70:
            # Win to Nil Away
            selection["bet_type"] = "Win to Nil Away"
            selection["prediction"] = "Yes" if fixture["win_to_nil_away_pred"] == 1 else "No"
            selection["confidence"] = fixture["win_to_nil_away_confidence"]
            selection["odds"] = 4.5  # Default odds for Win to Nil Away

        # Add selection if odds are between 3.0 and 10.0
        if 3.0 <= selection["odds"] <= 10.0:
            selections["10_odds"].append(selection)

    # Generate 3 odds rollover selections (3 selections with ~3.0 odds each)
    high_conf_df = high_conf_df.sort_values("match_result_confidence", ascending=False)

    for _, fixture in high_conf_df.iterrows():
        # Skip if we already have enough selections
        if len(selections["rollover_3_odds"]) >= 3:
            break

        # Skip if already used in other selections
        if any(s["fixture_id"] == fixture["fixture_id"] for s in selections["2_odds"] + selections["5_odds"] + selections["10_odds"]):
            continue

        # Create selection
        selection = {
            "fixture_id": fixture["fixture_id"],
            "home_team": fixture["home_team"],
            "away_team": fixture["away_team"],
            "league_name": fixture["league_name"],
            "date": fixture["date"],
            "bet_type": "",
            "prediction": "",
            "confidence": 0,
            "odds": 0
        }

        # Choose best bet type based on confidence
        if fixture["match_result_confidence"] > 75:
            # Match result
            selection["bet_type"] = "Match Result"
            selection["prediction"] = fixture["match_result_label"]
            selection["confidence"] = fixture["match_result_confidence"]

            if fixture["match_result_label"] == "H":
                selection["odds"] = fixture["home_odds"]
            elif fixture["match_result_label"] == "D":
                selection["odds"] = fixture["draw_odds"]
            else:
                selection["odds"] = fixture["away_odds"]
        elif fixture["btts_confidence"] > 75:
            # BTTS
            selection["bet_type"] = "Both Teams to Score"
            selection["prediction"] = "Yes" if fixture["btts_pred"] == 1 else "No"
            selection["confidence"] = fixture["btts_confidence"]
            selection["odds"] = 1.8  # Default odds for BTTS
        elif fixture["over_2_5_confidence"] > 75:
            # Over/Under
            selection["bet_type"] = "Over/Under 2.5"
            selection["prediction"] = "Over" if fixture["over_2_5_pred"] == 1 else "Under"
            selection["confidence"] = fixture["over_2_5_confidence"]
            selection["odds"] = 1.9  # Default odds for Over/Under

        # Add selection if odds are around 3.0
        if 1.8 <= selection["odds"] <= 3.5:
            selections["rollover_3_odds"].append(selection)

    # Calculate combined odds
    for category in selections:
        if selections[category]:
            combined_odds = 1.0
            for selection in selections[category]:
                combined_odds *= selection["odds"]

            # Add combined odds to each selection
            for selection in selections[category]:
                selection["combined_odds"] = combined_odds

    logger.info(f"Generated bet selections: 2 odds ({len(selections['2_odds'])}), 5 odds ({len(selections['5_odds'])}), 10 odds ({len(selections['10_odds'])}), rollover ({len(selections['rollover_3_odds'])})")

    return selections

def save_predictions_to_db(predictions_df, selections):
    """
    Save predictions to database.

    Args:
        predictions_df: DataFrame with predictions
        selections: Dictionary with bet selections

    Returns:
        None
    """
    logger.info("Saving predictions to database...")

    try:
        db = SessionLocal()

        # Save each prediction
        for _, prediction in predictions_df.iterrows():
            # Check if prediction already exists
            existing = db.query(Prediction).filter(
                Prediction.fixture_id == prediction["fixture_id"]
            ).first()

            if existing:
                logger.info(f"Prediction for fixture {prediction['fixture_id']} already exists, updating...")

                # Update existing prediction
                existing.match_result_pred = prediction.get("match_result_label", "")
                existing.match_result_confidence = float(prediction.get("match_result_confidence", 0))
                existing.btts_pred = int(prediction.get("btts_pred", 0))
                existing.btts_confidence = float(prediction.get("btts_confidence", 0))
                existing.over_under_2_5_pred = int(prediction.get("over_2_5_pred", 0))
                existing.over_under_2_5_confidence = float(prediction.get("over_2_5_confidence", 0))
                existing.home_win_prob = float(prediction.get("home_win_pred_prob", 0))
                existing.draw_prob = float(prediction.get("draw_pred_prob", 0))
                existing.away_win_prob = float(prediction.get("away_win_pred_prob", 0))
                existing.updated_at = datetime.now()
            else:
                # Create new prediction
                new_prediction = Prediction(
                    id=str(uuid.uuid4()),
                    fixture_id=prediction["fixture_id"],
                    match_result_pred=prediction.get("match_result_label", ""),
                    match_result_confidence=float(prediction.get("match_result_confidence", 0)),
                    btts_pred=int(prediction.get("btts_pred", 0)),
                    btts_confidence=float(prediction.get("btts_confidence", 0)),
                    over_under_2_5_pred=int(prediction.get("over_2_5_pred", 0)),
                    over_under_2_5_confidence=float(prediction.get("over_2_5_confidence", 0)),
                    home_win_prob=float(prediction.get("home_win_pred_prob", 0)),
                    draw_prob=float(prediction.get("draw_pred_prob", 0)),
                    away_win_prob=float(prediction.get("away_win_pred_prob", 0)),
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                db.add(new_prediction)

        # Commit changes
        db.commit()
        logger.info(f"Saved {len(predictions_df)} predictions to database")

    except Exception as e:
        logger.error(f"Error saving predictions to database: {str(e)}")
        traceback.print_exc()
    finally:
        db.close()

def main():
    """Main function."""
    # Parse arguments
    args = parse_arguments()

    # Ensure directories exist
    ensure_directory_exists(DATA_DIR)
    ensure_directory_exists(MODELS_DIR)
    ensure_directory_exists(RESULTS_DIR)

    # Fetch fixtures
    fixtures_df = fetch_fixtures_from_api(args.date, args.competitions, args.force)

    if fixtures_df.empty:
        logger.error(f"No fixtures found for {args.date}")
        print(f"ERROR: No fixtures found for {args.date}. Please try another date.")
        return

    # Load GitHub dataset
    github_df = load_github_dataset()

    if github_df.empty:
        logger.error("Failed to load GitHub dataset")
        return

    # Prepare features
    features_df = prepare_features(fixtures_df, github_df)

    # Load models
    models = load_xgboost_models()

    if not models:
        logger.error("No models loaded")
        return

    # Make predictions
    predictions_df = make_predictions(features_df, models)

    # Generate bet selections
    selections = generate_bet_selections(predictions_df)

    # Save predictions to CSV
    predictions_df.to_csv(args.output, index=False)
    logger.info(f"Saved predictions to {args.output}")

    # Save selections to JSON
    import json
    selections_path = os.path.join(RESULTS_DIR, f"xgboost_selections_{args.date}.json")
    with open(selections_path, "w") as f:
        json.dump(selections, f, indent=4)
    logger.info(f"Saved selections to {selections_path}")

    # Save predictions to database if requested
    if args.save_to_db:
        save_predictions_to_db(predictions_df, selections)

    logger.info("Daily predictions completed successfully")

if __name__ == "__main__":
    main()
