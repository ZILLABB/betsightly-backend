"""
Fetch Football Data from GitHub

This script downloads and processes football match data from the schochastics/football-data GitHub repository.
The data is used to train the machine learning models for predicting match outcomes.

Repository: https://github.com/schochastics/football-data
"""

import os
import logging
import requests
import pandas as pd
import pyarrow.parquet as pq
from typing import Dict, List, Any, Optional
from datetime import datetime
import io
import zipfile

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
HISTORICAL_DIR = os.path.join(DATA_DIR, "historical")
PROCESSED_DIR = os.path.join(HISTORICAL_DIR, "processed")
RAW_DIR = os.path.join(HISTORICAL_DIR, "raw")
FEATURES_FILE = os.path.join(PROCESSED_DIR, "features.parquet")
RESULTS_FILE = os.path.join(PROCESSED_DIR, "results.parquet")

# GitHub repository URL
GITHUB_REPO = "https://github.com/schochastics/football-data"
GITHUB_RAW = "https://raw.githubusercontent.com/schochastics/football-data/main"
GITHUB_RELEASES = "https://github.com/schochastics/football-data/releases/download"

# Top leagues to focus on for better predictions
TOP_LEAGUES = [
    "ENG-Premier League",
    "ESP-La Liga",
    "GER-Bundesliga",
    "ITA-Serie A",
    "FRA-Ligue 1",
    "NED-Eredivisie",
    "POR-Liga Portugal",
    "BEL-First Division A"
]

def download_file(url: str, save_path: str) -> bool:
    """
    Download a file from a URL and save it to disk.
    
    Args:
        url: URL to download from
        save_path: Path to save the file to
        
    Returns:
        True if download was successful, False otherwise
    """
    try:
        logger.info(f"Downloading {url} to {save_path}")
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
        # Download file
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        # Save file
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        logger.info(f"Downloaded {url} to {save_path}")
        return True
    
    except Exception as e:
        logger.error(f"Error downloading {url}: {str(e)}")
        return False

def download_latest_release() -> Optional[str]:
    """
    Download the latest release of the football-data dataset.
    
    Returns:
        Path to the downloaded file or None if download failed
    """
    try:
        # Check if we already have the data
        if os.path.exists(FEATURES_FILE) and os.path.exists(RESULTS_FILE):
            logger.info("Processed data files already exist. Skipping download.")
            return None
        
        # Create directories if they don't exist
        os.makedirs(RAW_DIR, exist_ok=True)
        os.makedirs(PROCESSED_DIR, exist_ok=True)
        
        # Download the latest release
        # For this repository, we'll use the direct link to the latest release
        # In a real implementation, we would check the GitHub API for the latest release
        release_version = "v0.2.0"  # Update this as needed
        release_file = "football-data.zip"
        release_url = f"{GITHUB_RELEASES}/{release_version}/{release_file}"
        
        zip_path = os.path.join(RAW_DIR, release_file)
        
        # Download the zip file
        if not download_file(release_url, zip_path):
            # Try alternative URL if the first one fails
            alternative_url = f"{GITHUB_RAW}/data/football-data.zip"
            if not download_file(alternative_url, zip_path):
                logger.error("Failed to download data from both URLs")
                return None
        
        # Extract the zip file
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(RAW_DIR)
        
        logger.info(f"Extracted {zip_path} to {RAW_DIR}")
        return RAW_DIR
    
    except Exception as e:
        logger.error(f"Error downloading latest release: {str(e)}")
        return None

def process_data() -> bool:
    """
    Process the downloaded data and prepare it for training.
    
    Returns:
        True if processing was successful, False otherwise
    """
    try:
        # Download the data if needed
        data_dir = download_latest_release()
        
        if data_dir is None and os.path.exists(FEATURES_FILE) and os.path.exists(RESULTS_FILE):
            logger.info("Using existing processed data files")
            return True
        
        if data_dir is None:
            logger.error("Failed to download or locate data")
            return False
        
        # Find all parquet files
        parquet_files = []
        for root, dirs, files in os.walk(RAW_DIR):
            for file in files:
                if file.endswith(".parquet"):
                    parquet_files.append(os.path.join(root, file))
        
        if not parquet_files:
            logger.error("No parquet files found in the downloaded data")
            return False
        
        logger.info(f"Found {len(parquet_files)} parquet files")
        
        # Load and process the data
        all_matches = []
        
        for file in parquet_files:
            try:
                # Load the parquet file
                df = pd.read_parquet(file)
                
                # Check if this is a match data file
                if "home_team" in df.columns and "away_team" in df.columns:
                    # Filter for top leagues if desired
                    if len(TOP_LEAGUES) > 0:
                        df = df[df["competition_name"].isin(TOP_LEAGUES)]
                    
                    # Add to the list of matches
                    all_matches.append(df)
            
            except Exception as e:
                logger.warning(f"Error processing {file}: {str(e)}")
        
        if not all_matches:
            logger.error("No valid match data found in the parquet files")
            return False
        
        # Combine all matches
        matches_df = pd.concat(all_matches, ignore_index=True)
        
        # Filter out matches with missing essential data
        matches_df = matches_df.dropna(subset=["home_team", "away_team", "home_score", "away_score", "date"])
        
        logger.info(f"Loaded {len(matches_df)} matches from {len(all_matches)} files")
        
        # Create features and results dataframes
        features_df = create_features_dataframe(matches_df)
        results_df = create_results_dataframe(matches_df)
        
        # Save to parquet files
        features_df.to_parquet(FEATURES_FILE, index=False)
        results_df.to_parquet(RESULTS_FILE, index=False)
        
        logger.info(f"Saved {len(features_df)} matches to {FEATURES_FILE} and {RESULTS_FILE}")
        return True
    
    except Exception as e:
        logger.error(f"Error processing data: {str(e)}")
        return False

def create_features_dataframe(matches_df: pd.DataFrame) -> pd.DataFrame:
    """
    Create a features dataframe from the matches dataframe.
    
    Args:
        matches_df: DataFrame containing match data
        
    Returns:
        DataFrame containing features for training
    """
    # Create a copy to avoid modifying the original
    df = matches_df.copy()
    
    # Create a unique match ID
    df["match_id"] = df.apply(
        lambda row: f"{row['competition_name']}_{row['season']}_{row['date']}_{row['home_team']}_{row['away_team']}",
        axis=1
    )
    
    # Select relevant columns for features
    features = df[["match_id", "date", "home_team", "away_team", "competition_name", "season"]]
    
    # Add additional features if available
    if "home_position" in df.columns and "away_position" in df.columns:
        features["league_position_diff"] = df["home_position"] - df["away_position"]
    else:
        features["league_position_diff"] = 0
    
    # Add placeholder values for features that need to be calculated
    features["home_form"] = 0.5
    features["away_form"] = 0.5
    features["home_attack"] = 0.5
    features["away_attack"] = 0.5
    features["home_defense"] = 0.5
    features["away_defense"] = 0.5
    features["h2h_home_wins"] = 0
    features["h2h_away_wins"] = 0
    features["h2h_draws"] = 0
    
    # Calculate team form, attack, and defense based on previous matches
    features = calculate_team_metrics(features, df)
    
    return features

def create_results_dataframe(matches_df: pd.DataFrame) -> pd.DataFrame:
    """
    Create a results dataframe from the matches dataframe.
    
    Args:
        matches_df: DataFrame containing match data
        
    Returns:
        DataFrame containing results for training
    """
    # Create a copy to avoid modifying the original
    df = matches_df.copy()
    
    # Create a unique match ID
    df["match_id"] = df.apply(
        lambda row: f"{row['competition_name']}_{row['season']}_{row['date']}_{row['home_team']}_{row['away_team']}",
        axis=1
    )
    
    # Create match result
    df["match_result"] = df.apply(
        lambda row: "H" if row["home_score"] > row["away_score"] else "A" if row["home_score"] < row["away_score"] else "D",
        axis=1
    )
    
    # Create over/under 2.5 goals
    df["over_2_5"] = df.apply(
        lambda row: 1 if row["home_score"] + row["away_score"] > 2.5 else 0,
        axis=1
    )
    
    # Create both teams to score
    df["btts"] = df.apply(
        lambda row: 1 if row["home_score"] > 0 and row["away_score"] > 0 else 0,
        axis=1
    )
    
    # Select relevant columns for results
    results = df[["match_id", "date", "home_team", "away_team", "home_score", "away_score", "match_result", "over_2_5", "btts"]]
    
    return results

def calculate_team_metrics(features_df: pd.DataFrame, matches_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate team metrics (form, attack, defense) based on previous matches.
    
    Args:
        features_df: DataFrame containing features
        matches_df: DataFrame containing all matches
        
    Returns:
        DataFrame with updated team metrics
    """
    # Create a copy to avoid modifying the original
    df = features_df.copy()
    
    # Convert date to datetime
    matches_df["date"] = pd.to_datetime(matches_df["date"])
    df["date"] = pd.to_datetime(df["date"])
    
    # Sort by date
    matches_df = matches_df.sort_values("date")
    
    # Calculate team metrics for each match
    for i, row in df.iterrows():
        # Get previous matches for home team
        home_team = row["home_team"]
        match_date = row["date"]
        
        home_previous = matches_df[
            ((matches_df["home_team"] == home_team) | (matches_df["away_team"] == home_team)) &
            (matches_df["date"] < match_date)
        ].tail(10)
        
        # Calculate home team form (win rate in last 10 matches)
        if len(home_previous) > 0:
            home_wins = sum(
                (home_previous["home_team"] == home_team) & (home_previous["home_score"] > home_previous["away_score"]) |
                (home_previous["away_team"] == home_team) & (home_previous["away_score"] > home_previous["home_score"])
            )
            df.at[i, "home_form"] = home_wins / len(home_previous)
            
            # Calculate home team attack (goals scored per match)
            home_goals_scored = sum(
                home_previous[home_previous["home_team"] == home_team]["home_score"].sum() +
                home_previous[home_previous["away_team"] == home_team]["away_score"].sum()
            )
            df.at[i, "home_attack"] = home_goals_scored / len(home_previous) / 2.5
            
            # Calculate home team defense (goals conceded per match)
            home_goals_conceded = sum(
                home_previous[home_previous["home_team"] == home_team]["away_score"].sum() +
                home_previous[home_previous["away_team"] == home_team]["home_score"].sum()
            )
            df.at[i, "home_defense"] = 1 - (home_goals_conceded / len(home_previous) / 2.5)
        
        # Get previous matches for away team
        away_team = row["away_team"]
        
        away_previous = matches_df[
            ((matches_df["home_team"] == away_team) | (matches_df["away_team"] == away_team)) &
            (matches_df["date"] < match_date)
        ].tail(10)
        
        # Calculate away team form (win rate in last 10 matches)
        if len(away_previous) > 0:
            away_wins = sum(
                (away_previous["home_team"] == away_team) & (away_previous["home_score"] > away_previous["away_score"]) |
                (away_previous["away_team"] == away_team) & (away_previous["away_score"] > away_previous["home_score"])
            )
            df.at[i, "away_form"] = away_wins / len(away_previous)
            
            # Calculate away team attack (goals scored per match)
            away_goals_scored = sum(
                away_previous[away_previous["home_team"] == away_team]["home_score"].sum() +
                away_previous[away_previous["away_team"] == away_team]["away_score"].sum()
            )
            df.at[i, "away_attack"] = away_goals_scored / len(away_previous) / 2.5
            
            # Calculate away team defense (goals conceded per match)
            away_goals_conceded = sum(
                away_previous[away_previous["home_team"] == away_team]["away_score"].sum() +
                away_previous[away_previous["away_team"] == away_team]["home_score"].sum()
            )
            df.at[i, "away_defense"] = 1 - (away_goals_conceded / len(away_previous) / 2.5)
        
        # Calculate head-to-head stats
        h2h_matches = matches_df[
            ((matches_df["home_team"] == home_team) & (matches_df["away_team"] == away_team) |
             (matches_df["home_team"] == away_team) & (matches_df["away_team"] == home_team)) &
            (matches_df["date"] < match_date)
        ]
        
        if len(h2h_matches) > 0:
            df.at[i, "h2h_home_wins"] = sum(
                (h2h_matches["home_team"] == home_team) & (h2h_matches["home_score"] > h2h_matches["away_score"]) |
                (h2h_matches["away_team"] == home_team) & (h2h_matches["away_score"] > h2h_matches["home_score"])
            )
            df.at[i, "h2h_away_wins"] = sum(
                (h2h_matches["home_team"] == away_team) & (h2h_matches["home_score"] > h2h_matches["away_score"]) |
                (h2h_matches["away_team"] == away_team) & (h2h_matches["away_score"] > h2h_matches["home_score"])
            )
            df.at[i, "h2h_draws"] = sum(
                h2h_matches["home_score"] == h2h_matches["away_score"]
            )
    
    return df

def main():
    """Main function to download and process football data."""
    logger.info("Starting football data download and processing")
    
    # Create directories if they don't exist
    os.makedirs(HISTORICAL_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    os.makedirs(RAW_DIR, exist_ok=True)
    
    # Process the data
    if process_data():
        logger.info("Football data processing completed successfully")
    else:
        logger.error("Football data processing failed")

if __name__ == "__main__":
    main()
