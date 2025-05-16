#!/usr/bin/env python3
"""
Production-Ready Daily Football Predictions

This script runs daily predictions using the enhanced ensemble models.
It includes error handling, logging, and database storage.
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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Add parent directory to path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(backend_dir)
os.chdir(backend_dir)  # Change to backend directory to ensure .env is found

# Import settings module
from app.utils.config import settings, FOOTBALL_DATA_KEY, FOOTBALL_DATA_BASE_URL, FOOTBALL_DATA_DEFAULT_COMPETITIONS
from app.services.api_client import FootballDataClient

# Set up logging
log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f"daily_predictions_{datetime.now().strftime('%Y-%m-%d')}.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "enhanced")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")
GITHUB_DATASET_URL = "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data-2000-2025/main/data/Matches.csv"
GITHUB_ELO_URL = "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data-2000-2025/main/data/Elo%20Ratings.csv"

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

# Email notification settings
EMAIL_ENABLED = os.environ.get("EMAIL_NOTIFICATIONS", "false").lower() == "true"
EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "")
EMAIL_SMTP_SERVER = os.environ.get("EMAIL_SMTP_SERVER", "smtp.gmail.com")
EMAIL_SMTP_PORT = int(os.environ.get("EMAIL_SMTP_PORT", "587"))

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Run daily football predictions")

    parser.add_argument(
        "--date",
        type=str,
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Date for predictions (YYYY-MM-DD)"
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
        default=os.path.join(RESULTS_DIR, f"predictions_{datetime.now().strftime('%Y-%m-%d')}.csv"),
        help="Output file path"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force fetching fixtures from API even if cached"
    )

    parser.add_argument(
        "--check-api",
        action="store_true",
        help="Only check API status and exit"
    )

    return parser.parse_args()

def send_email_notification(subject, message):
    """Send email notification."""
    if not EMAIL_ENABLED:
        logger.info("Email notifications disabled")
        return

    if not EMAIL_SENDER or not EMAIL_PASSWORD or not EMAIL_RECIPIENT:
        logger.warning("Email settings not configured")
        return

    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECIPIENT
        msg["Subject"] = subject

        msg.attach(MIMEText(message, "plain"))

        server = smtplib.SMTP(EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()

        logger.info(f"Email notification sent: {subject}")
    except Exception as e:
        logger.error(f"Failed to send email notification: {str(e)}")

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

def fetch_fixtures_from_api(date_str, competitions=None, api_key=None, force=False):
    """
    Fetch fixtures from Football-Data.org.

    Args:
        date_str: Date string in YYYY-MM-DD format
        competitions: Comma-separated list of competition codes (e.g., "PL,PD,SA")
        api_key: Football-Data.org API key (optional, uses default if not provided)
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
        from app.database import SessionLocal
        from app.models.fixture import Fixture

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
    logger.info(f"Fetching all fixtures for {date_str} from Football-Data.org...")

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

                # Add odds if available (not directly available from football-data.org)
                # We'll need to fetch odds from another source or use default values

                fixtures_data.append(fixture_data)

            # If we found fixtures, return them
            if fixtures_data:
                return pd.DataFrame(fixtures_data)

    except Exception as e:
        logger.error(f"Error fetching all fixtures: {str(e)}")
        # Check if it's a rate limit error
        if isinstance(e, dict) and "status" in e and e["status"] == "error" and "429" in str(e.get("message", "")):
            logger.error("API RATE LIMIT EXCEEDED. Please try again later.")
            # Return empty DataFrame to indicate rate limit issue
            return pd.DataFrame({'rate_limit_exceeded': [True]})

    # If we couldn't get all matches at once, try competition by competition as fallback
    logger.info("Falling back to fetching fixtures by competition...")
    for competition in competitions_list:
        logger.info(f"Fetching fixtures for competition {competition}...")

        try:
            # Get matches for this competition and date
            response = football_data_client.get_competition_matches(
                competition=competition,
                date_str=date_str,
                use_cache=not force
            )

            # Check if response contains matches
            if "matches" not in response or not response["matches"]:
                logger.warning(f"No fixtures found for competition {competition} on {date_str}")
                continue

            # Process matches
            for match in response["matches"]:
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

        except Exception as e:
            logger.error(f"Error fetching fixtures for competition {competition}: {str(e)}")
            # Check if it's a rate limit error
            if isinstance(e, dict) and "status" in e and e["status"] == "error" and "429" in str(e.get("message", "")):
                logger.error("API RATE LIMIT EXCEEDED. Please try again later.")
                # Return empty DataFrame to indicate rate limit issue
                return pd.DataFrame({'rate_limit_exceeded': [True]})

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

    # Calculate H2H form
    home_form = 0
    away_form = 0
    match_count = 0

    for _, match in h2h_matches.iterrows():
        if match["HomeTeam"] == home_team:
            if match["FTResult"] == "H":
                home_form += 3
            elif match["FTResult"] == "D":
                home_form += 1
                away_form += 1
            else:
                away_form += 3
        else:
            if match["FTResult"] == "H":
                away_form += 3
            elif match["FTResult"] == "D":
                home_form += 1
                away_form += 1
            else:
                home_form += 3

        match_count += 1

    # Create H2H data dictionary
    h2h_data = {
        "home_form": home_form / (match_count * 3) if match_count > 0 else 0.5,
        "away_form": away_form / (match_count * 3) if match_count > 0 else 0.5
    }

    return h2h_data

def get_elo_rating(team_name, github_df):
    """
    Get Elo rating from GitHub dataset.

    Args:
        team_name: Team name
        github_df: DataFrame with GitHub football data

    Returns:
        Elo rating
    """
    # Get latest match
    latest_match = github_df[
        (github_df["HomeTeam"] == team_name) | (github_df["AwayTeam"] == team_name)
    ].sort_values("MatchDate", ascending=False).head(1)

    # Get Elo rating
    if not latest_match.empty:
        if latest_match.iloc[0]["HomeTeam"] == team_name:
            return latest_match.iloc[0]["HomeElo"] if "HomeElo" in latest_match.columns and not pd.isna(latest_match.iloc[0]["HomeElo"]) else 1500
        else:
            return latest_match.iloc[0]["AwayElo"] if "AwayElo" in latest_match.columns and not pd.isna(latest_match.iloc[0]["AwayElo"]) else 1500

    return 1500

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

def make_predictions(features_df):
    """
    Make predictions using the trained models.

    Args:
        features_df: DataFrame with features

    Returns:
        DataFrame with predictions
    """
    # Check if features DataFrame is empty
    if features_df.empty:
        logger.error("Features DataFrame is empty")
        return pd.DataFrame()

    # Load models
    try:
        match_result_model_path = os.path.join(MODELS_DIR, "match_result_model.joblib")
        over_under_model_path = os.path.join(MODELS_DIR, "over_under_model.joblib")
        btts_model_path = os.path.join(MODELS_DIR, "btts_model.joblib")

        if not os.path.exists(match_result_model_path):
            logger.error(f"Match result model not found at {match_result_model_path}")
            return pd.DataFrame()

        if not os.path.exists(over_under_model_path):
            logger.error(f"Over/under model not found at {over_under_model_path}")
            return pd.DataFrame()

        if not os.path.exists(btts_model_path):
            logger.error(f"BTTS model not found at {btts_model_path}")
            return pd.DataFrame()

        match_result_model = joblib.load(match_result_model_path)
        over_under_model = joblib.load(over_under_model_path)
        btts_model = joblib.load(btts_model_path)
    except Exception as e:
        logger.error(f"Error loading models: {str(e)}")
        return pd.DataFrame()

    # Get feature columns
    feature_columns = [col for col in features_df.columns if col not in [
        "fixture_id", "date", "league_id", "league_name",
        "home_team_id", "home_team", "away_team_id", "away_team"
    ]]

    # Make predictions
    try:
        match_result_probs = match_result_model.predict_proba(features_df[feature_columns])
        over_under_probs = over_under_model.predict_proba(features_df[feature_columns])
        btts_probs = btts_model.predict_proba(features_df[feature_columns])
    except Exception as e:
        logger.error(f"Error making predictions: {str(e)}")
        return pd.DataFrame()

    # Create predictions DataFrame
    predictions_df = features_df[["fixture_id", "date", "league_id", "league_name", "home_team_id", "home_team", "away_team_id", "away_team"]].copy()

    # Add match result predictions
    predictions_df["home_win_pred"] = match_result_probs[:, 0]
    predictions_df["draw_pred"] = match_result_probs[:, 1]
    predictions_df["away_win_pred"] = match_result_probs[:, 2]

    # Add over/under predictions
    predictions_df["under_2_5_pred"] = over_under_probs[:, 0]
    predictions_df["over_2_5_pred"] = over_under_probs[:, 1]

    # Add BTTS predictions
    predictions_df["btts_no_pred"] = btts_probs[:, 0]
    predictions_df["btts_yes_pred"] = btts_probs[:, 1]

    # Get predicted outcomes
    predictions_df["match_result_pred"] = np.argmax(match_result_probs, axis=1)
    predictions_df["match_result_pred"] = predictions_df["match_result_pred"].map({0: "HOME", 1: "DRAW", 2: "AWAY"})

    predictions_df["over_under_pred"] = np.argmax(over_under_probs, axis=1)
    predictions_df["over_under_pred"] = predictions_df["over_under_pred"].map({0: "UNDER", 1: "OVER"})

    predictions_df["btts_pred"] = np.argmax(btts_probs, axis=1)
    predictions_df["btts_pred"] = predictions_df["btts_pred"].map({0: "NO", 1: "YES"})

    # Calculate confidence levels
    predictions_df["match_result_confidence"] = predictions_df[["home_win_pred", "draw_pred", "away_win_pred"]].max(axis=1)
    predictions_df["over_under_confidence"] = predictions_df[["under_2_5_pred", "over_2_5_pred"]].max(axis=1)
    predictions_df["btts_confidence"] = predictions_df[["btts_no_pred", "btts_yes_pred"]].max(axis=1)

    # Calculate entropy-based uncertainty (lower entropy = higher confidence)
    def calculate_entropy(probs):
        # Avoid log(0) by adding a small epsilon
        epsilon = 1e-10
        probs = np.clip(probs, epsilon, 1.0 - epsilon)
        return -np.sum(probs * np.log2(probs), axis=1)

    # Calculate entropy for each prediction type
    match_result_entropy = calculate_entropy(match_result_probs)
    over_under_entropy = calculate_entropy(over_under_probs)
    btts_entropy = calculate_entropy(btts_probs)

    # Normalize entropy to [0, 1] range where 1 is highest confidence
    max_match_entropy = np.log2(3)  # 3 classes for match result
    max_over_under_entropy = np.log2(2)  # 2 classes for over/under
    max_btts_entropy = np.log2(2)  # 2 classes for BTTS

    predictions_df["match_result_certainty"] = 1 - (match_result_entropy / max_match_entropy)
    predictions_df["over_under_certainty"] = 1 - (over_under_entropy / max_over_under_entropy)
    predictions_df["btts_certainty"] = 1 - (btts_entropy / max_btts_entropy)

    # Calculate overall prediction quality score (0-100%)
    predictions_df["prediction_quality"] = (
        (predictions_df["match_result_confidence"] * 0.4) +
        (predictions_df["over_under_confidence"] * 0.3) +
        (predictions_df["btts_confidence"] * 0.3)
    ) * 100

    # Log average confidence levels
    logger.info(f"Average match result confidence: {predictions_df['match_result_confidence'].mean():.4f}")
    logger.info(f"Average over/under confidence: {predictions_df['over_under_confidence'].mean():.4f}")
    logger.info(f"Average BTTS confidence: {predictions_df['btts_confidence'].mean():.4f}")
    logger.info(f"Average prediction quality: {predictions_df['prediction_quality'].mean():.2f}%")

    return predictions_df

def categorize_predictions(predictions_df, fixtures_df):
    """
    Categorize predictions into different odds categories.

    Args:
        predictions_df: DataFrame with predictions data
        fixtures_df: DataFrame with fixtures data

    Returns:
        DataFrame with categorized predictions
    """
    if predictions_df.empty:
        return predictions_df

    logger.info("Categorizing predictions...")

    # Calculate odds for each prediction
    predictions_df["odds"] = 0.0
    predictions_df["confidence"] = 0.0
    predictions_df["prediction_type"] = ""

    for idx, row in predictions_df.iterrows():
        # Get the highest confidence prediction
        confidences = {
            "match_result": row["match_result_confidence"],
            "over_under": row["over_under_confidence"],
            "btts": row["btts_confidence"]
        }

        best_market = max(confidences, key=confidences.get)
        confidence = confidences[best_market]

        # Calculate odds based on the market
        odds = 0.0
        if best_market == "match_result":
            if row["match_result_pred"] == "HOME":
                odds = 1.0 / row["home_win_pred"] if row["home_win_pred"] > 0 else 0
            elif row["match_result_pred"] == "DRAW":
                odds = 1.0 / row["draw_pred"] if row["draw_pred"] > 0 else 0
            elif row["match_result_pred"] == "AWAY":
                odds = 1.0 / row["away_win_pred"] if row["away_win_pred"] > 0 else 0
        elif best_market == "over_under":
            if row["over_under_pred"] == "OVER":
                odds = 1.0 / row["over_2_5_pred"] if row["over_2_5_pred"] > 0 else 0
            elif row["over_under_pred"] == "UNDER":
                odds = 1.0 / row["under_2_5_pred"] if row["under_2_5_pred"] > 0 else 0
        elif best_market == "btts":
            if row["btts_pred"] == "YES":
                odds = 1.0 / row["btts_yes_pred"] if row["btts_yes_pred"] > 0 else 0
            elif row["btts_pred"] == "NO":
                odds = 1.0 / row["btts_no_pred"] if row["btts_no_pred"] > 0 else 0

        # Ensure odds are within reasonable range (1.1 to 10.0)
        odds = max(1.1, min(10.0, odds))

        # Update the dataframe
        predictions_df.at[idx, "odds"] = odds
        predictions_df.at[idx, "confidence"] = confidence

        # Categorize based on odds and confidence
        if odds >= 7.0 and confidence >= 0.65:
            predictions_df.at[idx, "prediction_type"] = "10_odds"
        elif odds >= 3.0 and confidence >= 0.70:
            predictions_df.at[idx, "prediction_type"] = "5_odds"
        elif odds >= 1.5 and confidence >= 0.75:
            predictions_df.at[idx, "prediction_type"] = "2_odds"

        # Add quality rating based on prediction_quality
        if "prediction_quality" in row:
            quality = row["prediction_quality"]
            if quality >= 85:
                predictions_df.at[idx, "quality_rating"] = "A+"
            elif quality >= 80:
                predictions_df.at[idx, "quality_rating"] = "A"
            elif quality >= 75:
                predictions_df.at[idx, "quality_rating"] = "B+"
            elif quality >= 70:
                predictions_df.at[idx, "quality_rating"] = "B"
            elif quality >= 65:
                predictions_df.at[idx, "quality_rating"] = "C+"
            else:
                predictions_df.at[idx, "quality_rating"] = "C"

    # Count predictions by category
    categories = predictions_df["prediction_type"].value_counts().to_dict()
    logger.info(f"Categorized predictions: {categories}")

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
        from app.database import SessionLocal
        from app.services.fixture_service import FixtureService
        from app.services.prediction_service import PredictionService

        # Get database session
        db = SessionLocal()

        # Create services
        fixture_service = FixtureService(db)
        prediction_service = PredictionService(db)

        # Convert fixtures to dictionaries
        fixtures_data = fixtures_df.to_dict(orient="records")

        # Convert predictions to dictionaries with only valid fields
        predictions_data = []
        for _, row in predictions_df.iterrows():
            # Determine prediction type and odds based on prediction values
            prediction_type = None
            odds = 0.0
            confidence = 0.0

            # Assign odds based on prediction type
            if row["btts_pred"] == "YES" and row["btts_yes_pred"] >= 0.7:
                prediction_type = "btts"
                odds = 1.8  # Typical BTTS odds
                confidence = row["btts_yes_pred"]
            elif row["over_under_pred"] == "OVER" and row["over_2_5_pred"] >= 0.7:
                prediction_type = "over_2_5"
                odds = 1.9  # Typical over 2.5 odds
                confidence = row["over_2_5_pred"]
            elif row["over_under_pred"] == "UNDER" and row["under_2_5_pred"] >= 0.7:
                prediction_type = "under_2_5"
                odds = 1.9  # Typical under 2.5 odds
                confidence = row["under_2_5_pred"]
            elif row["match_result_pred"] == "HOME" and row["home_win_pred"] >= 0.7:
                prediction_type = "home_win"
                odds = 2.0  # Typical home win odds
                confidence = row["home_win_pred"]
            elif row["match_result_pred"] == "DRAW" and row["draw_pred"] >= 0.7:
                prediction_type = "draw"
                odds = 3.5  # Typical draw odds
                confidence = row["draw_pred"]
            elif row["match_result_pred"] == "AWAY" and row["away_win_pred"] >= 0.7:
                prediction_type = "away_win"
                odds = 3.0  # Typical away win odds
                confidence = row["away_win_pred"]

            # Only include fields that exist in the Prediction model
            prediction_data = {
                "fixture_id": row["fixture_id"],
                "match_result_pred": row["match_result_pred"],
                "home_win_pred": row["home_win_pred"],
                "draw_pred": row["draw_pred"],
                "away_win_pred": row["away_win_pred"],
                "over_under_pred": row["over_under_pred"],
                "over_2_5_pred": row["over_2_5_pred"],
                "under_2_5_pred": row["under_2_5_pred"],
                "btts_pred": row["btts_pred"],
                "btts_yes_pred": row["btts_yes_pred"],
                "btts_no_pred": row["btts_no_pred"],
                "prediction_type": prediction_type,
                "odds": odds,
                "confidence": confidence
            }

            # Add new fields if they exist in the dataframe
            if "prediction_type" in row and not prediction_type:
                prediction_data["prediction_type"] = row["prediction_type"]
            if "odds" in row and odds == 0:
                prediction_data["odds"] = row["odds"]
            if "confidence" in row and confidence == 0:
                prediction_data["confidence"] = row["confidence"]

            # Add quality metrics
            if "prediction_quality" in row:
                prediction_data["prediction_quality"] = row["prediction_quality"]
            if "quality_rating" in row:
                prediction_data["quality_rating"] = row["quality_rating"]
            if "match_result_certainty" in row:
                prediction_data["match_result_certainty"] = row["match_result_certainty"]
            if "over_under_certainty" in row:
                prediction_data["over_under_certainty"] = row["over_under_certainty"]
            if "btts_certainty" in row:
                prediction_data["btts_certainty"] = row["btts_certainty"]

            predictions_data.append(prediction_data)

        # Save fixtures to database
        logger.info(f"Saving {len(fixtures_data)} fixtures to database")
        fixtures = fixture_service.create_or_update_fixtures(fixtures_data)

        # Save predictions to database
        logger.info(f"Saving {len(predictions_data)} predictions to database")
        predictions = prediction_service.create_or_update_predictions(predictions_data)

        logger.info(f"Successfully saved {len(fixtures)} fixtures and {len(predictions)} predictions to database")

    except Exception as e:
        logger.error(f"Error saving to database: {str(e)}")
        logger.error(traceback.format_exc())

def check_api_status(api_key=None):
    """Check Football-Data.org API status and available competitions."""
    logger.info("Checking Football-Data.org API status...")

    try:
        # Use our Football-Data.org client to check API status
        # We'll just get the competitions endpoint which doesn't count against match quota
        response = football_data_client.get("competitions")

        # Log API status based on competitions response
        if "competitions" in response and isinstance(response["competitions"], list):
            competitions = response["competitions"]
            logger.info(f"API is working. Found {len(competitions)} competitions.")

            # Log a few competitions as example
            if competitions:
                sample = competitions[:3]
                competition_names = []
                for c in sample:
                    name = c.get('name', 'Unknown')
                    code = c.get('code', 'Unknown')
                    competition_names.append(f"{name} ({code})")
                logger.info(f"Sample competitions: {', '.join(competition_names)}")

            return True

        # Check if it's an error response
        if "status" in response and response["status"] == "error":
            logger.error(f"API error: {response.get('message', 'Unknown error')}")
            return False

        logger.warning("Unknown API response format or no competitions found")
        return False

    except Exception as e:
        logger.error(f"Error checking API status: {str(e)}")
        return False

def main():
    """Main function."""
    start_time = datetime.now()
    logger.info(f"Starting daily predictions at {start_time}")

    try:
        # Parse arguments
        args = parse_arguments()

        # Get API key from Football-Data.org headers
        api_key = FOOTBALL_DATA_KEY
        logger.info(f"Using Football-Data.org API key: {api_key[:5]}...{api_key[-5:] if api_key else ''}")

        if not api_key:
            logger.error("Football-Data.org API key not found")
            send_email_notification(
                "Daily Predictions Failed",
                "Football-Data.org API key not found"
            )
            return

        # If only checking API status, do that and exit
        if args.check_api:
            logger.info("Checking API status only...")
            if check_api_status(api_key):
                logger.info("API status check successful. Football-Data.org API is working.")
                return
            else:
                logger.error("API status check failed. Please check your API key and subscription.")
                return

        # Ensure directories exist for full run
        ensure_directory_exists(DATA_DIR)
        ensure_directory_exists(os.path.dirname(args.output))

        # Check API status for full run
        if not check_api_status(api_key):
            logger.error("Failed to check API status. Please check your API key and subscription.")
            send_email_notification(
                "Daily Predictions Failed",
                "Failed to check API status. Please check your API key and subscription."
            )
            return

        # Load GitHub dataset
        github_df = load_github_dataset()

        if github_df.empty:
            logger.error("Failed to load GitHub dataset")
            send_email_notification(
                "Daily Predictions Failed",
                "Failed to load GitHub dataset"
            )
            return

        # Fetch fixtures from Football-Data.org
        competitions = "PL,PD,SA,BL1,FL1"  # Default competitions
        fixtures_df = fetch_fixtures_from_api(args.date, competitions, api_key, args.force)

        # Check if rate limit was exceeded
        if not fixtures_df.empty and 'rate_limit_exceeded' in fixtures_df.columns:
            logger.error("Daily predictions aborted due to API rate limit")
            send_email_notification(
                "Daily Predictions Failed - Rate Limit Exceeded",
                f"API rate limit exceeded when fetching fixtures for {args.date}. Please try again later."
            )
            return

        if fixtures_df.empty:
            logger.warning(f"No fixtures found for the specified date and competitions: {competitions}")
            # Try to fetch fixtures for all competitions to see if any are available
            logger.info("Trying to fetch fixtures for all available competitions...")
            all_competitions = "PL,PD,SA,BL1,FL1,CL,EC,WC"
            all_fixtures = fetch_fixtures_from_api(args.date, all_competitions, api_key, args.force)

            if not all_fixtures.empty and 'rate_limit_exceeded' not in all_fixtures.columns:
                logger.info(f"Found {len(all_fixtures)} fixtures in other competitions")
                logger.info("Consider updating the competitions parameter to include active competitions")

            send_email_notification(
                "Daily Predictions - No Fixtures",
                f"No fixtures found for {args.date} in competitions {competitions}"
            )
            return

        # Prepare features
        features_df = prepare_features(fixtures_df, github_df)

        # Make predictions
        predictions_df = make_predictions(features_df)

        if predictions_df.empty:
            logger.error("Failed to make predictions")
            send_email_notification(
                "Daily Predictions Failed",
                f"Failed to make predictions for {args.date}"
            )
            return

        # Categorize predictions
        predictions_df = categorize_predictions(predictions_df, fixtures_df)

        # Save predictions to CSV
        predictions_df.to_csv(args.output, index=False)
        logger.info(f"Predictions saved to {args.output}")

        # Save to database
        save_to_database(fixtures_df, predictions_df)

        # Print summary
        logger.info(f"Made predictions for {len(predictions_df)} fixtures")

        # Print high-confidence predictions
        high_confidence_predictions = predictions_df[
            (predictions_df["match_result_confidence"] >= 0.7) |
            (predictions_df["over_under_confidence"] >= 0.7) |
            (predictions_df["btts_confidence"] >= 0.7)
        ]

        if not high_confidence_predictions.empty:
            logger.info(f"\nHigh-confidence predictions ({len(high_confidence_predictions)}):")

            for _, prediction in high_confidence_predictions.iterrows():
                # Get quality rating if available
                quality_info = ""
                if "quality_rating" in prediction:
                    quality_info = f" - Quality: {prediction['quality_rating']}"
                elif "prediction_quality" in prediction:
                    quality_info = f" - Quality: {prediction['prediction_quality']:.1f}%"

                logger.info(f"{prediction['home_team']} vs {prediction['away_team']} ({prediction['league_name']}){quality_info}")

                if prediction["match_result_confidence"] >= 0.7:
                    certainty = ""
                    if "match_result_certainty" in prediction:
                        certainty = f", Certainty: {prediction['match_result_certainty']:.2f}"
                    logger.info(f"  Match Result: {prediction['match_result_pred']} (Conf: {prediction['match_result_confidence']:.2f}{certainty})")

                if prediction["over_under_confidence"] >= 0.7:
                    certainty = ""
                    if "over_under_certainty" in prediction:
                        certainty = f", Certainty: {prediction['over_under_certainty']:.2f}"
                    logger.info(f"  Over/Under: {prediction['over_under_pred']} (Conf: {prediction['over_under_confidence']:.2f}{certainty})")

                if prediction["btts_confidence"] >= 0.7:
                    certainty = ""
                    if "btts_certainty" in prediction:
                        certainty = f", Certainty: {prediction['btts_certainty']:.2f}"
                    logger.info(f"  BTTS: {prediction['btts_pred']} (Conf: {prediction['btts_confidence']:.2f}{certainty})")

                # Add odds information if available
                if "odds" in prediction:
                    logger.info(f"  Odds: {prediction['odds']:.2f}")

                # Add prediction type if available
                if "prediction_type" in prediction and prediction["prediction_type"]:
                    logger.info(f"  Category: {prediction['prediction_type']}")

        # Send email notification
        end_time = datetime.now()
        duration = end_time - start_time

        send_email_notification(
            f"Daily Predictions Completed - {args.date}",
            f"Daily predictions for {args.date} completed successfully.\n\n"
            f"Fixtures: {len(fixtures_df)}\n"
            f"Predictions: {len(predictions_df)}\n"
            f"High-confidence predictions: {len(high_confidence_predictions)}\n\n"
            f"Duration: {duration.total_seconds():.2f} seconds\n\n"
            f"Predictions saved to {args.output}"
        )

        logger.info(f"Daily predictions completed in {duration.total_seconds():.2f} seconds")

    except Exception as e:
        logger.error(f"Error in daily predictions: {str(e)}")
        logger.error(traceback.format_exc())

        send_email_notification(
            "Daily Predictions Failed",
            f"Error in daily predictions: {str(e)}\n\n{traceback.format_exc()}"
        )

if __name__ == "__main__":
    main()
