"""
Train ML Models

This script trains machine learning models for predicting football match outcomes.
It uses the historical data from the schochastics/football-data GitHub repository.
"""

import os
import sys
import pandas as pd
import numpy as np
import joblib
import logging
from typing import Dict, List, Any, Optional, Tuple
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, VotingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, classification_report
import xgboost as xgb
import lightgbm as lgb

# Add the parent directory to the path to import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.ml.ensemble_model import ensemble_model
from app.ml.feature_engineering import feature_engineer

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
HISTORICAL_DIR = os.path.join(DATA_DIR, "historical")
PROCESSED_DIR = os.path.join(HISTORICAL_DIR, "processed")
FEATURES_FILE = os.path.join(PROCESSED_DIR, "features.parquet")
RESULTS_FILE = os.path.join(PROCESSED_DIR, "results.parquet")
MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models")

def load_data() -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load historical data from Parquet files.

    Returns:
        Tuple of (features_df, results_df)
    """
    # Check if files exist
    if not os.path.exists(FEATURES_FILE) or not os.path.exists(RESULTS_FILE):
        raise FileNotFoundError(
            f"Historical data files not found. Please run fetch_football_data_github.py first."
        )

    # Load data from Parquet files
    try:
        features_df = pd.read_parquet(FEATURES_FILE)
        results_df = pd.read_parquet(RESULTS_FILE)

        logger.info(f"Loaded {len(features_df)} matches from Parquet files")
        return features_df, results_df

    except Exception as e:
        logger.error(f"Error loading Parquet files: {str(e)}")
        raise

def preprocess_data(features_df: pd.DataFrame, results_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    """
    Preprocess data for training.

    Args:
        features_df: DataFrame containing features
        results_df: DataFrame containing results

    Returns:
        Tuple of (X, y_match_result, y_over_under, y_btts)
    """
    # Merge features and results
    data = pd.merge(features_df, results_df, on="match_id")

    # Drop non-feature columns
    drop_columns = [
        'match_id', 'date_x', 'home_team_x', 'away_team_x', 'date_y',
        'home_team_y', 'away_team_y', 'home_goals', 'away_goals'
    ]

    for col in drop_columns:
        if col in data.columns:
            data = data.drop(col, axis=1)

    # Handle missing values
    data = data.fillna(0)

    # Extract target variables
    y_match_result = data['match_result']
    y_over_under = data['over_2_5']
    y_btts = data['btts']

    # Drop target columns
    X = data.drop(['match_result', 'over_2_5', 'btts'], axis=1)

    # Convert categorical variables to numeric
    for col in X.select_dtypes(include=['object']).columns:
        X[col] = pd.factorize(X[col])[0]

    return X, y_match_result, y_over_under, y_btts

def train_match_result_model(X: pd.DataFrame, y: pd.Series) -> Pipeline:
    """
    Train match result prediction model.

    Args:
        X: Features
        y: Target variable

    Returns:
        Trained model
    """
    logger.info("Training match result model...")

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Create pipeline
    model = Pipeline([
        ('scaler', StandardScaler()),
        ('classifier', RandomForestClassifier(n_estimators=100, random_state=42))
    ])

    # Train model
    model.fit(X_train, y_train)

    # Evaluate model
    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)

    logger.info(f"Match result model accuracy: {accuracy:.4f}")
    logger.info("\n" + classification_report(y_test, y_pred))

    return model

def train_over_under_model(X: pd.DataFrame, y: pd.Series) -> Pipeline:
    """
    Train over/under prediction model.

    Args:
        X: Features
        y: Target variable

    Returns:
        Trained model
    """
    logger.info("Training over/under model...")

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Create pipeline
    model = Pipeline([
        ('scaler', StandardScaler()),
        ('classifier', xgb.XGBClassifier(n_estimators=100, random_state=42))
    ])

    # Train model
    model.fit(X_train, y_train)

    # Evaluate model
    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)

    logger.info(f"Over/under model accuracy: {accuracy:.4f}")
    logger.info("\n" + classification_report(y_test, y_pred))

    return model

def train_btts_model(X: pd.DataFrame, y: pd.Series) -> Pipeline:
    """
    Train BTTS prediction model.

    Args:
        X: Features
        y: Target variable

    Returns:
        Trained model
    """
    logger.info("Training BTTS model...")

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Create pipeline
    model = Pipeline([
        ('scaler', StandardScaler()),
        ('classifier', xgb.XGBClassifier(n_estimators=100, random_state=42))
    ])

    # Train model
    model.fit(X_train, y_train)

    # Evaluate model
    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)

    logger.info(f"BTTS model accuracy: {accuracy:.4f}")
    logger.info("\n" + classification_report(y_test, y_pred))

    return model

def save_models(match_result_model: Pipeline, over_under_model: Pipeline, btts_model: Pipeline) -> None:
    """
    Save trained models to disk.

    Args:
        match_result_model: Match result prediction model
        over_under_model: Over/under prediction model
        btts_model: BTTS prediction model
    """
    # Create models directory if it doesn't exist
    os.makedirs(MODELS_DIR, exist_ok=True)

    # Save models
    joblib.dump(match_result_model, os.path.join(MODELS_DIR, "match_result_model.joblib"))
    joblib.dump(over_under_model, os.path.join(MODELS_DIR, "over_under_model.joblib"))
    joblib.dump(btts_model, os.path.join(MODELS_DIR, "btts_model.joblib"))

    logger.info(f"Models saved to {MODELS_DIR}")

def main():
    """Main function to train all models."""
    try:
        # Load data
        logger.info("Loading historical data...")
        features_df, results_df = load_data()

        logger.info(f"Loaded {len(features_df)} matches")

        # Load raw historical data for feature engineering
        logger.info("Loading raw historical data for feature engineering...")
        historical_df = pd.read_parquet(os.path.join(HISTORICAL_DIR, "raw", "matches.parquet"))

        logger.info(f"Loaded {len(historical_df)} raw historical matches")

        # Train ensemble models
        logger.info("Training ensemble models...")
        result = ensemble_model.train(features_df, results_df, historical_df)

        if result["status"] == "success":
            logger.info("Ensemble models trained successfully!")
            logger.info(f"Match result accuracy: {result['match_result_accuracy']:.4f}")
            logger.info(f"Over/under accuracy: {result['over_under_accuracy']:.4f}")
            logger.info(f"BTTS accuracy: {result['btts_accuracy']:.4f}")
        else:
            logger.error(f"Error training ensemble models: {result.get('message', 'Unknown error')}")

            # Fall back to traditional models
            logger.info("Falling back to traditional models...")

            # Preprocess data
            logger.info("Preprocessing data...")
            X, y_match_result, y_over_under, y_btts = preprocess_data(features_df, results_df)

            # Train models
            match_result_model = train_match_result_model(X, y_match_result)
            over_under_model = train_over_under_model(X, y_over_under)
            btts_model = train_btts_model(X, y_btts)

            # Save models
            save_models(match_result_model, over_under_model, btts_model)

            logger.info("Traditional models trained successfully!")

    except Exception as e:
        logger.error(f"Error training models: {str(e)}")
        raise

if __name__ == "__main__":
    main()
