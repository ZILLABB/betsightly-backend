"""
Evaluate Model

This script evaluates the performance of the football prediction models.
It uses a test set of matches to measure accuracy, precision, recall, and F1 score.
"""

import os
import sys
import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Tuple
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix, classification_report

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
EVALUATION_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "evaluation")
os.makedirs(EVALUATION_DIR, exist_ok=True)

def load_data() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Load data for evaluation.
    
    Returns:
        Tuple of (features_df, results_df, historical_df)
    """
    # Check if files exist
    if not os.path.exists(FEATURES_FILE) or not os.path.exists(RESULTS_FILE):
        raise FileNotFoundError(
            f"Data files not found. Please run fetch_football_data_github.py first."
        )
    
    # Load data
    features_df = pd.read_parquet(FEATURES_FILE)
    results_df = pd.read_parquet(RESULTS_FILE)
    
    # Load raw historical data
    historical_df = pd.read_parquet(os.path.join(HISTORICAL_DIR, "raw", "matches.parquet"))
    
    logger.info(f"Loaded {len(features_df)} matches for evaluation")
    
    return features_df, results_df, historical_df

def prepare_test_set(features_df: pd.DataFrame, results_df: pd.DataFrame, test_size: float = 0.2) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Prepare a test set for evaluation.
    
    Args:
        features_df: DataFrame containing features
        results_df: DataFrame containing results
        test_size: Proportion of data to use for testing
        
    Returns:
        Tuple of (test_features, test_results)
    """
    # Merge features and results
    data = pd.merge(features_df, results_df, on="match_id")
    
    # Sort by date
    if 'date' in data.columns:
        data['date'] = pd.to_datetime(data['date'])
        data = data.sort_values('date')
    
    # Use the most recent matches for testing
    test_count = int(len(data) * test_size)
    test_data = data.tail(test_count)
    
    # Split back into features and results
    test_features = test_data.drop(['match_result', 'over_2_5', 'btts', 'home_score', 'away_score'], axis=1, errors='ignore')
    test_results = test_data[['match_id', 'match_result', 'over_2_5', 'btts']]
    
    logger.info(f"Prepared test set with {len(test_features)} matches")
    
    return test_features, test_results

def evaluate_model(test_features: pd.DataFrame, test_results: pd.DataFrame, historical_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Evaluate the model on the test set.
    
    Args:
        test_features: DataFrame containing test features
        test_results: DataFrame containing test results
        historical_df: DataFrame containing raw historical match data
        
    Returns:
        Dictionary with evaluation results
    """
    # Set historical data for feature engineering
    feature_engineer.set_historical_data(historical_df)
    
    # Prepare predictions and actual values
    predictions = {
        'match_result': [],
        'over_under': [],
        'btts': []
    }
    
    actuals = {
        'match_result': [],
        'over_under': [],
        'btts': []
    }
    
    # Make predictions for each match in the test set
    for i, row in test_features.iterrows():
        try:
            # Create fixture data
            fixture_data = {
                'fixture': {
                    'id': row['match_id'],
                    'date': row['date'] if 'date' in row else datetime.now().strftime("%Y-%m-%d")
                },
                'teams': {
                    'home': {'name': row['home_team']},
                    'away': {'name': row['away_team']}
                },
                'league': {
                    'name': row['competition_name'] if 'competition_name' in row else 'Unknown',
                    'season': row['season'] if 'season' in row else 'Unknown'
                }
            }
            
            # Get actual values
            match_id = row['match_id']
            actual_result = test_results[test_results['match_id'] == match_id]['match_result'].values[0]
            actual_over_under = test_results[test_results['match_id'] == match_id]['over_2_5'].values[0]
            actual_btts = test_results[test_results['match_id'] == match_id]['btts'].values[0]
            
            # Make prediction
            prediction_result = ensemble_model.predict(fixture_data, historical_df)
            
            if prediction_result["status"] == "success":
                # Extract predictions
                for pred in prediction_result["predictions"]:
                    if pred["prediction_type"] == "Match Result":
                        if pred["prediction"] == "Home Win":
                            predictions['match_result'].append("H")
                        elif pred["prediction"] == "Draw":
                            predictions['match_result'].append("D")
                        else:  # Away Win
                            predictions['match_result'].append("A")
                        actuals['match_result'].append(actual_result)
                    
                    elif pred["prediction_type"] == "Over/Under":
                        if pred["prediction"] == "Over 2.5":
                            predictions['over_under'].append(1)
                        else:  # Under 2.5
                            predictions['over_under'].append(0)
                        actuals['over_under'].append(actual_over_under)
                    
                    elif pred["prediction_type"] == "BTTS":
                        if pred["prediction"] == "Yes":
                            predictions['btts'].append(1)
                        else:  # No
                            predictions['btts'].append(0)
                        actuals['btts'].append(actual_btts)
        
        except Exception as e:
            logger.error(f"Error evaluating match {row['match_id']}: {str(e)}")
    
    # Calculate metrics
    metrics = {}
    
    for pred_type in ['match_result', 'over_under', 'btts']:
        if len(predictions[pred_type]) > 0:
            metrics[pred_type] = {
                'accuracy': accuracy_score(actuals[pred_type], predictions[pred_type]),
                'precision': precision_score(actuals[pred_type], predictions[pred_type], average='weighted') if pred_type != 'match_result' else precision_score(actuals[pred_type], predictions[pred_type], average='weighted', labels=np.unique(actuals[pred_type])),
                'recall': recall_score(actuals[pred_type], predictions[pred_type], average='weighted') if pred_type != 'match_result' else recall_score(actuals[pred_type], predictions[pred_type], average='weighted', labels=np.unique(actuals[pred_type])),
                'f1': f1_score(actuals[pred_type], predictions[pred_type], average='weighted') if pred_type != 'match_result' else f1_score(actuals[pred_type], predictions[pred_type], average='weighted', labels=np.unique(actuals[pred_type])),
                'confusion_matrix': confusion_matrix(actuals[pred_type], predictions[pred_type]).tolist(),
                'classification_report': classification_report(actuals[pred_type], predictions[pred_type], output_dict=True)
            }
    
    logger.info("Model evaluation completed")
    
    return {
        'metrics': metrics,
        'predictions': predictions,
        'actuals': actuals
    }

def generate_evaluation_report(evaluation_results: Dict[str, Any]) -> None:
    """
    Generate an evaluation report.
    
    Args:
        evaluation_results: Dictionary with evaluation results
    """
    # Create report directory
    report_dir = os.path.join(EVALUATION_DIR, f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(report_dir, exist_ok=True)
    
    # Generate metrics report
    metrics = evaluation_results['metrics']
    
    with open(os.path.join(report_dir, "metrics.txt"), "w") as f:
        f.write("# Football Prediction Model Evaluation\n\n")
        f.write(f"Evaluation Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        for pred_type, metric in metrics.items():
            f.write(f"## {pred_type.replace('_', ' ').title()} Prediction\n\n")
            f.write(f"Accuracy: {metric['accuracy']:.4f}\n")
            f.write(f"Precision: {metric['precision']:.4f}\n")
            f.write(f"Recall: {metric['recall']:.4f}\n")
            f.write(f"F1 Score: {metric['f1']:.4f}\n\n")
            
            f.write("Classification Report:\n")
            for label, values in metric['classification_report'].items():
                if isinstance(values, dict):
                    f.write(f"  {label}: precision={values['precision']:.4f}, recall={values['recall']:.4f}, f1-score={values['f1-score']:.4f}, support={values['support']}\n")
            f.write("\n")
    
    # Generate confusion matrix plots
    for pred_type, metric in metrics.items():
        plt.figure(figsize=(8, 6))
        cm = np.array(metric['confusion_matrix'])
        
        if pred_type == 'match_result':
            labels = ['H', 'D', 'A']
            labels = labels[:len(cm)]  # In case some classes are missing
        else:
            labels = ['0', '1']
        
        sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', xticklabels=labels, yticklabels=labels)
        plt.xlabel('Predicted')
        plt.ylabel('Actual')
        plt.title(f'{pred_type.replace("_", " ").title()} Confusion Matrix')
        plt.tight_layout()
        plt.savefig(os.path.join(report_dir, f"{pred_type}_confusion_matrix.png"))
        plt.close()
    
    logger.info(f"Evaluation report generated at {report_dir}")

def main():
    """Main function to evaluate the model."""
    try:
        # Load data
        features_df, results_df, historical_df = load_data()
        
        # Prepare test set
        test_features, test_results = prepare_test_set(features_df, results_df)
        
        # Evaluate model
        evaluation_results = evaluate_model(test_features, test_results, historical_df)
        
        # Generate evaluation report
        generate_evaluation_report(evaluation_results)
        
        # Print summary
        for pred_type, metric in evaluation_results['metrics'].items():
            logger.info(f"{pred_type.replace('_', ' ').title()} Accuracy: {metric['accuracy']:.4f}")
        
        logger.info("Model evaluation completed successfully")
    
    except Exception as e:
        logger.error(f"Error evaluating model: {str(e)}")
        raise

if __name__ == "__main__":
    main()
