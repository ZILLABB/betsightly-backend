"""
Convert CSV to Parquet

This script converts the CSV files from the English Football Database to Parquet format.
"""

import os
import pandas as pd
import logging
from datetime import datetime

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
MATCHES_FILE = os.path.join(RAW_DIR, "matches.parquet")

def convert_csv_to_parquet():
    """
    Convert CSV files to Parquet format.
    """
    try:
        # Create directories if they don't exist
        os.makedirs(PROCESSED_DIR, exist_ok=True)
        
        # Convert matches.csv to matches.parquet
        logger.info("Converting matches.csv to Parquet format...")
        matches_csv = os.path.join(RAW_DIR, "matches.csv")
        if os.path.exists(matches_csv):
            matches_df = pd.read_csv(matches_csv)
            matches_df.to_parquet(MATCHES_FILE)
            logger.info(f"Saved {len(matches_df)} matches to {MATCHES_FILE}")
        else:
            logger.error(f"File not found: {matches_csv}")
        
        # Create features and results dataframes
        logger.info("Creating features and results dataframes...")
        if os.path.exists(MATCHES_FILE):
            matches_df = pd.read_parquet(MATCHES_FILE)
            
            # Create features dataframe
            features_df = create_features_dataframe(matches_df)
            features_df.to_parquet(FEATURES_FILE)
            logger.info(f"Saved {len(features_df)} features to {FEATURES_FILE}")
            
            # Create results dataframe
            results_df = create_results_dataframe(matches_df)
            results_df.to_parquet(RESULTS_FILE)
            logger.info(f"Saved {len(results_df)} results to {RESULTS_FILE}")
        else:
            logger.error(f"File not found: {MATCHES_FILE}")
        
        return True
    
    except Exception as e:
        logger.error(f"Error converting CSV to Parquet: {str(e)}")
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
    
    # Convert date to datetime
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])
    
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
    
    # Create match result
    if 'home_score' in df.columns and 'away_score' in df.columns:
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
    results = df[["match_id", "match_result", "over_2_5", "btts", "home_score", "away_score"]]
    
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
            home_goals_scored = (
                home_previous[home_previous["home_team"] == home_team]["home_score"].sum() +
                home_previous[home_previous["away_team"] == home_team]["away_score"].sum()
            )
            df.at[i, "home_attack"] = home_goals_scored / len(home_previous) / 2.5
            
            # Calculate home team defense (goals conceded per match)
            home_goals_conceded = (
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
            away_goals_scored = (
                away_previous[away_previous["home_team"] == away_team]["home_score"].sum() +
                away_previous[away_previous["away_team"] == away_team]["away_score"].sum()
            )
            df.at[i, "away_attack"] = away_goals_scored / len(away_previous) / 2.5
            
            # Calculate away team defense (goals conceded per match)
            away_goals_conceded = (
                away_previous[away_previous["home_team"] == away_team]["away_score"].sum() +
                away_previous[away_previous["away_team"] == away_team]["home_score"].sum()
            )
            df.at[i, "away_defense"] = 1 - (away_goals_conceded / len(away_previous) / 2.5)
        
        # Calculate head-to-head stats
        h2h_matches = matches_df[
            (((matches_df["home_team"] == home_team) & (matches_df["away_team"] == away_team)) |
             ((matches_df["home_team"] == away_team) & (matches_df["away_team"] == home_team))) &
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
    """Main function to convert CSV to Parquet."""
    logger.info("Starting CSV to Parquet conversion")
    
    # Create directories if they don't exist
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    
    # Convert CSV to Parquet
    if convert_csv_to_parquet():
        logger.info("CSV to Parquet conversion completed successfully")
    else:
        logger.error("CSV to Parquet conversion failed")

if __name__ == "__main__":
    main()
