"""
Test Model Loading

This script tests if we can load the ML models from the models directory.
"""

import os
import sys
import logging
import joblib
import numpy as np
import pandas as pd

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def test_model_loading():
    """Test if we can load the ML models."""
    try:
        # Try to load models from different directories
        model_dirs = ["models/xgboost", "models/enhanced", "models/advanced"]
        
        for model_dir in model_dirs:
            # Check if directory exists
            if os.path.exists(model_dir):
                logger.info(f"Found model directory: {model_dir}")
                
                # List all files in the directory
                model_files = [f for f in os.listdir(model_dir) if f.endswith('.joblib')]
                logger.info(f"Found {len(model_files)} model files: {model_files}")
                
                # Try to load each model
                for model_file in model_files:
                    model_path = os.path.join(model_dir, model_file)
                    try:
                        model = joblib.load(model_path)
                        logger.info(f"Successfully loaded model: {model_file}")
                        
                        # Check model type
                        logger.info(f"Model type: {type(model).__name__}")
                        
                        # Create a simple test input
                        test_input = pd.DataFrame({
                            'home_team': ['Test Team'],
                            'away_team': ['Opponent Team'],
                            'home_form': [1.5],
                            'away_form': [1.2],
                            'home_odds': [2.0],
                            'draw_odds': [3.0],
                            'away_odds': [3.5],
                            'form_diff': [0.3],
                            'odds_diff': [-1.5],
                            'total_form': [2.7],
                            'total_odds': [8.5],
                            'home_win_prob': [0.5],
                            'draw_prob': [0.3],
                            'away_win_prob': [0.2]
                        })
                        
                        # Try to get predictions
                        try:
                            if hasattr(model, 'predict_proba'):
                                predictions = model.predict_proba(test_input)
                                logger.info(f"Model prediction probabilities shape: {predictions.shape}")
                                logger.info(f"Model classes: {model.classes_}")
                                logger.info(f"Prediction probabilities: {predictions}")
                            else:
                                predictions = model.predict(test_input)
                                logger.info(f"Model predictions: {predictions}")
                        except Exception as e:
                            logger.error(f"Error making predictions with model {model_file}: {str(e)}")
                    
                    except Exception as e:
                        logger.error(f"Error loading model {model_file}: {str(e)}")
            else:
                logger.warning(f"Model directory not found: {model_dir}")
    
    except Exception as e:
        logger.error(f"Error testing model loading: {str(e)}")

if __name__ == "__main__":
    logger.info("Starting model loading test")
    test_model_loading()
    logger.info("Model loading test completed")
