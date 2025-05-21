#!/usr/bin/env python3
"""
Train Enhanced ML Models using GitHub Football Dataset

This script trains advanced machine learning models for football match prediction
using the Club-Football-Match-Data-2000-2025 dataset from GitHub with enhanced
features and hyperparameter tuning.
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
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, AdaBoostClassifier, VotingClassifier, StackingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.svm import SVC
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler, OneHotEncoder, RobustScaler
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split, GridSearchCV, cross_val_score, StratifiedKFold
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix, classification_report, roc_auc_score, roc_curve
import matplotlib.pyplot as plt
import seaborn as sns
from io import BytesIO

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import XGBoost and LightGBM if available
try:
    # For Mac users without OpenMP, we'll use CPU_COUNT=1 to avoid OpenMP dependency
    import os
    os.environ['OMP_NUM_THREADS'] = '1'

    import xgboost as xgb
    # Configure XGBoost to use single thread to avoid OpenMP issues
    xgb.config_context(verbosity=0, nthread=1)
    XGBOOST_AVAILABLE = True
    logger.info("XGBoost is available and will be used in ensemble models (single-threaded mode)")
except (ImportError, Exception) as e:
    XGBOOST_AVAILABLE = False
    logger.warning(f"XGBoost not available: {str(e)}")
    logger.warning("For Mac users, install OpenMP with: brew install libomp")
    logger.warning("Ensemble models will continue without XGBoost")

try:
    # For LightGBM, also try single-threaded mode
    if 'OMP_NUM_THREADS' not in os.environ:
        os.environ['OMP_NUM_THREADS'] = '1'

    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
    logger.info("LightGBM is available and will be used in ensemble models (single-threaded mode)")
except (ImportError, Exception) as e:
    LIGHTGBM_AVAILABLE = False
    logger.warning(f"LightGBM not available: {str(e)}")
    logger.warning("For Mac users, you may need to install additional dependencies")
    logger.warning("Ensemble models will continue without LightGBM")

try:
    from catboost import CatBoostClassifier
    CATBOOST_AVAILABLE = True
    logger.info("CatBoost is available and will be used in ensemble models")
except (ImportError, Exception) as e:
    CATBOOST_AVAILABLE = False
    logger.warning(f"CatBoost not available: {str(e)}")
    logger.warning("Ensemble models will continue without CatBoost")

# This is a duplicate logging setup, removed

# Constants
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "enhanced")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")
GITHUB_DATASET_URL = "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data-2000-2025/main/data/Matches.csv"
GITHUB_ELO_URL = "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data-2000-2025/main/data/Elo%20Ratings.csv"

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Train enhanced ML models for football prediction")

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
        default=2015,
        help="Start year for training data (default: 2015)"
    )

    parser.add_argument(
        "--end_year",
        type=int,
        default=2024,
        help="End year for training data (default: 2024)"
    )

    parser.add_argument(
        "--tune",
        action="store_true",
        help="Perform hyperparameter tuning"
    )

    parser.add_argument(
        "--ensemble",
        action="store_true",
        help="Use ensemble models"
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

def preprocess_github_data(df, leagues, start_year, end_year):
    """
    Preprocess the GitHub football dataset with enhanced features.

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
            "league": match["Division"],
            "season": match["MatchDate"].year,

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
            "over_odds": match["Over25"] if not pd.isna(match["Over25"]) else 0,
            "under_odds": match["Under25"] if not pd.isna(match["Under25"]) else 0,

            # Enhanced features - Asian Handicap
            "handi_size": match["HandiSize"] if not pd.isna(match["HandiSize"]) else 0,
            "handi_home": match["HandiHome"] if not pd.isna(match["HandiHome"]) else 0,
            "handi_away": match["HandiAway"] if not pd.isna(match["HandiAway"]) else 0,

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
    X_columns = [col for col in features_df.columns if col not in ['match_result', 'over_2_5', 'btts', 'home_team', 'away_team', 'league', 'season']]
    X = features_df[X_columns]

    # Convert match result to numeric
    y_match_result = features_df['match_result'].map({'H': 0, 'D': 1, 'A': 2})
    y_over_under = features_df['over_2_5']
    y_btts = features_df['btts']

    logger.info(f"Preprocessed {len(features_df)} matches")
    logger.info(f"Feature columns: {X_columns}")

    return X, y_match_result, y_over_under, y_btts, features_df[['home_team', 'away_team', 'league', 'season']]

def train_match_result_model(X, y, tune=False, ensemble=False):
    """
    Train an enhanced match result model.

    Args:
        X: Feature matrix
        y: Target variable
        tune: Whether to perform hyperparameter tuning
        ensemble: Whether to use ensemble models

    Returns:
        Trained model and evaluation metrics
    """
    logger.info("Training match result model...")

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Set up cross-validation
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    # Create pipeline
    if ensemble:
        # Create ensemble model with base estimators
        estimators = [
            ('rf', RandomForestClassifier(n_estimators=200, max_depth=15, random_state=42, n_jobs=-1)),
            ('gb', GradientBoostingClassifier(n_estimators=200, max_depth=8, random_state=42)),
            ('lr', LogisticRegression(C=1.0, max_iter=1000, random_state=42, n_jobs=-1))
        ]

        # Add XGBoost if available
        if XGBOOST_AVAILABLE:
            logger.info("Adding XGBoost to match result ensemble")
            estimators.append(('xgb', xgb.XGBClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.1,
                random_state=42,
                n_jobs=1,  # Force single thread to avoid OpenMP issues
                use_label_encoder=False,
                eval_metric='mlogloss',
                tree_method='hist'  # Use histogram-based algorithm which is faster
            )))

        # Add LightGBM if available
        if LIGHTGBM_AVAILABLE:
            logger.info("Adding LightGBM to match result ensemble")
            estimators.append(('lgb', lgb.LGBMClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.1,
                random_state=42,
                n_jobs=1,  # Force single thread to avoid OpenMP issues
                verbose=-1,  # Suppress output
                force_row_wise=True  # Avoid using OpenMP
            )))

        # Add CatBoost if available
        if CATBOOST_AVAILABLE:
            logger.info("Adding CatBoost to match result ensemble")
            estimators.append(('cat', CatBoostClassifier(
                iterations=200,
                depth=6,
                learning_rate=0.1,
                random_seed=42,
                thread_count=-1,
                verbose=0
            )))

        logger.info(f"Creating ensemble with {len(estimators)} base models: {[est[0] for est in estimators]}")

        # Choose the best approach based on available models
        if len(estimators) >= 4:
            # If we have 4+ models, use stacking for best performance
            logger.info("Using StackingClassifier for match result ensemble")
            final_estimator = LogisticRegression(C=1.0, max_iter=1000, random_state=42)

            pipeline = Pipeline([
                ('scaler', StandardScaler()),
                ('model', StackingClassifier(
                    estimators=estimators,
                    final_estimator=final_estimator,
                    cv=5,
                    n_jobs=-1
                ))
            ])
        else:
            # With fewer models, voting can be more stable
            logger.info("Using VotingClassifier for match result ensemble")
            pipeline = Pipeline([
                ('scaler', StandardScaler()),
                ('model', VotingClassifier(
                    estimators=estimators,
                    voting='soft'
                ))
            ])
    else:
        # Create single model
        pipeline = Pipeline([
            ('scaler', StandardScaler()),
            ('model', RandomForestClassifier(n_estimators=200, max_depth=15, random_state=42, n_jobs=-1))
        ])

    # Perform hyperparameter tuning if requested
    if tune:
        logger.info("Performing hyperparameter tuning for match result model...")

        if ensemble:
            # Tune ensemble model with stacking classifier
            param_grid = {
                'model__final_estimator__C': [0.1, 1.0, 10.0],
                'model__cv': [3, 5]
            }
        else:
            # Tune single model
            param_grid = {
                'model__n_estimators': [100, 200, 300],
                'model__max_depth': [10, 15, 20],
                'model__min_samples_split': [2, 5, 10]
            }

        grid_search = GridSearchCV(pipeline, param_grid, cv=3, scoring='accuracy', n_jobs=-1)
        grid_search.fit(X_train, y_train)

        logger.info(f"Best parameters: {grid_search.best_params_}")
        pipeline = grid_search.best_estimator_
    else:
        # Train model
        pipeline.fit(X_train, y_train)

    # Evaluate model on test set
    y_pred = pipeline.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    precision = precision_score(y_test, y_pred, average='weighted')
    recall = recall_score(y_test, y_pred, average='weighted')
    f1 = f1_score(y_test, y_pred, average='weighted')

    # Create confusion matrix
    cm = confusion_matrix(y_test, y_pred)

    # Perform cross-validation
    logger.info("Performing cross-validation...")
    cv_scores = cross_val_score(pipeline, X, y, cv=cv, scoring='accuracy', n_jobs=-1)
    logger.info(f"Cross-validation accuracy: {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")

    # Print classification report
    logger.info("Match result classification report:")
    logger.info("\n" + classification_report(y_test, y_pred, target_names=['Home', 'Draw', 'Away']))

    # Calculate feature importance if possible
    try:
        # Extract the model from the pipeline
        model = pipeline.named_steps['model']

        # Get feature importance based on model type
        if hasattr(model, 'feature_importances_'):
            # For tree-based models like RandomForest, GradientBoosting
            importances = model.feature_importances_
            feature_names = X.columns
        elif hasattr(model, 'coef_'):
            # For linear models like LogisticRegression
            importances = np.abs(model.coef_).mean(axis=0)
            feature_names = X.columns
        elif hasattr(model, 'estimators_') and hasattr(model.estimators_[0], 'feature_importances_'):
            # For ensemble models with feature_importances_
            importances = np.mean([est.feature_importances_ for est in model.estimators_], axis=0)
            feature_names = X.columns
        elif hasattr(model, 'final_estimator_') and hasattr(model, 'estimators_'):
            # For stacking classifier
            logger.info("Stacking classifier detected - showing base estimator importances")
            for name, est in model.estimators:
                if hasattr(est, 'feature_importances_'):
                    logger.info(f"\nFeature importances for {name}:")
                    est_importances = est.feature_importances_
                    for i, importance in enumerate(est_importances):
                        if i < len(X.columns):
                            logger.info(f"  {X.columns[i]}: {importance:.4f}")
            importances = None
            feature_names = None
        else:
            importances = None
            feature_names = None

        # Print feature importances
        if importances is not None and feature_names is not None:
            logger.info("\nFeature importances:")
            # Sort features by importance
            indices = np.argsort(importances)[::-1]
            for i in range(min(10, len(feature_names))):  # Print top 10 features
                logger.info(f"  {feature_names[indices[i]]}: {importances[indices[i]]:.4f}")
    except Exception as e:
        logger.warning(f"Could not calculate feature importance: {str(e)}")

    logger.info(f"Match result model accuracy: {accuracy:.4f}")
    logger.info(f"Match result model precision: {precision:.4f}")
    logger.info(f"Match result model recall: {recall:.4f}")
    logger.info(f"Match result model F1 score: {f1:.4f}")

    # Save model
    ensure_directory_exists(MODELS_DIR)
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

def train_over_under_model(X, y, tune=False, ensemble=False):
    """
    Train an enhanced over/under model.

    Args:
        X: Feature matrix
        y: Target variable
        tune: Whether to perform hyperparameter tuning
        ensemble: Whether to use ensemble models

    Returns:
        Trained model and evaluation metrics
    """
    logger.info("Training over/under model...")

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Set up cross-validation
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    # Create pipeline
    if ensemble:
        # Create ensemble model with base estimators
        estimators = [
            ('rf', RandomForestClassifier(n_estimators=200, max_depth=15, random_state=42, n_jobs=-1)),
            ('gb', GradientBoostingClassifier(n_estimators=200, max_depth=8, random_state=42)),
            ('lr', LogisticRegression(C=1.0, max_iter=1000, random_state=42, n_jobs=-1))
        ]

        # Add XGBoost if available
        if XGBOOST_AVAILABLE:
            logger.info("Adding XGBoost to over/under ensemble")
            estimators.append(('xgb', xgb.XGBClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.1,
                random_state=42,
                n_jobs=1,  # Force single thread to avoid OpenMP issues
                use_label_encoder=False,
                eval_metric='logloss',
                tree_method='hist'  # Use histogram-based algorithm which is faster
            )))

        # Add LightGBM if available
        if LIGHTGBM_AVAILABLE:
            logger.info("Adding LightGBM to over/under ensemble")
            estimators.append(('lgb', lgb.LGBMClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.1,
                random_state=42,
                n_jobs=1,  # Force single thread to avoid OpenMP issues
                verbose=-1,  # Suppress output
                force_row_wise=True  # Avoid using OpenMP
            )))

        # Add CatBoost if available
        if CATBOOST_AVAILABLE:
            logger.info("Adding CatBoost to over/under ensemble")
            estimators.append(('cat', CatBoostClassifier(
                iterations=200,
                depth=6,
                learning_rate=0.1,
                random_seed=42,
                thread_count=-1,
                verbose=0
            )))

        logger.info(f"Creating ensemble with {len(estimators)} base models: {[est[0] for est in estimators]}")

        # Choose the best approach based on available models
        if len(estimators) >= 4:
            # If we have 4+ models, use stacking for best performance
            logger.info("Using StackingClassifier for over/under ensemble")
            final_estimator = LogisticRegression(C=1.0, max_iter=1000, random_state=42)

            pipeline = Pipeline([
                ('scaler', StandardScaler()),
                ('model', StackingClassifier(
                    estimators=estimators,
                    final_estimator=final_estimator,
                    cv=5,
                    n_jobs=-1
                ))
            ])
        else:
            # With fewer models, voting can be more stable
            logger.info("Using VotingClassifier for over/under ensemble")
            pipeline = Pipeline([
                ('scaler', StandardScaler()),
                ('model', VotingClassifier(
                    estimators=estimators,
                    voting='soft'
                ))
            ])
    else:
        # Create single model
        pipeline = Pipeline([
            ('scaler', StandardScaler()),
            ('model', GradientBoostingClassifier(n_estimators=200, max_depth=8, random_state=42))
        ])

    # Perform hyperparameter tuning if requested
    if tune:
        logger.info("Performing hyperparameter tuning for over/under model...")

        if ensemble:
            # Tune ensemble model with stacking classifier
            param_grid = {
                'model__final_estimator__C': [0.1, 1.0, 10.0],
                'model__cv': [3, 5]
            }
        else:
            # Tune single model
            param_grid = {
                'model__n_estimators': [100, 200, 300],
                'model__max_depth': [5, 8, 10],
                'model__learning_rate': [0.05, 0.1, 0.2]
            }

        grid_search = GridSearchCV(pipeline, param_grid, cv=3, scoring='accuracy', n_jobs=-1)
        grid_search.fit(X_train, y_train)

        logger.info(f"Best parameters: {grid_search.best_params_}")
        pipeline = grid_search.best_estimator_
    else:
        # Train model
        pipeline.fit(X_train, y_train)

    # Evaluate model on test set
    y_pred = pipeline.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    precision = precision_score(y_test, y_pred)
    recall = recall_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred)

    # Create confusion matrix
    cm = confusion_matrix(y_test, y_pred)

    # Perform cross-validation
    logger.info("Performing cross-validation...")
    cv_scores = cross_val_score(pipeline, X, y, cv=cv, scoring='accuracy', n_jobs=-1)
    logger.info(f"Cross-validation accuracy: {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")

    # Print classification report
    logger.info("Over/under classification report:")
    logger.info("\n" + classification_report(y_test, y_pred, target_names=['Under', 'Over']))

    # Calculate feature importance if possible
    try:
        # Extract the model from the pipeline
        model = pipeline.named_steps['model']

        # Get feature importance based on model type
        if hasattr(model, 'feature_importances_'):
            # For tree-based models like RandomForest, GradientBoosting
            importances = model.feature_importances_
            feature_names = X.columns
        elif hasattr(model, 'coef_'):
            # For linear models like LogisticRegression
            importances = np.abs(model.coef_).mean(axis=0)
            feature_names = X.columns
        elif hasattr(model, 'estimators_') and hasattr(model.estimators_[0], 'feature_importances_'):
            # For ensemble models with feature_importances_
            importances = np.mean([est.feature_importances_ for est in model.estimators_], axis=0)
            feature_names = X.columns
        elif hasattr(model, 'final_estimator_') and hasattr(model, 'estimators_'):
            # For stacking classifier
            logger.info("Stacking classifier detected - showing base estimator importances")
            for name, est in model.estimators:
                if hasattr(est, 'feature_importances_'):
                    logger.info(f"\nFeature importances for {name}:")
                    est_importances = est.feature_importances_
                    for i, importance in enumerate(est_importances):
                        if i < len(X.columns):
                            logger.info(f"  {X.columns[i]}: {importance:.4f}")
            importances = None
            feature_names = None
        else:
            importances = None
            feature_names = None

        # Print feature importances
        if importances is not None and feature_names is not None:
            logger.info("\nOver/under feature importances:")
            # Sort features by importance
            indices = np.argsort(importances)[::-1]
            for i in range(min(10, len(feature_names))):  # Print top 10 features
                logger.info(f"  {feature_names[indices[i]]}: {importances[indices[i]]:.4f}")
    except Exception as e:
        logger.warning(f"Could not calculate feature importance: {str(e)}")

    logger.info(f"Over/under model accuracy: {accuracy:.4f}")
    logger.info(f"Over/under model precision: {precision:.4f}")
    logger.info(f"Over/under model recall: {recall:.4f}")
    logger.info(f"Over/under model F1 score: {f1:.4f}")

    # Save model
    ensure_directory_exists(MODELS_DIR)
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

def train_btts_model(X, y, tune=False, ensemble=False):
    """
    Train an enhanced BTTS model.

    Args:
        X: Feature matrix
        y: Target variable
        tune: Whether to perform hyperparameter tuning
        ensemble: Whether to use ensemble models

    Returns:
        Trained model and evaluation metrics
    """
    logger.info("Training BTTS model...")

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Set up cross-validation
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    # Create pipeline
    if ensemble:
        # Create ensemble model with base estimators
        estimators = [
            ('rf', RandomForestClassifier(n_estimators=200, max_depth=15, random_state=42, n_jobs=-1)),
            ('gb', GradientBoostingClassifier(n_estimators=200, max_depth=8, random_state=42)),
            ('lr', LogisticRegression(C=1.0, max_iter=1000, random_state=42, n_jobs=-1))
        ]

        # Add XGBoost if available
        if XGBOOST_AVAILABLE:
            logger.info("Adding XGBoost to BTTS ensemble")
            estimators.append(('xgb', xgb.XGBClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.1,
                random_state=42,
                n_jobs=1,  # Force single thread to avoid OpenMP issues
                use_label_encoder=False,
                eval_metric='logloss',
                tree_method='hist'  # Use histogram-based algorithm which is faster
            )))

        # Add LightGBM if available
        if LIGHTGBM_AVAILABLE:
            logger.info("Adding LightGBM to BTTS ensemble")
            estimators.append(('lgb', lgb.LGBMClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.1,
                random_state=42,
                n_jobs=1,  # Force single thread to avoid OpenMP issues
                verbose=-1,  # Suppress output
                force_row_wise=True  # Avoid using OpenMP
            )))

        # Add CatBoost if available
        if CATBOOST_AVAILABLE:
            logger.info("Adding CatBoost to BTTS ensemble")
            estimators.append(('cat', CatBoostClassifier(
                iterations=200,
                depth=6,
                learning_rate=0.1,
                random_seed=42,
                thread_count=-1,
                verbose=0
            )))

        logger.info(f"Creating ensemble with {len(estimators)} base models: {[est[0] for est in estimators]}")

        # Choose the best approach based on available models
        if len(estimators) >= 4:
            # If we have 4+ models, use stacking for best performance
            logger.info("Using StackingClassifier for BTTS ensemble")
            final_estimator = LogisticRegression(C=1.0, max_iter=1000, random_state=42)

            pipeline = Pipeline([
                ('scaler', StandardScaler()),
                ('model', StackingClassifier(
                    estimators=estimators,
                    final_estimator=final_estimator,
                    cv=5,
                    n_jobs=-1
                ))
            ])
        else:
            # With fewer models, voting can be more stable
            logger.info("Using VotingClassifier for BTTS ensemble")
            pipeline = Pipeline([
                ('scaler', StandardScaler()),
                ('model', VotingClassifier(
                    estimators=estimators,
                    voting='soft'
                ))
            ])
    else:
        # Create single model
        pipeline = Pipeline([
            ('scaler', StandardScaler()),
            ('model', LogisticRegression(C=1.0, max_iter=1000, random_state=42, n_jobs=-1))
        ])

    # Perform hyperparameter tuning if requested
    if tune:
        logger.info("Performing hyperparameter tuning for BTTS model...")

        if ensemble:
            # Tune ensemble model with stacking classifier
            param_grid = {
                'model__final_estimator__C': [0.1, 1.0, 10.0],
                'model__cv': [3, 5]
            }
        else:
            # Tune single model
            param_grid = {
                'model__C': [0.1, 1.0, 10.0],
                'model__solver': ['liblinear', 'lbfgs'],
                'model__max_iter': [1000, 2000]
            }

        grid_search = GridSearchCV(pipeline, param_grid, cv=3, scoring='accuracy', n_jobs=-1)
        grid_search.fit(X_train, y_train)

        logger.info(f"Best parameters: {grid_search.best_params_}")
        pipeline = grid_search.best_estimator_
    else:
        # Train model
        pipeline.fit(X_train, y_train)

    # Evaluate model on test set
    y_pred = pipeline.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    precision = precision_score(y_test, y_pred)
    recall = recall_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred)

    # Create confusion matrix
    cm = confusion_matrix(y_test, y_pred)

    # Perform cross-validation
    logger.info("Performing cross-validation...")
    cv_scores = cross_val_score(pipeline, X, y, cv=cv, scoring='accuracy', n_jobs=-1)
    logger.info(f"Cross-validation accuracy: {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")

    # Print classification report
    logger.info("BTTS classification report:")
    logger.info("\n" + classification_report(y_test, y_pred, target_names=['No', 'Yes']))

    # Calculate feature importance if possible
    try:
        # Extract the model from the pipeline
        model = pipeline.named_steps['model']

        # Get feature importance based on model type
        if hasattr(model, 'feature_importances_'):
            # For tree-based models like RandomForest, GradientBoosting
            importances = model.feature_importances_
            feature_names = X.columns
        elif hasattr(model, 'coef_'):
            # For linear models like LogisticRegression
            importances = np.abs(model.coef_).mean(axis=0)
            feature_names = X.columns
        elif hasattr(model, 'estimators_') and hasattr(model.estimators_[0], 'feature_importances_'):
            # For ensemble models with feature_importances_
            importances = np.mean([est.feature_importances_ for est in model.estimators_], axis=0)
            feature_names = X.columns
        elif hasattr(model, 'final_estimator_') and hasattr(model, 'estimators_'):
            # For stacking classifier
            logger.info("Stacking classifier detected - showing base estimator importances")
            for name, est in model.estimators:
                if hasattr(est, 'feature_importances_'):
                    logger.info(f"\nFeature importances for {name}:")
                    est_importances = est.feature_importances_
                    for i, importance in enumerate(est_importances):
                        if i < len(X.columns):
                            logger.info(f"  {X.columns[i]}: {importance:.4f}")
            importances = None
            feature_names = None
        else:
            importances = None
            feature_names = None

        # Print feature importances
        if importances is not None and feature_names is not None:
            logger.info("\nBTTS feature importances:")
            # Sort features by importance
            indices = np.argsort(importances)[::-1]
            for i in range(min(10, len(feature_names))):  # Print top 10 features
                logger.info(f"  {feature_names[indices[i]]}: {importances[indices[i]]:.4f}")
    except Exception as e:
        logger.warning(f"Could not calculate feature importance: {str(e)}")

    logger.info(f"BTTS model accuracy: {accuracy:.4f}")
    logger.info(f"BTTS model precision: {precision:.4f}")
    logger.info(f"BTTS model recall: {recall:.4f}")
    logger.info(f"BTTS model F1 score: {f1:.4f}")

    # Save model
    ensure_directory_exists(MODELS_DIR)
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
    X, y_match_result, y_over_under, y_btts, _ = preprocess_github_data(df, args.leagues, args.start_year, args.end_year)

    if X is None:
        logger.error("Failed to preprocess data")
        return

    # Train models
    _, match_result_metrics = train_match_result_model(X, y_match_result, args.tune, args.ensemble)
    _, over_under_metrics = train_over_under_model(X, y_over_under, args.tune, args.ensemble)
    _, btts_metrics = train_btts_model(X, y_btts, args.tune, args.ensemble)

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
        "end_year": args.end_year,
        "tune": args.tune,
        "ensemble": args.ensemble
    }

    metrics_path = os.path.join(RESULTS_DIR, "enhanced_model_metrics.joblib")
    joblib.dump(metrics, metrics_path)

    logger.info(f"Model metrics saved to {metrics_path}")

if __name__ == "__main__":
    main()