"""
Prepare Football Data

This script prepares the football data from the English Football Database for ML training.
It creates simplified features and results dataframes without complex feature engineering.
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

def prepare_data():
    """
    Prepare the football data for ML training.
    """
    try:
        # Create directories if they don't exist
        os.makedirs(PROCESSED_DIR, exist_ok=True)
        
        # Load matches data
        logger.info("Loading matches data...")
        matches_csv = os.path.join(RAW_DIR, "matches.csv")
        if os.path.exists(matches_csv):
            matches_df = pd.read_csv(matches_csv, low_memory=False)
            logger.info(f"Loaded {len(matches_df)} matches")
        else:
            logger.error(f"File not found: {matches_csv}")
            return False
        
        # Create features dataframe
        logger.info("Creating features dataframe...")
        features_df = create_features_dataframe(matches_df)
        features_df.to_parquet(FEATURES_FILE)
        logger.info(f"Saved {len(features_df)} features to {FEATURES_FILE}")
        
        # Create results dataframe
        logger.info("Creating results dataframe...")
        results_df = create_results_dataframe(matches_df)
        results_df.to_parquet(RESULTS_FILE)
        logger.info(f"Saved {len(results_df)} results to {RESULTS_FILE}")
        
        return True
    
    except Exception as e:
        logger.error(f"Error preparing data: {str(e)}")
        return False

def create_features_dataframe(matches_df):
    """
    Create a simplified features dataframe from the matches dataframe.
    
    Args:
        matches_df: DataFrame containing match data
        
    Returns:
        DataFrame containing features for training
    """
    # Create a copy to avoid modifying the original
    df = matches_df.copy()
    
    # Create features dataframe
    features = pd.DataFrame()
    features['match_id'] = df['match_id']
    features['season'] = df['season']
    features['tier'] = df['tier']
    features['division'] = df['division']
    features['home_team'] = df['home_team_name']
    features['away_team'] = df['away_team_name']
    
    # Add some basic features
    features['home_team_id'] = df['home_team_id']
    features['away_team_id'] = df['away_team_id']
    
    # Add dummy features for ML training
    features['home_form'] = 0.5
    features['away_form'] = 0.5
    features['home_attack'] = 0.5
    features['away_attack'] = 0.5
    features['home_defense'] = 0.5
    features['away_defense'] = 0.5
    
    return features

def create_results_dataframe(matches_df):
    """
    Create a results dataframe from the matches dataframe.
    
    Args:
        matches_df: DataFrame containing match data
        
    Returns:
        DataFrame containing results for training
    """
    # Create a copy to avoid modifying the original
    df = matches_df.copy()
    
    # Create results dataframe
    results = pd.DataFrame()
    results['match_id'] = df['match_id']
    results['home_score'] = df['home_team_score']
    results['away_score'] = df['away_team_score']
    
    # Create match result
    results["match_result"] = df.apply(
        lambda row: "H" if row["home_team_score"] > row["away_team_score"] else "A" if row["home_team_score"] < row["away_team_score"] else "D",
        axis=1
    )
    
    # Create over/under 2.5 goals
    results["over_2_5"] = df.apply(
        lambda row: 1 if row["home_team_score"] + row["away_team_score"] > 2.5 else 0,
        axis=1
    )
    
    # Create both teams to score
    results["btts"] = df.apply(
        lambda row: 1 if row["home_team_score"] > 0 and row["away_team_score"] > 0 else 0,
        axis=1
    )
    
    return results

def main():
    """Main function to prepare football data."""
    logger.info("Starting football data preparation")
    
    # Prepare data
    if prepare_data():
        logger.info("Football data preparation completed successfully")
    else:
        logger.error("Football data preparation failed")

if __name__ == "__main__":
    main()
