#!/usr/bin/env python3
"""
Evaluate ML Models on Historical Data

This script evaluates the trained ML models on historical data to assess their performance.
"""

import os
import sys
import pandas as pd
import numpy as np
import logging
import joblib
from datetime import datetime
import argparse
from typing import Dict, List, Tuple, Any, Union
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix, classification_report
import matplotlib.pyplot as plt
import seaborn as sns

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "enhanced")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")
GITHUB_DATASET_URL = "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data-2000-2025/main/data/Matches.csv"

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Evaluate ML models on historical data")

    parser.add_argument(
        "--leagues",
        type=str,
        default="E0,SP1,I1,D1,F1",
        help="Comma-separated list of leagues to evaluate"
    )

    parser.add_argument(
        "--start_year",
        type=int,
        default=2023,
        help="Start year for evaluation data (default: 2023)"
    )

    parser.add_argument(
        "--end_year",
        type=int,
        default=2024,
        help="End year for evaluation data (default: 2024)"
    )

    parser.add_argument(
        "--output",
        type=str,
        default="evaluation_results.csv",
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
        return pd.read_csv(cache_file, low_memory=False)
    else:
        logger.error(f"GitHub dataset not found at {cache_file}. Please run train_github_models.py first.")
        return pd.DataFrame()

def preprocess_evaluation_data(df, leagues, start_year, end_year):
    """
    Preprocess the GitHub dataset for evaluation.

    Args:
        df: DataFrame with football data
        leagues: List of leagues to include
        start_year: Start year for evaluation data
        end_year: End year for evaluation data

    Returns:
        Tuple of (X, y_match_result, y_over_under, y_btts)
    """
    # Filter by leagues
    leagues_list = leagues.split(",")
    df = df[df["Division"].isin(leagues_list)]

    # Filter by date
    df["MatchDate"] = pd.to_datetime(df["MatchDate"])
    df = df[(df["MatchDate"].dt.year >= start_year) & (df["MatchDate"].dt.year <= end_year)]

    # Drop rows with missing values in key columns
    required_columns = ["HomeTeam", "AwayTeam", "FTHome", "FTAway", "FTResult"]
    df = df.dropna(subset=required_columns)

    # Create features DataFrame
    features = []

    for _, match in df.iterrows():
        # Create feature dictionary
        feature_dict = {
            # Team information
            "home_team": match["HomeTeam"],
            "away_team": match["AwayTeam"],
            "league": match["Division"],
            "match_date": match["MatchDate"],

            # Form features
            "home_form": match["Form5Home"] / 15 if not pd.isna(match["Form5Home"]) else 0.5,
            "away_form": match["Form5Away"] / 15 if not pd.isna(match["Form5Away"]) else 0.5,

            # Elo ratings
            "home_elo": match["HomeElo"] / 2000 if not pd.isna(match["HomeElo"]) else 0.5,
            "away_elo": match["AwayElo"] / 2000 if not pd.isna(match["AwayElo"]) else 0.5,
            "elo_diff": (match["HomeElo"] - match["AwayElo"]) / 500 if not pd.isna(match["HomeElo"]) and not pd.isna(match["AwayElo"]) else 0,

            # Odds features (if available)
            "home_odds": match["OddHome"] if not pd.isna(match["OddHome"]) else 0,
            "draw_odds": match["OddDraw"] if not pd.isna(match["OddDraw"]) else 0,
            "away_odds": match["OddAway"] if not pd.isna(match["OddAway"]) else 0,

            # Derived features
            "home_win_prob": 1/match["OddHome"] if not pd.isna(match["OddHome"]) and match["OddHome"] > 0 else 0.33,
            "draw_prob": 1/match["OddDraw"] if not pd.isna(match["OddDraw"]) and match["OddDraw"] > 0 else 0.33,
            "away_win_prob": 1/match["OddAway"] if not pd.isna(match["OddAway"]) and match["OddAway"] > 0 else 0.33,

            # Enhanced features - Over/Under odds
            "over_odds": match["Over25"] if not pd.isna(match["Over25"]) else 1.9,
            "under_odds": match["Under25"] if not pd.isna(match["Under25"]) else 1.9,

            # Enhanced features - Asian Handicap
            "handi_size": match["HandiSize"] if not pd.isna(match["HandiSize"]) else 0,
            "handi_home": match["HandiHome"] if not pd.isna(match["HandiHome"]) else 1.9,
            "handi_away": match["HandiAway"] if not pd.isna(match["HandiAway"]) else 1.9,

            # Target variables
            "match_result": match["FTResult"],
            "over_2_5": 1 if match["FTHome"] + match["FTAway"] > 2.5 else 0,
            "btts": 1 if match["FTHome"] > 0 and match["FTAway"] > 0 else 0,

            # Actual scores
            "home_goals": match["FTHome"],
            "away_goals": match["FTAway"]
        }

        # Add additional features if available
        for col in ["Form3Home", "Form3Away", "HomeShots", "AwayShots", "HomeTarget", "AwayTarget",
                   "HomeFouls", "AwayFouls", "HomeCorners", "AwayCorners", "HomeYellow", "AwayYellow",
                   "HomeRed", "AwayRed"]:
            if col in match and not pd.isna(match[col]):
                # Normalize the values
                if "Form" in col:
                    feature_dict[col.lower()] = match[col] / 9  # Max form3 is 9 points
                elif "Shots" in col or "Target" in col:
                    feature_dict[col.lower()] = match[col] / 30  # Normalize shots
                elif "Fouls" in col:
                    feature_dict[col.lower()] = match[col] / 20  # Normalize fouls
                elif "Corners" in col:
                    feature_dict[col.lower()] = match[col] / 15  # Normalize corners
                elif "Yellow" in col or "Red" in col:
                    feature_dict[col.lower()] = match[col] / 5  # Normalize cards
                else:
                    feature_dict[col.lower()] = match[col]

        features.append(feature_dict)

    # Create DataFrame
    features_df = pd.DataFrame(features)

    # Handle missing values
    features_df = features_df.fillna(0)

    return features_df

def evaluate_models(evaluation_df):
    """
    Evaluate models on historical data.

    Args:
        evaluation_df: DataFrame with evaluation data

    Returns:
        DataFrame with evaluation results
    """
    logger.info("Evaluating models on historical data...")

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
    feature_columns = [col for col in evaluation_df.columns if col not in [
        "home_team", "away_team", "league", "match_date",
        "match_result", "over_2_5", "btts", "home_goals", "away_goals"
    ]]

    # Make predictions
    match_result_probs = match_result_model.predict_proba(evaluation_df[feature_columns])
    over_under_probs = over_under_model.predict_proba(evaluation_df[feature_columns])
    btts_probs = btts_model.predict_proba(evaluation_df[feature_columns])

    # Add predictions to evaluation DataFrame
    results_df = evaluation_df.copy()

    # Match result predictions
    results_df["home_win_pred"] = match_result_probs[:, 0]
    results_df["draw_pred"] = match_result_probs[:, 1]
    results_df["away_win_pred"] = match_result_probs[:, 2]

    # Over/under predictions
    results_df["under_2_5_pred"] = over_under_probs[:, 0]
    results_df["over_2_5_pred"] = over_under_probs[:, 1]

    # BTTS predictions
    results_df["btts_no_pred"] = btts_probs[:, 0]
    results_df["btts_yes_pred"] = btts_probs[:, 1]

    # Get predicted outcomes
    results_df["match_result_pred"] = np.argmax(match_result_probs, axis=1)
    results_df["match_result_pred"] = results_df["match_result_pred"].map({0: "H", 1: "D", 2: "A"})

    results_df["over_under_pred"] = np.argmax(over_under_probs, axis=1)
    results_df["over_under_pred"] = results_df["over_under_pred"].map({0: "Under", 1: "Over"})

    results_df["btts_pred"] = np.argmax(btts_probs, axis=1)
    results_df["btts_pred"] = results_df["btts_pred"].map({0: "No", 1: "Yes"})

    # Calculate accuracy
    match_result_accuracy = (results_df["match_result_pred"] == results_df["match_result"]).mean()

    # Create actual over/under and btts results
    results_df["over_under_actual"] = results_df["over_2_5"].apply(lambda x: "Over" if x == 1 else "Under")
    results_df["btts_actual"] = results_df["btts"].apply(lambda x: "Yes" if x == 1 else "No")

    over_under_accuracy = (results_df["over_under_pred"] == results_df["over_under_actual"]).mean()
    btts_accuracy = (results_df["btts_pred"] == results_df["btts_actual"]).mean()

    logger.info(f"Match result accuracy: {match_result_accuracy:.4f}")
    logger.info(f"Over/under accuracy: {over_under_accuracy:.4f}")
    logger.info(f"BTTS accuracy: {btts_accuracy:.4f}")

    # Calculate metrics by league
    league_metrics = []

    for league in results_df["league"].unique():
        league_df = results_df[results_df["league"] == league]

        league_match_result_accuracy = (league_df["match_result_pred"] == league_df["match_result"]).mean()
        league_over_under_accuracy = (league_df["over_under_pred"] == league_df["over_under_actual"]).mean()
        league_btts_accuracy = (league_df["btts_pred"] == league_df["btts_actual"]).mean()

        league_metrics.append({
            "league": league,
            "match_count": len(league_df),
            "match_result_accuracy": league_match_result_accuracy,
            "over_under_accuracy": league_over_under_accuracy,
            "btts_accuracy": league_btts_accuracy
        })

    league_metrics_df = pd.DataFrame(league_metrics)
    logger.info("\nAccuracy by league:")
    logger.info(league_metrics_df.to_string(index=False))

    # Calculate metrics by confidence level
    results_df["match_result_confidence"] = results_df[["home_win_pred", "draw_pred", "away_win_pred"]].max(axis=1)
    results_df["over_under_confidence"] = results_df[["under_2_5_pred", "over_2_5_pred"]].max(axis=1)
    results_df["btts_confidence"] = results_df[["btts_no_pred", "btts_yes_pred"]].max(axis=1)

    # Create confidence bins
    results_df["match_result_confidence_bin"] = pd.cut(results_df["match_result_confidence"], bins=[0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0], labels=["0-50%", "50-60%", "60-70%", "70-80%", "80-90%", "90-100%"])
    results_df["over_under_confidence_bin"] = pd.cut(results_df["over_under_confidence"], bins=[0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0], labels=["0-50%", "50-60%", "60-70%", "70-80%", "80-90%", "90-100%"])
    results_df["btts_confidence_bin"] = pd.cut(results_df["btts_confidence"], bins=[0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0], labels=["0-50%", "50-60%", "60-70%", "70-80%", "80-90%", "90-100%"])

    # Calculate metrics by confidence bin
    confidence_metrics = []

    for bin_label in ["0-50%", "50-60%", "60-70%", "70-80%", "80-90%", "90-100%"]:
        # Match result
        bin_df = results_df[results_df["match_result_confidence_bin"] == bin_label]
        if len(bin_df) > 0:
            bin_accuracy = (bin_df["match_result_pred"] == bin_df["match_result"]).mean()
            confidence_metrics.append({
                "prediction_type": "Match Result",
                "confidence_bin": bin_label,
                "match_count": len(bin_df),
                "accuracy": bin_accuracy
            })

        # Over/under
        bin_df = results_df[results_df["over_under_confidence_bin"] == bin_label]
        if len(bin_df) > 0:
            bin_accuracy = (bin_df["over_under_pred"] == bin_df["over_under_actual"]).mean()
            confidence_metrics.append({
                "prediction_type": "Over/Under",
                "confidence_bin": bin_label,
                "match_count": len(bin_df),
                "accuracy": bin_accuracy
            })

        # BTTS
        bin_df = results_df[results_df["btts_confidence_bin"] == bin_label]
        if len(bin_df) > 0:
            bin_accuracy = (bin_df["btts_pred"] == bin_df["btts_actual"]).mean()
            confidence_metrics.append({
                "prediction_type": "BTTS",
                "confidence_bin": bin_label,
                "match_count": len(bin_df),
                "accuracy": bin_accuracy
            })

    confidence_metrics_df = pd.DataFrame(confidence_metrics)
    logger.info("\nAccuracy by confidence level:")
    logger.info(confidence_metrics_df.to_string(index=False))

    return results_df, league_metrics_df, confidence_metrics_df

def main():
    """Main function."""
    # Parse arguments
    args = parse_arguments()

    # Ensure directories exist
    ensure_directory_exists(RESULTS_DIR)

    # Load GitHub dataset
    github_df = load_github_dataset()

    if github_df.empty:
        logger.error("Failed to load GitHub dataset")
        return

    # Preprocess evaluation data
    evaluation_df = preprocess_evaluation_data(github_df, args.leagues, args.start_year, args.end_year)

    if evaluation_df.empty:
        logger.error("Failed to preprocess evaluation data")
        return

    # Evaluate models
    results_df, league_metrics_df, confidence_metrics_df = evaluate_models(evaluation_df)

    if results_df.empty:
        logger.error("Failed to evaluate models")
        return

    # Save results
    results_path = os.path.join(RESULTS_DIR, args.output)
    results_df.to_csv(results_path, index=False)

    league_metrics_path = os.path.join(RESULTS_DIR, f"league_metrics_{args.start_year}_{args.end_year}.csv")
    league_metrics_df.to_csv(league_metrics_path, index=False)

    confidence_metrics_path = os.path.join(RESULTS_DIR, f"confidence_metrics_{args.start_year}_{args.end_year}.csv")
    confidence_metrics_df.to_csv(confidence_metrics_path, index=False)

    logger.info(f"Evaluation results saved to {results_path}")
    logger.info(f"League metrics saved to {league_metrics_path}")
    logger.info(f"Confidence metrics saved to {confidence_metrics_path}")

if __name__ == "__main__":
    main()
