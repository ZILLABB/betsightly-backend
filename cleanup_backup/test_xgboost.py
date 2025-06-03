"""
Test XGBoost and OpenMP

This script tests if XGBoost is working properly with OpenMP.
"""

import os
import sys
import logging
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.datasets import make_classification
from sklearn.model_selection import train_test_split

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def test_xgboost():
    """Test if XGBoost is working properly."""
    try:
        # Print XGBoost version
        logger.info(f"XGBoost version: {xgb.__version__}")
        
        # Check if XGBoost is built with OpenMP
        logger.info(f"XGBoost build info: {xgb.build_info()}")
        
        # Create a simple dataset
        X, y = make_classification(n_samples=1000, n_features=10, random_state=42)
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        
        # Create DMatrix
        dtrain = xgb.DMatrix(X_train, label=y_train)
        dtest = xgb.DMatrix(X_test, label=y_test)
        
        # Set parameters
        params = {
            'max_depth': 3,
            'eta': 0.1,
            'objective': 'binary:logistic',
            'eval_metric': 'logloss',
            'nthread': 4  # Use 4 threads to test OpenMP
        }
        
        # Train model
        logger.info("Training XGBoost model...")
        model = xgb.train(params, dtrain, num_boost_round=10, evals=[(dtest, 'test')])
        
        # Save model
        model_path = 'test_model.joblib'
        model.save_model(model_path)
        logger.info(f"Model saved to {model_path}")
        
        # Load model
        loaded_model = xgb.Booster()
        loaded_model.load_model(model_path)
        logger.info("Model loaded successfully")
        
        # Make predictions
        preds = loaded_model.predict(dtest)
        logger.info(f"Predictions shape: {preds.shape}")
        logger.info(f"First 5 predictions: {preds[:5]}")
        
        # Clean up
        if os.path.exists(model_path):
            os.remove(model_path)
        
        logger.info("XGBoost test completed successfully")
        return True
    
    except Exception as e:
        logger.error(f"Error testing XGBoost: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False

if __name__ == "__main__":
    logger.info("Starting XGBoost test")
    success = test_xgboost()
    if success:
        logger.info("XGBoost is working properly")
    else:
        logger.error("XGBoost test failed")
