#!/usr/bin/env python
"""
Train Advanced ML Models

This script trains and evaluates the advanced ML models for football prediction.
It supports XGBoost, LightGBM, Neural Networks, and LSTM models.
"""

import os
import sys
import argparse
import logging
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Any, Tuple

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ml.model_factory import model_factory
from app.utils.common import setup_logging, ensure_directory_exists
from app.utils.config import settings

# Set up logging
logger = setup_logging("train_advanced_models")

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Train advanced ML models for football prediction")
    
    parser.add_argument(
        "--model-type",
        type=str,
        choices=model_factory.get_available_models(),
        help="Type of model to train"
    )
    
    parser.add_argument(
        "--data-file",
        type=str,
        default="data/processed/football_matches.csv",
        help="Path to processed data file"
    )
    
    parser.add_argument(
        "--leagues",
        type=str,
        default="E0,E1,SP1,D1,I1,F1",
        help="Comma-separated list of leagues to include"
    )
    
    parser.add_argument(
        "--start-year",
        type=int,
        default=2018,
        help="Start year for training data"
    )
    
    parser.add_argument(
        "--end-year",
        type=int,
        default=2023,
        help="End year for training data"
    )
    
    parser.add_argument(
        "--all",
        action="store_true",
        help="Train all available models"
    )
    
    return parser.parse_args()

def load_data(data_file: str, leagues: str, start_year: int, end_year: int) -> pd.DataFrame:
    """
    Load and preprocess data for training.
    
    Args:
        data_file: Path to data file
        leagues: Comma-separated list of leagues
        start_year: Start year for filtering
        end_year: End year for filtering
        
    Returns:
        Preprocessed DataFrame
    """
    logger.info(f"Loading data from {data_file}")
    
    try:
        # Load data
        df = pd.read_csv(data_file)
        
        # Filter by leagues if specified
        if leagues:
            league_list = leagues.split(",")
            df = df[df["Division"].isin(league_list)]
            
        # Filter by date if year columns exist
        if "Season" in df.columns:
            df = df[(df["Season"] >= start_year) & (df["Season"] <= end_year)]
        elif "MatchDate" in df.columns:
            df["MatchDate"] = pd.to_datetime(df["MatchDate"])
            df = df[(df["MatchDate"].dt.year >= start_year) & (df["MatchDate"].dt.year <= end_year)]
            
        logger.info(f"Loaded {len(df)} matches after filtering")
        return df
        
    except Exception as e:
        logger.error(f"Error loading data: {str(e)}")
        return pd.DataFrame()

def preprocess_data(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, pd.Series]]:
    """
    Preprocess data for model training.
    
    Args:
        df: Raw DataFrame
        
    Returns:
        Tuple of (features_df, targets_dict)
    """
    logger.info("Preprocessing data for model training")
    
    try:
        # Create features DataFrame
        features = []
        
        for _, match in df.iterrows():
            # Create feature dictionary
            feature_dict = {
                # Team information
                "home_team": match.get("HomeTeam", "Unknown"),
                "away_team": match.get("AwayTeam", "Unknown"),
                
                # Form features (normalize to 0-1 range)
                "home_form": match.get("Form5Home", 0) / 15 if "Form5Home" in match and not pd.isna(match["Form5Home"]) else 0.5,
                "away_form": match.get("Form5Away", 0) / 15 if "Form5Away" in match and not pd.isna(match["Form5Away"]) else 0.5,
                
                # Team strength
                "home_attack": match.get("HomeAttackStrength", 0.5),
                "away_attack": match.get("AwayAttackStrength", 0.5),
                "home_defense": match.get("HomeDefenseStrength", 0.5),
                "away_defense": match.get("AwayDefenseStrength", 0.5),
                
                # Head-to-head
                "h2h_home_wins": match.get("H2HHomeWins", 0) / 5 if "H2HHomeWins" in match and not pd.isna(match["H2HHomeWins"]) else 0.5,
                "h2h_away_wins": match.get("H2HAwayWins", 0) / 5 if "H2HAwayWins" in match and not pd.isna(match["H2HAwayWins"]) else 0.5,
                "h2h_draws": match.get("H2HDraws", 0) / 5 if "H2HDraws" in match and not pd.isna(match["H2HDraws"]) else 0.5,
                
                # League position
                "league_position_diff": (match.get("HomePosition", 10) - match.get("AwayPosition", 10)) / 20 if "HomePosition" in match and "AwayPosition" in match else 0,
                
                # Odds features (if available)
                "home_odds": match.get("OddHome", 2.5) if "OddHome" in match and not pd.isna(match["OddHome"]) else 2.5,
                "draw_odds": match.get("OddDraw", 3.5) if "OddDraw" in match and not pd.isna(match["OddDraw"]) else 3.5,
                "away_odds": match.get("OddAway", 3.0) if "OddAway" in match and not pd.isna(match["OddAway"]) else 3.0,
                
                # Derived features
                "home_win_prob": 1/match.get("OddHome", 3) if "OddHome" in match and not pd.isna(match["OddHome"]) and match["OddHome"] > 0 else 0.33,
                "draw_prob": 1/match.get("OddDraw", 3) if "OddDraw" in match and not pd.isna(match["OddDraw"]) and match["OddDraw"] > 0 else 0.33,
                "away_win_prob": 1/match.get("OddAway", 3) if "OddAway" in match and not pd.isna(match["OddAway"]) and match["OddAway"] > 0 else 0.33,
            }
            
            # Add match ID if available
            if "match_id" in match:
                feature_dict["match_id"] = match["match_id"]
            elif "ID" in match:
                feature_dict["match_id"] = match["ID"]
            else:
                feature_dict["match_id"] = f"{match.get('HomeTeam', 'home')}_{match.get('AwayTeam', 'away')}_{match.get('MatchDate', datetime.now().strftime('%Y-%m-%d'))}"
            
            # Add target variables
            # Match result
            if "FTR" in match:
                feature_dict["match_result"] = match["FTR"]
            elif "FTResult" in match:
                feature_dict["match_result"] = match["FTResult"]
            else:
                # Try to derive from goals
                home_goals = match.get("FTHG", match.get("FTHome", 0))
                away_goals = match.get("FTAG", match.get("FTAway", 0))
                
                if home_goals > away_goals:
                    feature_dict["match_result"] = "H"
                elif away_goals > home_goals:
                    feature_dict["match_result"] = "A"
                else:
                    feature_dict["match_result"] = "D"
            
            # Over/Under 2.5
            home_goals = match.get("FTHG", match.get("FTHome", 0))
            away_goals = match.get("FTAG", match.get("FTAway", 0))
            total_goals = home_goals + away_goals
            
            feature_dict["over_2_5"] = 1 if total_goals > 2.5 else 0
            feature_dict["over_1_5"] = 1 if total_goals > 1.5 else 0
            feature_dict["over_3_5"] = 1 if total_goals > 3.5 else 0
            
            # BTTS
            feature_dict["btts"] = 1 if home_goals > 0 and away_goals > 0 else 0
            
            # Clean sheet
            feature_dict["home_clean_sheet"] = 1 if away_goals == 0 else 0
            feature_dict["away_clean_sheet"] = 1 if home_goals == 0 else 0
            
            # Win to nil
            feature_dict["home_win_to_nil"] = 1 if home_goals > 0 and away_goals == 0 else 0
            feature_dict["away_win_to_nil"] = 1 if away_goals > 0 and home_goals == 0 else 0
            
            features.append(feature_dict)
        
        # Create DataFrame
        features_df = pd.DataFrame(features)
        
        # Handle missing values
        features_df = features_df.fillna(0)
        
        # Create target variables
        targets = {
            "match_result": features_df["match_result"].map({"H": 0, "D": 1, "A": 2}),
            "over_2_5": features_df["over_2_5"],
            "over_1_5": features_df["over_1_5"],
            "over_3_5": features_df["over_3_5"],
            "btts": features_df["btts"],
            "home_clean_sheet": features_df["home_clean_sheet"],
            "away_clean_sheet": features_df["away_clean_sheet"],
            "home_win_to_nil": features_df["home_win_to_nil"],
            "away_win_to_nil": features_df["away_win_to_nil"]
        }
        
        # Select feature columns
        feature_cols = [col for col in features_df.columns if col not in list(targets.keys()) + ["match_id"]]
        
        logger.info(f"Preprocessed data with {len(features_df)} samples and {len(feature_cols)} features")
        logger.info(f"Feature columns: {feature_cols}")
        
        return features_df[feature_cols], targets
        
    except Exception as e:
        logger.error(f"Error preprocessing data: {str(e)}")
        return pd.DataFrame(), {}

def train_model(model_type: str, features_df: pd.DataFrame, targets: Dict[str, pd.Series]) -> Dict[str, Any]:
    """
    Train a model of the specified type.
    
    Args:
        model_type: Type of model to train
        features_df: Features DataFrame
        targets: Dictionary of target Series
        
    Returns:
        Dictionary with training results
    """
    logger.info(f"Training {model_type} model")
    
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
        
        # Train model
        result = model_factory.train_model(model_type, features_df, target)
        
        logger.info(f"Training result: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Error training {model_type} model: {str(e)}")
        return {
            "status": "error",
            "message": f"Error training {model_type} model: {str(e)}"
        }

def main():
    """Main function."""
    args = parse_args()
    
    # Load data
    df = load_data(args.data_file, args.leagues, args.start_year, args.end_year)
    
    if df.empty:
        logger.error("Failed to load data")
        return
    
    # Preprocess data
    features_df, targets = preprocess_data(df)
    
    if features_df.empty:
        logger.error("Failed to preprocess data")
        return
    
    # Train models
    if args.all:
        # Train all models
        for model_type in model_factory.get_available_models():
            train_model(model_type, features_df, targets)
    elif args.model_type:
        # Train specific model
        train_model(args.model_type, features_df, targets)
    else:
        logger.error("No model type specified. Use --model-type or --all")
        return
    
    logger.info("Model training complete")

if __name__ == "__main__":
    main()
