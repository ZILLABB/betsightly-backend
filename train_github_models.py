#!/usr/bin/env python3
"""
Train Advanced ML Models using GitHub Football Dataset

This script trains advanced machine learning models for football match prediction
using the Club-Football-Match-Data-2000-2025 dataset from GitHub.
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
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, StackingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix
from sklearn.pipeline import Pipeline
import matplotlib.pyplot as plt
import seaborn as sns
from io import BytesIO

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "advanced")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")
GITHUB_DATASET_URL = "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data-2000-2025/main/data/Matches.csv"
GITHUB_ELO_URL = "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data-2000-2025/main/data/Elo%20Ratings.csv"

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Train advanced ML models for football prediction")

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force retraining even if models already exist"
    )

    parser.add_argument(
        "--leagues",
        type=str,
        default="E0,E1,SP1,I1,D1,F1",
        help="Comma-separated list of leagues to use for training"
    )

    parser.add_argument(
        "--start_year",
        type=int,
        default=2018,
        help="Start year for training data (default: 2018)"
    )

    parser.add_argument(
        "--end_year",
        type=int,
        default=2024,
        help="End year for training data (default: 2024)"
    )

    return parser.parse_args()

def ensure_directory_exists(directory):
    """Ensure a directory exists."""
    os.makedirs(directory, exist_ok=True)

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
        return pd.read_csv(cache_file)

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
        df = pd.read_csv(cache_file)

        logger.info(f"Downloaded {len(df)} matches from GitHub")
        return df

    except Exception as e:
        logger.error(f"Error downloading dataset: {str(e)}")
        return pd.DataFrame()

def preprocess_github_data(df, leagues, start_year, end_year):
    """
    Preprocess the GitHub football dataset.

    Args:
        df: DataFrame with football data
        leagues: List of leagues to include
        start_year: Start year for training data
        end_year: End year for training data

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

            # Target variables
            "match_result": match["FTResult"],
            "over_2_5": 1 if match["FTHome"] + match["FTAway"] > 2.5 else 0,
            "btts": 1 if match["FTHome"] > 0 and match["FTAway"] > 0 else 0
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

    # Create feature matrix and target variables
    X_columns = [col for col in features_df.columns if col not in ['match_result', 'over_2_5', 'btts', 'home_team', 'away_team']]
    X = features_df[X_columns]

    # Convert match result to numeric
    y_match_result = features_df['match_result'].map({'H': 0, 'D': 1, 'A': 2})
    y_over_under = features_df['over_2_5']
    y_btts = features_df['btts']

    logger.info(f"Preprocessed {len(features_df)} matches")
    logger.info(f"Feature columns: {X_columns}")

    return X, y_match_result, y_over_under, y_btts

def train_match_result_model(X, y):
    """
    Train an advanced match result model.

    Args:
        X: Feature matrix
        y: Target variable

    Returns:
        Trained model and evaluation metrics
    """
    logger.info("Training match result model...")

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Create pipeline
    pipeline = Pipeline([
        ('scaler', StandardScaler()),
        ('model', RandomForestClassifier(n_estimators=200, max_depth=15, random_state=42, n_jobs=-1))
    ])

    # Train model
    pipeline.fit(X_train, y_train)

    # Evaluate model
    y_pred = pipeline.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    precision = precision_score(y_test, y_pred, average='weighted')
    recall = recall_score(y_test, y_pred, average='weighted')
    f1 = f1_score(y_test, y_pred, average='weighted')

    # Create confusion matrix
    cm = confusion_matrix(y_test, y_pred)

    logger.info(f"Match result model accuracy: {accuracy:.4f}")
    logger.info(f"Match result model precision: {precision:.4f}")
    logger.info(f"Match result model recall: {recall:.4f}")
    logger.info(f"Match result model F1 score: {f1:.4f}")

    # Save model
    model_path = os.path.join(MODELS_DIR, "match_result_model.joblib")
    joblib.dump(pipeline, model_path)

    logger.info(f"Match result model saved to {model_path}")

    return pipeline, {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "confusion_matrix": cm
    }

def train_over_under_model(X, y):
    """
    Train an advanced over/under model.

    Args:
        X: Feature matrix
        y: Target variable

    Returns:
        Trained model and evaluation metrics
    """
    logger.info("Training over/under model...")

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Create pipeline
    pipeline = Pipeline([
        ('scaler', StandardScaler()),
        ('model', GradientBoostingClassifier(n_estimators=200, max_depth=8, random_state=42))
    ])

    # Train model
    pipeline.fit(X_train, y_train)

    # Evaluate model
    y_pred = pipeline.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    precision = precision_score(y_test, y_pred)
    recall = recall_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred)

    # Create confusion matrix
    cm = confusion_matrix(y_test, y_pred)

    logger.info(f"Over/under model accuracy: {accuracy:.4f}")
    logger.info(f"Over/under model precision: {precision:.4f}")
    logger.info(f"Over/under model recall: {recall:.4f}")
    logger.info(f"Over/under model F1 score: {f1:.4f}")

    # Save model
    model_path = os.path.join(MODELS_DIR, "over_under_model.joblib")
    joblib.dump(pipeline, model_path)

    logger.info(f"Over/under model saved to {model_path}")

    return pipeline, {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "confusion_matrix": cm
    }

def train_btts_model(X, y):
    """
    Train an advanced BTTS model.

    Args:
        X: Feature matrix
        y: Target variable

    Returns:
        Trained model and evaluation metrics
    """
    logger.info("Training BTTS model...")

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Create pipeline
    pipeline = Pipeline([
        ('scaler', StandardScaler()),
        ('model', LogisticRegression(C=1.0, max_iter=1000, random_state=42, n_jobs=-1))
    ])

    # Train model
    pipeline.fit(X_train, y_train)

    # Evaluate model
    y_pred = pipeline.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    precision = precision_score(y_test, y_pred)
    recall = recall_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred)

    # Create confusion matrix
    cm = confusion_matrix(y_test, y_pred)

    logger.info(f"BTTS model accuracy: {accuracy:.4f}")
    logger.info(f"BTTS model precision: {precision:.4f}")
    logger.info(f"BTTS model recall: {recall:.4f}")
    logger.info(f"BTTS model F1 score: {f1:.4f}")

    # Save model
    model_path = os.path.join(MODELS_DIR, "btts_model.joblib")
    joblib.dump(pipeline, model_path)

    logger.info(f"BTTS model saved to {model_path}")

    return pipeline, {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "confusion_matrix": cm
    }

def main():
    """Main function."""
    # Parse arguments
    args = parse_arguments()

    # Ensure directories exist
    ensure_directory_exists(DATA_DIR)
    ensure_directory_exists(MODELS_DIR)
    ensure_directory_exists(RESULTS_DIR)

    # Check if models already exist
    match_result_model_path = os.path.join(MODELS_DIR, "match_result_model.joblib")
    over_under_model_path = os.path.join(MODELS_DIR, "over_under_model.joblib")
    btts_model_path = os.path.join(MODELS_DIR, "btts_model.joblib")

    if not args.force and os.path.exists(match_result_model_path) and os.path.exists(over_under_model_path) and os.path.exists(btts_model_path):
        logger.info("Models already exist. Use --force to retrain.")
        return

    # Download data
    df = download_github_dataset()

    if df.empty:
        logger.error("Failed to download dataset")
        return

    # Preprocess data
    X, y_match_result, y_over_under, y_btts = preprocess_github_data(df, args.leagues, args.start_year, args.end_year)

    if X is None:
        logger.error("Failed to preprocess data")
        return

    # Train models
    match_result_model, match_result_metrics = train_match_result_model(X, y_match_result)
    over_under_model, over_under_metrics = train_over_under_model(X, y_over_under)
    btts_model, btts_metrics = train_btts_model(X, y_btts)

    # Print summary
    logger.info("Models trained successfully")
    logger.info(f"Match result accuracy: {match_result_metrics['accuracy']:.4f}")
    logger.info(f"Over/under accuracy: {over_under_metrics['accuracy']:.4f}")
    logger.info(f"BTTS accuracy: {btts_metrics['accuracy']:.4f}")

    # Save metrics
    metrics = {
        "match_result": match_result_metrics,
        "over_under": over_under_metrics,
        "btts": btts_metrics,
        "training_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "leagues": args.leagues,
        "start_year": args.start_year,
        "end_year": args.end_year
    }

    metrics_path = os.path.join(RESULTS_DIR, "model_metrics.joblib")
    joblib.dump(metrics, metrics_path)

    logger.info(f"Model metrics saved to {metrics_path}")

if __name__ == "__main__":
    main()
