#!/usr/bin/env python3
"""
Train Advanced ML Models Script

This script trains the advanced ML models using the GitHub football dataset.
It uses the advanced feature engineering and confidence calibration for better prediction accuracy.
"""

import os
import sys
import argparse
import logging
import pandas as pd
import numpy as np
import requests
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple, Union

# Add the parent directory to the path so we can import from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ml.model_factory import model_factory
from app.ml.advanced_feature_engineering import AdvancedFootballFeatureEngineer
from app.ml.confidence_calibrator import IsotonicCalibrator
from app.utils.common import setup_logging, ensure_directory_exists
from app.utils.config import settings

# Set up logging
logger = setup_logging(__name__)

# Constants
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "advanced")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")
GITHUB_DATASET_URL = "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data-2000-2025/main/data/Matches.csv"
GITHUB_ELO_URL = "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data-2000-2025/main/data/Elo%20Ratings.csv"

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Train advanced ML models using GitHub football dataset")
    
    parser.add_argument(
        "--leagues",
        type=str,
        default="EPL,La_Liga,Bundesliga,Serie_A,Ligue_1",
        help="Comma-separated list of leagues to include (default: EPL,La_Liga,Bundesliga,Serie_A,Ligue_1)"
    )
    
    parser.add_argument(
        "--start-year",
        type=int,
        default=2018,
        help="Start year for training data (default: 2018)"
    )
    
    parser.add_argument(
        "--end-year",
        type=int,
        default=2025,
        help="End year for training data (default: 2025)"
    )
    
    parser.add_argument(
        "--model-type",
        type=str,
        help="Type of model to train (e.g., xgboost_match_result, lightgbm_btts)"
    )
    
    parser.add_argument(
        "--all",
        action="store_true",
        help="Train all available models"
    )
    
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.2,
        help="Proportion of data to use for testing (default: 0.2)"
    )
    
    parser.add_argument(
        "--optimize",
        action="store_true",
        help="Optimize hyperparameters before training"
    )
    
    return parser.parse_args()

def download_github_dataset():
    """
    Download the football dataset from GitHub.

    Returns:
        DataFrame with football data
    """
    # Build cache path
    cache_dir = os.path.join(DATA_DIR, "github-football")
    ensure_directory_exists(cache_dir)
    cache_file = os.path.join(cache_dir, "Matches.csv")

    # Check if cache exists
    if os.path.exists(cache_file):
        logger.info(f"Using cached GitHub dataset from {cache_file}")
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

def preprocess_data(df: pd.DataFrame, leagues: List[str], start_year: int, end_year: int) -> Tuple[pd.DataFrame, Dict[str, pd.Series]]:
    """
    Preprocess the GitHub football dataset.

    Args:
        df: Raw DataFrame
        leagues: List of leagues to include
        start_year: Start year for training data
        end_year: End year for training data

    Returns:
        Tuple of (features_df, targets_dict)
    """
    try:
        logger.info(f"Preprocessing data for leagues: {leagues}, years: {start_year}-{end_year}")
        
        # Filter by league and year
        filtered_df = df[
            (df['League'].isin(leagues)) &
            (df['Season'].str.contains('|'.join([str(year) for year in range(start_year, end_year + 1)])))
        ]
        
        if filtered_df.empty:
            logger.error(f"No matches found for the specified leagues and years")
            return pd.DataFrame(), {}
        
        logger.info(f"Filtered to {len(filtered_df)} matches")
        
        # Convert date to datetime
        filtered_df['Date'] = pd.to_datetime(filtered_df['Date'], errors='coerce')
        
        # Sort by date
        filtered_df = filtered_df.sort_values('Date')
        
        # Create features DataFrame
        features_df = pd.DataFrame({
            'match_id': filtered_df.index,
            'date': filtered_df['Date'],
            'home_team': filtered_df['Home'],
            'away_team': filtered_df['Away'],
            'league': filtered_df['League'],
            'season': filtered_df['Season'],
            'home_score': filtered_df['HomeGoals'],
            'away_score': filtered_df['AwayGoals']
        })
        
        # Add additional columns if they exist
        if 'HomeXG' in filtered_df.columns:
            features_df['home_xg'] = filtered_df['HomeXG']
        if 'AwayXG' in filtered_df.columns:
            features_df['away_xg'] = filtered_df['AwayXG']
        if 'HomeShots' in filtered_df.columns:
            features_df['home_shots'] = filtered_df['HomeShots']
        if 'AwayShots' in filtered_df.columns:
            features_df['away_shots'] = filtered_df['AwayShots']
        if 'HomeShotsOnTarget' in filtered_df.columns:
            features_df['home_shots_on_target'] = filtered_df['HomeShotsOnTarget']
        if 'AwayShotsOnTarget' in filtered_df.columns:
            features_df['away_shots_on_target'] = filtered_df['AwayShotsOnTarget']
        if 'HomeCorners' in filtered_df.columns:
            features_df['home_corners'] = filtered_df['HomeCorners']
        if 'AwayCorners' in filtered_df.columns:
            features_df['away_corners'] = filtered_df['AwayCorners']
        if 'HomeFouls' in filtered_df.columns:
            features_df['home_fouls'] = filtered_df['HomeFouls']
        if 'AwayFouls' in filtered_df.columns:
            features_df['away_fouls'] = filtered_df['AwayFouls']
        if 'HomeYellowCards' in filtered_df.columns:
            features_df['home_yellow_cards'] = filtered_df['HomeYellowCards']
        if 'AwayYellowCards' in filtered_df.columns:
            features_df['away_yellow_cards'] = filtered_df['AwayYellowCards']
        if 'HomeRedCards' in filtered_df.columns:
            features_df['home_red_cards'] = filtered_df['HomeRedCards']
        if 'AwayRedCards' in filtered_df.columns:
            features_df['away_red_cards'] = filtered_df['AwayRedCards']
        
        # Create target variables
        targets = {}
        
        # Match result (H, D, A)
        targets['match_result'] = pd.Series(
            np.where(filtered_df['HomeGoals'] > filtered_df['AwayGoals'], 'H',
                    np.where(filtered_df['HomeGoals'] < filtered_df['AwayGoals'], 'A', 'D')),
            index=features_df.index
        )
        
        # Over/Under 2.5 goals
        targets['over_2_5'] = pd.Series(
            (filtered_df['HomeGoals'] + filtered_df['AwayGoals']) > 2.5,
            index=features_df.index
        )
        
        # Over/Under 1.5 goals
        targets['over_1_5'] = pd.Series(
            (filtered_df['HomeGoals'] + filtered_df['AwayGoals']) > 1.5,
            index=features_df.index
        )
        
        # Over/Under 3.5 goals
        targets['over_3_5'] = pd.Series(
            (filtered_df['HomeGoals'] + filtered_df['AwayGoals']) > 3.5,
            index=features_df.index
        )
        
        # Both teams to score
        targets['btts'] = pd.Series(
            (filtered_df['HomeGoals'] > 0) & (filtered_df['AwayGoals'] > 0),
            index=features_df.index
        )
        
        # Clean sheet (home and away)
        targets['home_clean_sheet'] = pd.Series(
            filtered_df['AwayGoals'] == 0,
            index=features_df.index
        )
        
        targets['away_clean_sheet'] = pd.Series(
            filtered_df['HomeGoals'] == 0,
            index=features_df.index
        )
        
        # Win to nil (home and away)
        targets['home_win_to_nil'] = pd.Series(
            (filtered_df['HomeGoals'] > 0) & (filtered_df['AwayGoals'] == 0),
            index=features_df.index
        )
        
        targets['away_win_to_nil'] = pd.Series(
            (filtered_df['HomeGoals'] == 0) & (filtered_df['AwayGoals'] > 0),
            index=features_df.index
        )
        
        logger.info(f"Created features and targets for {len(features_df)} matches")
        
        return features_df, targets
        
    except Exception as e:
        logger.error(f"Error preprocessing data: {str(e)}")
        return pd.DataFrame(), {}

def train_model(model_type: str, features_df: pd.DataFrame, targets: Dict[str, pd.Series], optimize: bool = False) -> Dict[str, Any]:
    """
    Train a model.

    Args:
        model_type: Type of model to train
        features_df: Features DataFrame
        targets: Dictionary of target variables
        optimize: Whether to optimize hyperparameters

    Returns:
        Dictionary with training results
    """
    try:
        # Select appropriate target based on model type
        if "match_result" in model_type:
            target = targets["match_result"]
        elif "over_under_1_5" in model_type:
            target = targets["over_1_5"]
        elif "over_under_3_5" in model_type:
            target = targets["over_3_5"]
        elif "over_under" in model_type:
            target = targets["over_2_5"]
        elif "btts" in model_type:
            target = targets["btts"]
        elif "clean_sheet" in model_type:
            target = targets["home_clean_sheet"]  # Default to home
        elif "win_to_nil" in model_type:
            target = targets["home_win_to_nil"]  # Default to home
        else:
            # Default to match result
            target = targets["match_result"]
        
        # Get model from factory
        model = model_factory.get_model(model_type)
        
        if model is None:
            logger.error(f"Model type {model_type} not found")
            return {"status": "error", "message": f"Model type {model_type} not found"}
        
        # Optimize hyperparameters if requested
        if optimize and hasattr(model, 'optimize_hyperparameters'):
            logger.info(f"Optimizing hyperparameters for {model_type}")
            optimization_result = model.optimize_hyperparameters(features_df, target)
            logger.info(f"Optimization result: {optimization_result}")
        
        # Train model
        logger.info(f"Training model {model_type}")
        result = model.train(features_df, target)
        
        logger.info(f"Training result: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Error training model {model_type}: {str(e)}")
        return {"status": "error", "message": str(e)}

def main():
    """Main function."""
    # Parse arguments
    args = parse_arguments()
    
    # Ensure directories exist
    ensure_directory_exists(DATA_DIR)
    ensure_directory_exists(MODELS_DIR)
    ensure_directory_exists(RESULTS_DIR)
    
    # Download data
    df = download_github_dataset()
    
    if df.empty:
        logger.error("Failed to download dataset")
        return
    
    # Preprocess data
    leagues = args.leagues.split(',')
    features_df, targets = preprocess_data(df, leagues, args.start_year, args.end_year)
    
    if features_df.empty:
        logger.error("Failed to preprocess data")
        return
    
    # Initialize feature engineer with historical data
    feature_engineer = AdvancedFootballFeatureEngineer()
    feature_engineer.set_historical_data(features_df)
    
    # Train models
    if args.all:
        # Train all models
        for model_type in model_factory.get_available_models():
            train_model(model_type, features_df, targets, args.optimize)
    elif args.model_type:
        # Train specific model
        train_model(args.model_type, features_df, targets, args.optimize)
    else:
        logger.error("No model type specified. Use --model-type or --all")
        return
    
    logger.info("Model training complete")

if __name__ == "__main__":
    main()
