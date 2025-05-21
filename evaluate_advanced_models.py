#!/usr/bin/env python3
"""
Evaluate Advanced ML Models Script

This script evaluates the advanced ML models using the GitHub football dataset.
It compares the performance of different models and generates evaluation metrics.
"""

import os
import sys
import argparse
import logging
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple, Union
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score
from sklearn.metrics import confusion_matrix, classification_report, roc_curve, precision_recall_curve
from sklearn.model_selection import train_test_split

# Add the parent directory to the path so we can import from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ml.model_factory import model_factory
from app.utils.common import setup_logging, ensure_directory_exists
from app.utils.config import settings

# Set up logging
logger = setup_logging(__name__)

# Constants
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "advanced")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")
EVAL_DIR = os.path.join(RESULTS_DIR, "evaluation")
GITHUB_DATASET_URL = "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data-2000-2025/main/data/Matches.csv"

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Evaluate advanced ML models using GitHub football dataset")
    
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
        help="Type of model to evaluate (e.g., xgboost_match_result, lightgbm_btts)"
    )
    
    parser.add_argument(
        "--all",
        action="store_true",
        help="Evaluate all available models"
    )
    
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.2,
        help="Proportion of data to use for testing (default: 0.2)"
    )
    
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Compare advanced models with traditional models"
    )
    
    return parser.parse_args()

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
        logger.error(f"GitHub dataset not found at {cache_file}. Please run train_advanced_ml_models.py first.")
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
        
        logger.info(f"Created features and targets for {len(features_df)} matches")
        
        return features_df, targets
        
    except Exception as e:
        logger.error(f"Error preprocessing data: {str(e)}")
        return pd.DataFrame(), {}

def evaluate_model(model_type: str, features_df: pd.DataFrame, targets: Dict[str, pd.Series], test_size: float = 0.2) -> Dict[str, Any]:
    """
    Evaluate a model.

    Args:
        model_type: Type of model to evaluate
        features_df: Features DataFrame
        targets: Dictionary of target variables
        test_size: Proportion of data to use for testing

    Returns:
        Dictionary with evaluation results
    """
    try:
        # Select appropriate target based on model type
        if "match_result" in model_type:
            target_name = "match_result"
            target = targets["match_result"]
            is_multiclass = True
        elif "over_under_1_5" in model_type:
            target_name = "over_1_5"
            target = targets["over_1_5"]
            is_multiclass = False
        elif "over_under_3_5" in model_type:
            target_name = "over_3_5"
            target = targets["over_3_5"]
            is_multiclass = False
        elif "over_under" in model_type:
            target_name = "over_2_5"
            target = targets["over_2_5"]
            is_multiclass = False
        elif "btts" in model_type:
            target_name = "btts"
            target = targets["btts"]
            is_multiclass = False
        else:
            # Default to match result
            target_name = "match_result"
            target = targets["match_result"]
            is_multiclass = True
        
        # Get model from factory
        model = model_factory.get_model(model_type)
        
        if model is None:
            logger.error(f"Model type {model_type} not found")
            return {"status": "error", "message": f"Model type {model_type} not found"}
        
        # Split data into training and testing sets
        # Use time-based split for football data
        train_idx = features_df.index[:int(len(features_df) * (1 - test_size))]
        test_idx = features_df.index[int(len(features_df) * (1 - test_size)):]
        
        X_train = features_df.loc[train_idx]
        X_test = features_df.loc[test_idx]
        y_train = target.loc[train_idx]
        y_test = target.loc[test_idx]
        
        # Evaluate model
        logger.info(f"Evaluating model {model_type}")
        
        # Make predictions
        result = model.predict(X_test)
        
        if result.get("status") != "success":
            logger.error(f"Error making predictions: {result.get('message')}")
            return {"status": "error", "message": result.get("message")}
        
        # Get predictions
        y_pred = result.get("predictions", [])
        y_proba = result.get("probabilities", [])
        
        # Calculate metrics
        metrics = {}
        
        if is_multiclass:
            # Convert string labels to numeric
            label_map = {"H": 0, "D": 1, "A": 2}
            y_test_numeric = y_test.map(label_map)
            y_pred_numeric = [label_map.get(p, 0) for p in y_pred]
            
            # Calculate metrics
            metrics["accuracy"] = accuracy_score(y_test_numeric, y_pred_numeric)
            metrics["precision"] = precision_score(y_test_numeric, y_pred_numeric, average="weighted")
            metrics["recall"] = recall_score(y_test_numeric, y_pred_numeric, average="weighted")
            metrics["f1"] = f1_score(y_test_numeric, y_pred_numeric, average="weighted")
            
            # Create confusion matrix
            cm = confusion_matrix(y_test_numeric, y_pred_numeric)
            metrics["confusion_matrix"] = cm.tolist()
            
            # Create classification report
            cr = classification_report(y_test_numeric, y_pred_numeric, target_names=["Home Win", "Draw", "Away Win"], output_dict=True)
            metrics["classification_report"] = cr
            
        else:
            # Binary classification
            metrics["accuracy"] = accuracy_score(y_test, y_pred)
            metrics["precision"] = precision_score(y_test, y_pred)
            metrics["recall"] = recall_score(y_test, y_pred)
            metrics["f1"] = f1_score(y_test, y_pred)
            
            # Calculate ROC AUC if probabilities are available
            if y_proba and len(y_proba[0]) > 1:
                metrics["roc_auc"] = roc_auc_score(y_test, [p[1] for p in y_proba])
            
            # Create confusion matrix
            cm = confusion_matrix(y_test, y_pred)
            metrics["confusion_matrix"] = cm.tolist()
            
            # Create classification report
            cr = classification_report(y_test, y_pred, output_dict=True)
            metrics["classification_report"] = cr
        
        # Add uncertainty metrics if available
        if "uncertainty" in result:
            uncertainty = result.get("uncertainty", [])
            metrics["mean_uncertainty"] = np.mean(uncertainty)
            metrics["median_uncertainty"] = np.median(uncertainty)
            metrics["min_uncertainty"] = np.min(uncertainty)
            metrics["max_uncertainty"] = np.max(uncertainty)
        
        # Save evaluation results
        ensure_directory_exists(EVAL_DIR)
        eval_file = os.path.join(EVAL_DIR, f"{model_type}_{target_name}_eval.json")
        
        import json
        with open(eval_file, "w") as f:
            json.dump(metrics, f, indent=2)
        
        logger.info(f"Evaluation results saved to {eval_file}")
        
        return {
            "status": "success",
            "model_type": model_type,
            "target": target_name,
            "metrics": metrics
        }
        
    except Exception as e:
        logger.error(f"Error evaluating model {model_type}: {str(e)}")
        return {"status": "error", "message": str(e)}

def compare_models(advanced_model: str, traditional_model: str, features_df: pd.DataFrame, targets: Dict[str, pd.Series], test_size: float = 0.2) -> Dict[str, Any]:
    """
    Compare an advanced model with a traditional model.

    Args:
        advanced_model: Type of advanced model
        traditional_model: Type of traditional model
        features_df: Features DataFrame
        targets: Dictionary of target variables
        test_size: Proportion of data to use for testing

    Returns:
        Dictionary with comparison results
    """
    try:
        # Evaluate advanced model
        advanced_result = evaluate_model(advanced_model, features_df, targets, test_size)
        
        # Evaluate traditional model
        traditional_result = evaluate_model(traditional_model, features_df, targets, test_size)
        
        # Compare results
        comparison = {
            "status": "success",
            "advanced_model": advanced_model,
            "traditional_model": traditional_model,
            "advanced_metrics": advanced_result.get("metrics", {}),
            "traditional_metrics": traditional_result.get("metrics", {}),
            "improvement": {}
        }
        
        # Calculate improvement
        for metric in ["accuracy", "precision", "recall", "f1"]:
            if metric in advanced_result.get("metrics", {}) and metric in traditional_result.get("metrics", {}):
                advanced_value = advanced_result["metrics"][metric]
                traditional_value = traditional_result["metrics"][metric]
                improvement = advanced_value - traditional_value
                improvement_pct = (improvement / traditional_value) * 100 if traditional_value > 0 else 0
                
                comparison["improvement"][metric] = {
                    "absolute": improvement,
                    "percentage": improvement_pct
                }
        
        # Save comparison results
        ensure_directory_exists(EVAL_DIR)
        comparison_file = os.path.join(EVAL_DIR, f"comparison_{advanced_model}_vs_{traditional_model}.json")
        
        import json
        with open(comparison_file, "w") as f:
            json.dump(comparison, f, indent=2)
        
        logger.info(f"Comparison results saved to {comparison_file}")
        
        return comparison
        
    except Exception as e:
        logger.error(f"Error comparing models: {str(e)}")
        return {"status": "error", "message": str(e)}

def main():
    """Main function."""
    # Parse arguments
    args = parse_arguments()
    
    # Ensure directories exist
    ensure_directory_exists(DATA_DIR)
    ensure_directory_exists(MODELS_DIR)
    ensure_directory_exists(RESULTS_DIR)
    ensure_directory_exists(EVAL_DIR)
    
    # Load data
    df = load_github_dataset()
    
    if df.empty:
        logger.error("Failed to load dataset")
        return
    
    # Preprocess data
    leagues = args.leagues.split(',')
    features_df, targets = preprocess_data(df, leagues, args.start_year, args.end_year)
    
    if features_df.empty:
        logger.error("Failed to preprocess data")
        return
    
    # Evaluate models
    if args.all:
        # Evaluate all models
        for model_type in model_factory.get_available_models():
            evaluate_model(model_type, features_df, targets, args.test_size)
    elif args.model_type:
        # Evaluate specific model
        evaluate_model(args.model_type, features_df, targets, args.test_size)
    else:
        logger.error("No model type specified. Use --model-type or --all")
        return
    
    # Compare models if requested
    if args.compare:
        # Define model pairs to compare
        model_pairs = [
            ("xgboost_match_result", "match_result"),
            ("lightgbm_btts", "btts"),
            ("nn_over_under_2_5", "over_under")
        ]
        
        for advanced_model, traditional_model in model_pairs:
            compare_models(advanced_model, traditional_model, features_df, targets, args.test_size)
    
    logger.info("Model evaluation complete")

if __name__ == "__main__":
    main()
