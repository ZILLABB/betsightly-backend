#!/usr/bin/env python3
"""
Make Predictions with GitHub-trained Models

This script uses the models trained on GitHub football data to make predictions
for upcoming fixtures fetched from API-Football.
"""

import os
import sys
import pandas as pd
import numpy as np
import requests
import logging
import joblib
from datetime import datetime
import argparse
from typing import Dict, List, Tuple, Any, Union
from sklearn.preprocessing import StandardScaler

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "enhanced")  # Use enhanced models
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")
GITHUB_DATASET_URL = "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data-2000-2025/main/data/Matches.csv"
GITHUB_ELO_URL = "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data-2000-2025/main/data/Elo%20Ratings.csv"

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Make predictions with GitHub-trained models")

    parser.add_argument(
        "--date",
        type=str,
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Date to predict fixtures for (YYYY-MM-DD)"
    )

    parser.add_argument(
        "--leagues",
        type=str,
        default="39,140,135,78,61",
        help="Comma-separated list of league IDs to predict (API-Football IDs)"
    )

    parser.add_argument(
        "--output",
        type=str,
        default="predictions.csv",
        help="Output file path"
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
    cache_file = os.path.join(cache_dir, "Matches.csv")

    # Check if cache exists
    if os.path.exists(cache_file):
        logger.info(f"Loading cached GitHub dataset from {cache_file}")
        return pd.read_csv(cache_file)
    else:
        logger.error(f"GitHub dataset not found at {cache_file}. Please run train_github_models.py first.")
        return pd.DataFrame()

def fetch_fixtures_from_api(date, leagues, api_key):
    """
    Fetch fixtures from API-Football with rate limiting and caching.

    Args:
        date: Date in format YYYY-MM-DD
        leagues: List of league IDs
        api_key: API-Football API key

    Returns:
        DataFrame with fixtures data
    """
    # Create cache directory
    cache_dir = os.path.join(DATA_DIR, "api-cache")
    ensure_directory_exists(cache_dir)

    # Create cache file path
    cache_file = os.path.join(cache_dir, f"fixtures_{date}_{leagues.replace(',', '_')}.json")

    # Check if cache exists and is less than 1 hour old
    if os.path.exists(cache_file):
        file_age = datetime.now().timestamp() - os.path.getmtime(cache_file)
        if file_age < 3600:  # 1 hour in seconds
            logger.info(f"Using cached fixtures from {cache_file}")
            with open(cache_file, 'r') as f:
                import json
                cached_data = json.load(f)

            # Create DataFrame from cached data
            if not cached_data:
                logger.warning(f"No fixtures found in cache for {date}")
                return pd.DataFrame()

            df = pd.DataFrame(cached_data)
            logger.info(f"Loaded {len(df)} fixtures from cache for {date}")
            return df

    # API endpoint
    url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"

    # Headers
    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": "api-football-v1.p.rapidapi.com"
    }

    # Get season from date
    date_obj = datetime.strptime(date, "%Y-%m-%d")
    season = date_obj.year

    # Parameters - we'll fetch fixtures for each league separately
    params = {
        "date": date,
        "season": season
    }

    # Split leagues into individual IDs
    league_ids = leagues.split(",")

    # Store all fixtures
    all_fixtures = []

    try:
        logger.info(f"Fetching fixtures for {date} from API-Football...")

        # Fetch fixtures for each league with rate limiting
        for i, league_id in enumerate(league_ids):
            # Add delay to avoid rate limiting (1 request per second)
            if i > 0:
                import time
                time.sleep(1.2)  # 1.2 seconds to be safe

            # Update params with league ID
            params["league"] = league_id

            logger.info(f"Fetching fixtures for league {league_id}...")
            response = requests.get(url, headers=headers, params=params)

            if response.status_code == 429:
                logger.error(f"Rate limit exceeded for API-Football. Waiting 60 seconds...")
                time.sleep(60)
                # Try again
                response = requests.get(url, headers=headers, params=params)

            if response.status_code != 200:
                logger.error(f"Error fetching fixtures for league {league_id}: {response.status_code}")
                continue

            # Parse response
            data = response.json()

            if "response" not in data or len(data["response"]) == 0:
                logger.warning(f"No fixtures found for league {league_id} on {date}")
                continue

            # Extract fixtures
            for fixture in data["response"]:
                all_fixtures.append({
                    "fixture_id": fixture["fixture"]["id"],
                    "date": fixture["fixture"]["date"],
                    "league_id": fixture["league"]["id"],
                    "league_name": fixture["league"]["name"],
                    "home_team_id": fixture["teams"]["home"]["id"],
                    "home_team": fixture["teams"]["home"]["name"],
                    "away_team_id": fixture["teams"]["away"]["id"],
                    "away_team": fixture["teams"]["away"]["name"],
                    "home_odds": fixture.get("odds", {}).get("1", 0),
                    "draw_odds": fixture.get("odds", {}).get("X", 0),
                    "away_odds": fixture.get("odds", {}).get("2", 0)
                })

        # Create DataFrame
        if not all_fixtures:
            logger.warning(f"No fixtures found for any league on {date}")
            # Save empty cache to avoid repeated API calls
            with open(cache_file, 'w') as f:
                import json
                json.dump([], f)
            return pd.DataFrame()

        df = pd.DataFrame(all_fixtures)

        # Save to cache
        with open(cache_file, 'w') as f:
            import json
            json.dump(all_fixtures, f)

        logger.info(f"Fetched {len(df)} fixtures for {date}")
        return df

    except Exception as e:
        logger.error(f"Error fetching fixtures: {str(e)}")
        return pd.DataFrame()

# We're removing these functions to minimize API calls
# Instead, we'll use the GitHub dataset for all historical data
# and only use API-Football for daily fixtures

def prepare_features(fixtures_df, github_df):
    """
    Prepare features for prediction using only GitHub dataset for historical data.
    Enhanced to match the features used in the ensemble models.

    Args:
        fixtures_df: DataFrame with fixtures data
        github_df: DataFrame with GitHub football data

    Returns:
        DataFrame with features
    """
    # Create features DataFrame
    features = []

    for _, fixture in fixtures_df.iterrows():
        # Get team names
        home_team = fixture["home_team"]
        away_team = fixture["away_team"]

        # Find similar team names in GitHub dataset
        home_team_github = find_similar_team_name(home_team, github_df["HomeTeam"].unique())
        away_team_github = find_similar_team_name(away_team, github_df["AwayTeam"].unique())

        # Get team data from GitHub dataset
        home_team_data = get_team_data(home_team_github, github_df)
        away_team_data = get_team_data(away_team_github, github_df)

        # Get H2H data from GitHub dataset
        h2h_data = get_h2h_data(home_team_github, away_team_github, github_df)

        # Get Elo ratings from GitHub dataset
        home_elo = get_elo_rating(home_team_github, github_df)
        away_elo = get_elo_rating(away_team_github, github_df)

        # Get odds from API-Football
        home_odds = fixture.get("home_odds", 0)
        draw_odds = fixture.get("draw_odds", 0)
        away_odds = fixture.get("away_odds", 0)

        # Calculate implied probabilities
        home_win_prob = 1/home_odds if home_odds > 0 else 0.33
        draw_prob = 1/draw_odds if draw_odds > 0 else 0.33
        away_win_prob = 1/away_odds if away_odds > 0 else 0.33

        # Create feature dictionary
        feature_dict = {
            "fixture_id": fixture["fixture_id"],
            "date": fixture["date"],
            "league_id": fixture["league_id"],
            "league_name": fixture["league_name"],
            "home_team_id": fixture["home_team_id"],
            "home_team": fixture["home_team"],
            "away_team_id": fixture["away_team_id"],
            "away_team": fixture["away_team"],

            # Basic features
            "home_form": home_team_data.get("form", 0.5),
            "away_form": away_team_data.get("form", 0.5),
            "home_elo": home_elo / 2000,
            "away_elo": away_elo / 2000,
            "elo_diff": (home_elo - away_elo) / 500,
            "home_odds": home_odds,
            "draw_odds": draw_odds,
            "away_odds": away_odds,
            "home_win_prob": home_win_prob,
            "draw_prob": draw_prob,
            "away_win_prob": away_win_prob,

            # Enhanced features - Over/Under odds (estimated if not available)
            "over_odds": 1.9,  # Default value if not available
            "under_odds": 1.9,  # Default value if not available

            # Enhanced features - Asian Handicap (estimated if not available)
            "handi_size": -0.5 if home_win_prob > away_win_prob else 0.5,  # Estimated based on odds
            "handi_home": 1.9,  # Default value if not available
            "handi_away": 1.9,  # Default value if not available

            # Form features
            "form3home": home_team_data.get("form3", 0.5),
            "form3away": away_team_data.get("form3", 0.5),

            # Additional features
            "homeshots": home_team_data.get("shots", 0.5),
            "awayshots": away_team_data.get("shots", 0.5),
            "hometarget": home_team_data.get("target", 0.5),
            "awaytarget": away_team_data.get("target", 0.5),
            "homefouls": home_team_data.get("fouls", 0.5),
            "awayfouls": away_team_data.get("fouls", 0.5),
            "homecorners": home_team_data.get("corners", 0.5),
            "awaycorners": away_team_data.get("corners", 0.5),
            "homeyellow": home_team_data.get("yellow", 0.5),
            "awayyellow": away_team_data.get("yellow", 0.5),
            "homered": home_team_data.get("red", 0.5),
            "awayred": away_team_data.get("red", 0.5)
        }

        features.append(feature_dict)

    # Create DataFrame
    features_df = pd.DataFrame(features)

    # Handle missing values
    features_df = features_df.fillna(0)

    return features_df

def find_similar_team_name(team_name, team_names_list):
    """
    Find the most similar team name in the list.

    Args:
        team_name: Team name to find
        team_names_list: List of team names to search in

    Returns:
        Most similar team name
    """
    # Simple mapping for common team names
    common_mappings = {
        "Manchester United": "Man United",
        "Manchester City": "Man City",
        "Tottenham": "Tottenham",
        "Arsenal": "Arsenal",
        "Liverpool": "Liverpool",
        "Chelsea": "Chelsea",
        "Everton": "Everton",
        "Leicester": "Leicester",
        "West Ham": "West Ham",
        "Aston Villa": "Aston Villa",
        "Newcastle": "Newcastle",
        "Crystal Palace": "Crystal Palace",
        "Brighton": "Brighton",
        "Southampton": "Southampton",
        "Burnley": "Burnley",
        "Wolves": "Wolves",
        "Watford": "Watford",
        "Norwich": "Norwich",
        "Bournemouth": "Bournemouth",
        "Sheffield Utd": "Sheffield United",
        "Leeds": "Leeds",
        "Brentford": "Brentford",
        "Fulham": "Fulham",
        "West Brom": "West Brom",
        "Barcelona": "Barcelona",
        "Real Madrid": "Real Madrid",
        "Atletico Madrid": "Atletico Madrid",
        "Sevilla": "Sevilla",
        "Valencia": "Valencia",
        "Villarreal": "Villarreal",
        "Athletic Club": "Athletic Bilbao",
        "Real Sociedad": "Real Sociedad",
        "Real Betis": "Betis",
        "Juventus": "Juventus",
        "Inter": "Inter",
        "AC Milan": "Milan",
        "Napoli": "Napoli",
        "Roma": "Roma",
        "Lazio": "Lazio",
        "Atalanta": "Atalanta",
        "Bayern Munich": "Bayern Munich",
        "Borussia Dortmund": "Dortmund",
        "RB Leipzig": "RB Leipzig",
        "Bayer Leverkusen": "Leverkusen",
        "Borussia Monchengladbach": "Monchengladbach",
        "Paris Saint Germain": "PSG",
        "Lyon": "Lyon",
        "Marseille": "Marseille",
        "Monaco": "Monaco"
    }

    # Check if team name is in common mappings
    if team_name in common_mappings:
        mapped_name = common_mappings[team_name]
        # Check if mapped name is in team_names_list
        if mapped_name in team_names_list:
            return mapped_name

    # If not found in mappings, return the original name
    # In a real implementation, you would use fuzzy matching here
    return team_name

def calculate_form(form_string):
    """
    Calculate form from API-Football form string.

    Args:
        form_string: Form string (e.g., "WDLWW")

    Returns:
        Form value between 0 and 1
    """
    if not form_string:
        return 0.5

    # Calculate points
    points = 0
    for result in form_string:
        if result == "W":
            points += 3
        elif result == "D":
            points += 1

    # Calculate maximum possible points
    max_points = len(form_string) * 3

    # Return form as a value between 0 and 1
    return points / max_points if max_points > 0 else 0.5

def get_elo_rating(team_name, github_df):
    """
    Get Elo rating for a team from GitHub dataset.

    Args:
        team_name: Team name
        github_df: DataFrame with GitHub football data

    Returns:
        Elo rating
    """
    # Get the most recent matches for the team
    team_matches = github_df[(github_df["HomeTeam"] == team_name) | (github_df["AwayTeam"] == team_name)]

    if team_matches.empty:
        return 1500  # Default Elo rating

    # Sort by date (most recent first)
    team_matches = team_matches.sort_values("MatchDate", ascending=False)

    # Get the most recent match
    most_recent_match = team_matches.iloc[0]

    # Get Elo rating
    if most_recent_match["HomeTeam"] == team_name:
        return most_recent_match["HomeElo"] if not pd.isna(most_recent_match["HomeElo"]) else 1500
    else:
        return most_recent_match["AwayElo"] if not pd.isna(most_recent_match["AwayElo"]) else 1500

def get_team_data(team_name, github_df):
    """
    Get team data from GitHub dataset.

    Args:
        team_name: Team name
        github_df: DataFrame with GitHub football data

    Returns:
        Dictionary with team data
    """
    # Get the most recent matches for the team
    team_matches = github_df[(github_df["HomeTeam"] == team_name) | (github_df["AwayTeam"] == team_name)]

    if team_matches.empty:
        return {
            "form": 0.5,
            "form3": 0.5,
            "shots": 0.5,
            "target": 0.5,
            "fouls": 0.5,
            "corners": 0.5,
            "yellow": 0.5,
            "red": 0.5
        }

    # Sort by date (most recent first)
    team_matches = team_matches.sort_values("MatchDate", ascending=False)

    # Get the last 5 matches
    last_5_matches = team_matches.head(5)

    # Calculate form (last 5 matches)
    form_points = 0
    for _, match in last_5_matches.iterrows():
        if match["HomeTeam"] == team_name:
            if match["FTResult"] == "H":
                form_points += 3
            elif match["FTResult"] == "D":
                form_points += 1
        else:  # Away team
            if match["FTResult"] == "A":
                form_points += 3
            elif match["FTResult"] == "D":
                form_points += 1

    form = form_points / (5 * 3) if len(last_5_matches) == 5 else form_points / (len(last_5_matches) * 3)

    # Calculate form3 (last 3 matches)
    form3_points = 0
    for _, match in last_5_matches.head(3).iterrows():
        if match["HomeTeam"] == team_name:
            if match["FTResult"] == "H":
                form3_points += 3
            elif match["FTResult"] == "D":
                form3_points += 1
        else:  # Away team
            if match["FTResult"] == "A":
                form3_points += 3
            elif match["FTResult"] == "D":
                form3_points += 1

    form3 = form3_points / (3 * 3) if len(last_5_matches) >= 3 else form3_points / (len(last_5_matches) * 3)

    # Calculate average stats
    shots = 0
    target = 0
    fouls = 0
    corners = 0
    yellow = 0
    red = 0
    count = 0

    for _, match in last_5_matches.iterrows():
        if match["HomeTeam"] == team_name:
            # Home team stats
            if "HomeShots" in match and not pd.isna(match["HomeShots"]):
                shots += match["HomeShots"]
                count += 1
            if "HomeTarget" in match and not pd.isna(match["HomeTarget"]):
                target += match["HomeTarget"]
            if "HomeFouls" in match and not pd.isna(match["HomeFouls"]):
                fouls += match["HomeFouls"]
            if "HomeCorners" in match and not pd.isna(match["HomeCorners"]):
                corners += match["HomeCorners"]
            if "HomeYellow" in match and not pd.isna(match["HomeYellow"]):
                yellow += match["HomeYellow"]
            if "HomeRed" in match and not pd.isna(match["HomeRed"]):
                red += match["HomeRed"]
        else:  # Away team
            # Away team stats
            if "AwayShots" in match and not pd.isna(match["AwayShots"]):
                shots += match["AwayShots"]
                count += 1
            if "AwayTarget" in match and not pd.isna(match["AwayTarget"]):
                target += match["AwayTarget"]
            if "AwayFouls" in match and not pd.isna(match["AwayFouls"]):
                fouls += match["AwayFouls"]
            if "AwayCorners" in match and not pd.isna(match["AwayCorners"]):
                corners += match["AwayCorners"]
            if "AwayYellow" in match and not pd.isna(match["AwayYellow"]):
                yellow += match["AwayYellow"]
            if "AwayRed" in match and not pd.isna(match["AwayRed"]):
                red += match["AwayRed"]

    # Normalize stats
    shots = (shots / count) / 30 if count > 0 else 0.5
    target = (target / count) / 30 if count > 0 else 0.5
    fouls = (fouls / count) / 20 if count > 0 else 0.5
    corners = (corners / count) / 15 if count > 0 else 0.5
    yellow = (yellow / count) / 5 if count > 0 else 0.5
    red = (red / count) / 5 if count > 0 else 0.5

    return {
        "form": form,
        "form3": form3,
        "shots": shots,
        "target": target,
        "fouls": fouls,
        "corners": corners,
        "yellow": yellow,
        "red": red
    }

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
    ]

    if h2h_matches.empty:
        return {
            "home_form": 0.5,
            "away_form": 0.5
        }

    # Sort by date (most recent first)
    h2h_matches = h2h_matches.sort_values("MatchDate", ascending=False)

    # Get the last 10 matches
    last_10_matches = h2h_matches.head(10)

    # Count home team wins, away team wins, and draws
    home_wins = 0
    away_wins = 0
    draws = 0

    for _, match in last_10_matches.iterrows():
        if match["HomeTeam"] == home_team and match["AwayTeam"] == away_team:
            if match["FTResult"] == "H":
                home_wins += 1
            elif match["FTResult"] == "A":
                away_wins += 1
            else:
                draws += 1
        else:  # Away team is home, home team is away
            if match["FTResult"] == "H":
                away_wins += 1
            elif match["FTResult"] == "A":
                home_wins += 1
            else:
                draws += 1

    # Calculate H2H form
    total_matches = len(last_10_matches)
    if total_matches > 0:
        home_form = (home_wins + 0.5 * draws) / total_matches
        away_form = (away_wins + 0.5 * draws) / total_matches
    else:
        home_form = 0.5
        away_form = 0.5

    return {
        "home_form": home_form,
        "away_form": away_form
    }

def make_predictions(features_df):
    """
    Make predictions using trained models.

    Args:
        features_df: DataFrame with features

    Returns:
        DataFrame with predictions
    """
    # Load models
    match_result_model_path = os.path.join(MODELS_DIR, "match_result_model.joblib")
    over_under_model_path = os.path.join(MODELS_DIR, "over_under_model.joblib")
    btts_model_path = os.path.join(MODELS_DIR, "btts_model.joblib")

    if not os.path.exists(match_result_model_path) or not os.path.exists(over_under_model_path) or not os.path.exists(btts_model_path):
        logger.error("Models not found. Please run train_github_models.py first.")
        return pd.DataFrame()

    match_result_model = joblib.load(match_result_model_path)
    over_under_model = joblib.load(over_under_model_path)
    btts_model = joblib.load(btts_model_path)

    # Get feature columns
    feature_columns = [col for col in features_df.columns if col not in [
        "fixture_id", "date", "league_id", "league_name",
        "home_team_id", "home_team", "away_team_id", "away_team"
    ]]

    # Make predictions
    match_result_probs = match_result_model.predict_proba(features_df[feature_columns])
    over_under_probs = over_under_model.predict_proba(features_df[feature_columns])
    btts_probs = btts_model.predict_proba(features_df[feature_columns])

    # Add predictions to features DataFrame
    predictions_df = features_df.copy()

    # Match result predictions
    predictions_df["home_win_pred"] = match_result_probs[:, 0]
    predictions_df["draw_pred"] = match_result_probs[:, 1]
    predictions_df["away_win_pred"] = match_result_probs[:, 2]

    # Over/under predictions
    predictions_df["under_2_5_pred"] = over_under_probs[:, 0]
    predictions_df["over_2_5_pred"] = over_under_probs[:, 1]

    # BTTS predictions
    predictions_df["btts_no_pred"] = btts_probs[:, 0]
    predictions_df["btts_yes_pred"] = btts_probs[:, 1]

    # Get predicted outcomes
    predictions_df["match_result_pred"] = np.argmax(match_result_probs, axis=1)
    predictions_df["match_result_pred"] = predictions_df["match_result_pred"].map({0: "HOME", 1: "DRAW", 2: "AWAY"})

    predictions_df["over_under_pred"] = np.argmax(over_under_probs, axis=1)
    predictions_df["over_under_pred"] = predictions_df["over_under_pred"].map({0: "UNDER", 1: "OVER"})

    predictions_df["btts_pred"] = np.argmax(btts_probs, axis=1)
    predictions_df["btts_pred"] = predictions_df["btts_pred"].map({0: "NO", 1: "YES"})

    return predictions_df

def save_to_database(fixtures_df, predictions_df):
    """
    Save fixtures and predictions to the database.

    Args:
        fixtures_df: DataFrame with fixtures data
        predictions_df: DataFrame with predictions data
    """
    try:
        # Import database modules
        import sys
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        from app.database import get_db
        from app.services.fixture_service import FixtureService
        from app.services.prediction_service import PredictionService

        # Get database session
        db = next(get_db())

        # Create services
        fixture_service = FixtureService(db)
        prediction_service = PredictionService(db)

        # Convert DataFrames to dictionaries
        fixtures_data = fixtures_df.to_dict(orient="records")
        predictions_data = predictions_df.to_dict(orient="records")

        # Save fixtures to database
        logger.info(f"Saving {len(fixtures_data)} fixtures to database")
        fixtures = fixture_service.create_or_update_fixtures(fixtures_data)

        # Save predictions to database
        logger.info(f"Saving {len(predictions_data)} predictions to database")
        predictions = prediction_service.create_or_update_predictions(predictions_data)

        logger.info(f"Successfully saved {len(fixtures)} fixtures and {len(predictions)} predictions to database")

    except Exception as e:
        logger.error(f"Error saving to database: {str(e)}")

def main():
    """Main function."""
    # Parse arguments
    args = parse_arguments()

    # Ensure directories exist
    ensure_directory_exists(DATA_DIR)

    # Only create directory if output is not in current directory
    if os.path.dirname(args.output):
        ensure_directory_exists(os.path.dirname(args.output))

    # Get API key from environment
    api_key = os.environ.get("API_FOOTBALL_KEY", "")
    if not api_key:
        logger.error("API_FOOTBALL_KEY not found in environment variables")
        return

    # Load GitHub dataset
    github_df = load_github_dataset()

    if github_df.empty:
        logger.error("Failed to load GitHub dataset")
        return

    # Fetch fixtures from API-Football (only daily fixtures)
    fixtures_df = fetch_fixtures_from_api(args.date, args.leagues, api_key)

    if fixtures_df.empty:
        logger.error("Failed to fetch fixtures")
        return

    # Prepare features using GitHub dataset for historical data
    features_df = prepare_features(fixtures_df, github_df)

    # Make predictions
    predictions_df = make_predictions(features_df)

    if predictions_df.empty:
        logger.error("Failed to make predictions")
        return

    # Save predictions to CSV
    predictions_df.to_csv(args.output, index=False)
    logger.info(f"Predictions saved to {args.output}")

    # Save to database
    save_to_database(fixtures_df, predictions_df)

    # Print summary
    logger.info(f"Made predictions for {len(predictions_df)} fixtures")

    # Print predictions
    for _, prediction in predictions_df.iterrows():
        logger.info(f"{prediction['home_team']} vs {prediction['away_team']}: {prediction['match_result_pred']} ({prediction['home_win_pred']:.2f}/{prediction['draw_pred']:.2f}/{prediction['away_win_pred']:.2f}), Over/Under: {prediction['over_under_pred']} ({prediction['over_2_5_pred']:.2f}), BTTS: {prediction['btts_pred']} ({prediction['btts_yes_pred']:.2f})")

if __name__ == "__main__":
    main()
