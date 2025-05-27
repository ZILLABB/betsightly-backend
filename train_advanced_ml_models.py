"""Train advanced ML models for football predictions.

This script trains various advanced machine learning models for predicting
football match outcomes using enhanced features and ensemble methods.
"""

import os
import sys
import logging
import argparse

import pandas as pd
from sklearn.model_selection import train_test_split

import matplotlib.pyplot as plt
import seaborn as sns
from io import BytesIO
import joblib

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ml.ensemble_model import EnsembleModel
from app.ml.feature_engineering import FeatureEngineer
from app.ml.model_evaluator import ModelEvaluator
from app.ml.model_persistence import ModelPersistence
from app.ml.confidence_calibrator import PlattCalibrator

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
DATA_DIR = "data"
MODELS_DIR = "models"
RESULTS_DIR = "results"
EVAL_DIR = "evaluation"

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Train advanced ML models for football predictions"
    )
    
    parser.add_argument(
        "--leagues",
        type=str,
        default="PL,PD,SA,BL1,FL1",
        help="Comma-separated list of league codes"
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
        "--test-size",
        type=float,
        default=0.2,
        help="Proportion of data to use for testing"
    )
    
    parser.add_argument(
        "--model-type",
        type=str,
        choices=["xgboost", "lightgbm", "catboost", "nn"],
        help="Type of model to train"
    )
    
    parser.add_argument(
        "--all",
        action="store_true",
        help="Train all model types"
    )
    
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Compare with traditional models"
    )
    
    return parser.parse_args()

def ensure_directory_exists(directory: str) -> None:
    """Ensure a directory exists, creating it if necessary."""
    if not os.path.exists(directory):
        os.makedirs(directory)
        logger.info(f"Created directory: {directory}")

def load_github_dataset() -> pd.DataFrame:
    """Load the GitHub dataset."""
    try:
        file_path = os.path.join(DATA_DIR, "github_dataset.parquet")
        if not os.path.exists(file_path):
            logger.error(f"Dataset file not found: {file_path}")
            return pd.DataFrame()
        
        df = pd.read_parquet(file_path)
        logger.info(f"Loaded dataset with {len(df)} rows")
        return df
    
    except Exception as e:
        logger.error(f"Error loading dataset: {str(e)}")
        return pd.DataFrame()

def preprocess_data(
    df: pd.DataFrame,
    leagues: List[str],
    start_year: int,
    end_year: int
) -> Tuple[pd.DataFrame, Dict[str, pd.Series]]:
    """Preprocess the data for model training."""
    try:
        # Filter by leagues and years
        mask = (
            df["league"].isin(leagues) &
            (df["season"] >= start_year) &
            (df["season"] <= end_year)
        )
        df = df[mask].copy()
        
        if df.empty:
            logger.error("No data after filtering")
            return pd.DataFrame(), {}
        
        # Prepare features and targets
        feature_engineer = FeatureEngineer()
        features_df = feature_engineer.prepare_features(df)
        
        targets = {
            "match_result": df["match_result"],
            "btts": df["btts"],
            "over_under": df["over_under"]
        }
        
        return features_df, targets
    
    except Exception as e:
        logger.error(f"Error preprocessing data: {str(e)}")
        return pd.DataFrame(), {}

def evaluate_model(
    model_type: str,
    features_df: pd.DataFrame,
    targets: Dict[str, pd.Series],
    test_size: float
) -> None:
    """Evaluate a specific model type."""
    try:
        logger.info(f"Evaluating {model_type} model...")
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            features_df,
            targets["match_result"],
            test_size=test_size,
            random_state=42
        )
        
        # Train and evaluate
        model = EnsembleModel(model_type=model_type)
        model.fit(X_train, y_train)
        
        evaluator = ModelEvaluator()
        metrics = evaluator.evaluate(model, X_test, y_test)
        
        # Save results
        results_file = os.path.join(
            RESULTS_DIR,
            f"{model_type}_results.json"
        )
        evaluator.save_results(metrics, results_file)
        
        logger.info(f"Evaluation complete for {model_type}")
    
    except Exception as e:
        logger.error(f"Error evaluating {model_type} model: {str(e)}")

def compare_models(
    advanced_model: str,
    traditional_model: str,
    features_df: pd.DataFrame,
    targets: Dict[str, pd.Series],
    test_size: float
) -> None:
    """Compare advanced and traditional models."""
    try:
        logger.info(
            f"Comparing {advanced_model} with {traditional_model}..."
        )
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            features_df,
            targets["match_result"],
            test_size=test_size,
            random_state=42
        )
        
        # Train both models
        advanced = EnsembleModel(model_type=advanced_model)
        traditional = EnsembleModel(model_type=traditional_model)
        
        advanced.fit(X_train, y_train)
        traditional.fit(X_train, y_train)
        
        # Evaluate both
        evaluator = ModelEvaluator()
        advanced_metrics = evaluator.evaluate(advanced, X_test, y_test)
        traditional_metrics = evaluator.evaluate(
            traditional, X_test, y_test
        )
        
        # Save comparison
        comparison = {
            "advanced": advanced_metrics,
            "traditional": traditional_metrics
        }
        
        results_file = os.path.join(
            RESULTS_DIR,
            f"{advanced_model}_vs_{traditional_model}_comparison.json"
        )
        evaluator.save_results(comparison, results_file)
        
        logger.info("Comparison complete")
    
    except Exception as e:
        logger.error(f"Error comparing models: {str(e)}")

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
    features_df, targets = preprocess_data(
        df, leagues, args.start_year, args.end_year
    )
    
    if features_df.empty:
        logger.error("Failed to preprocess data")
        return
    
    # Evaluate models
    if args.all:
        # Evaluate all models
        for model_type in ["xgboost", "lightgbm", "catboost", "nn"]:
            evaluate_model(model_type, features_df, targets, args.test_size)
    elif args.model_type:
        # Evaluate specific model
        evaluate_model(
            args.model_type, features_df, targets, args.test_size
        )
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
            compare_models(
                advanced_model,
                traditional_model,
                features_df,
                targets,
                args.test_size
            )
    
    logger.info("Model evaluation complete")

if __name__ == "__main__":
    main()
