"""
Create ML Models for Football Predictions

This script creates and saves ML models for football match predictions.
"""

import os
import sys
import logging
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
import xgboost as xgb

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def create_synthetic_data():
    """Create synthetic data for training the models."""
    # Create synthetic data for match results (home, draw, away)
    np.random.seed(42)
    n_samples = 1000
    
    # Features
    home_form = np.random.uniform(0.5, 2.5, n_samples)
    away_form = np.random.uniform(0.5, 2.5, n_samples)
    home_odds = np.random.uniform(1.5, 4.0, n_samples)
    draw_odds = np.random.uniform(2.5, 4.5, n_samples)
    away_odds = np.random.uniform(1.5, 4.0, n_samples)
    
    # Derived features
    form_diff = home_form - away_form
    odds_diff = home_odds - away_odds
    total_form = home_form + away_form
    total_odds = home_odds + draw_odds + away_odds
    
    # Create DataFrame
    data = pd.DataFrame({
        'home_form': home_form,
        'away_form': away_form,
        'home_odds': home_odds,
        'draw_odds': draw_odds,
        'away_odds': away_odds,
        'form_diff': form_diff,
        'odds_diff': odds_diff,
        'total_form': total_form,
        'total_odds': total_odds
    })
    
    # Generate target variables
    # Match result (home, draw, away)
    home_prob = 1 / home_odds
    draw_prob = 1 / draw_odds
    away_prob = 1 / away_odds
    
    # Normalize probabilities
    total_prob = home_prob + draw_prob + away_prob
    home_prob /= total_prob
    draw_prob /= total_prob
    away_prob /= total_prob
    
    # Adjust based on form
    form_factor = 0.1 * form_diff
    home_prob += form_factor
    away_prob -= form_factor
    
    # Ensure probabilities are valid
    home_prob = np.clip(home_prob, 0.1, 0.8)
    away_prob = np.clip(away_prob, 0.1, 0.8)
    draw_prob = 1 - home_prob - away_prob
    draw_prob = np.clip(draw_prob, 0.1, 0.8)
    
    # Normalize again
    total_prob = home_prob + draw_prob + away_prob
    home_prob /= total_prob
    draw_prob /= total_prob
    away_prob /= total_prob
    
    # Generate match results based on probabilities
    match_results = []
    for i in range(n_samples):
        result = np.random.choice(['home', 'draw', 'away'], p=[home_prob[i], draw_prob[i], away_prob[i]])
        match_results.append(result)
    
    data['match_result'] = match_results
    
    # Generate over/under results
    over_prob = 0.5 + 0.05 * (total_form - 2)
    over_prob = np.clip(over_prob, 0.3, 0.7)
    
    over_under_results = []
    for i in range(n_samples):
        result = np.random.choice(['over', 'under'], p=[over_prob[i], 1 - over_prob[i]])
        over_under_results.append(result)
    
    data['over_under'] = over_under_results
    
    # Generate BTTS results
    btts_prob = 0.5 + 0.05 * (total_form - 2)
    btts_prob = np.clip(btts_prob, 0.3, 0.7)
    
    btts_results = []
    for i in range(n_samples):
        result = np.random.choice(['yes', 'no'], p=[btts_prob[i], 1 - btts_prob[i]])
        btts_results.append(result)
    
    data['btts'] = btts_results
    
    return data

def create_and_save_models():
    """Create and save ML models for football predictions."""
    try:
        # Create directory for models
        os.makedirs('models/xgboost', exist_ok=True)
        
        # Create synthetic data
        logger.info("Creating synthetic data...")
        data = create_synthetic_data()
        
        # Split data into features and targets
        X = data.drop(['match_result', 'over_under', 'btts'], axis=1)
        y_match = data['match_result']
        y_over = data['over_under']
        y_btts = data['btts']
        
        # Split data into train and test sets
        X_train, X_test, y_match_train, y_match_test = train_test_split(X, y_match, test_size=0.2, random_state=42)
        _, _, y_over_train, y_over_test = train_test_split(X, y_over, test_size=0.2, random_state=42)
        _, _, y_btts_train, y_btts_test = train_test_split(X, y_btts, test_size=0.2, random_state=42)
        
        # Create and train match result model (XGBoost)
        logger.info("Training match result model...")
        match_model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=3,
            learning_rate=0.1,
            objective='multi:softprob',
            num_class=3,
            use_label_encoder=False,
            eval_metric='mlogloss',
            random_state=42
        )
        match_model.fit(
            X_train, 
            pd.Series(y_match_train).map({'home': 0, 'draw': 1, 'away': 2}),
            eval_set=[(X_test, pd.Series(y_match_test).map({'home': 0, 'draw': 1, 'away': 2}))],
            verbose=False
        )
        
        # Fix the classes to ensure they're correctly mapped
        match_model.classes_ = np.array(['home', 'draw', 'away'])
        
        # Create and train over/under model (XGBoost)
        logger.info("Training over/under model...")
        over_model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=3,
            learning_rate=0.1,
            objective='binary:logistic',
            use_label_encoder=False,
            eval_metric='logloss',
            random_state=42
        )
        over_model.fit(
            X_train, 
            pd.Series(y_over_train).map({'over': 0, 'under': 1}),
            eval_set=[(X_test, pd.Series(y_over_test).map({'over': 0, 'under': 1}))],
            verbose=False
        )
        
        # Fix the classes to ensure they're correctly mapped
        over_model.classes_ = np.array(['over', 'under'])
        
        # Create and train BTTS model (XGBoost)
        logger.info("Training BTTS model...")
        btts_model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=3,
            learning_rate=0.1,
            objective='binary:logistic',
            use_label_encoder=False,
            eval_metric='logloss',
            random_state=42
        )
        btts_model.fit(
            X_train, 
            pd.Series(y_btts_train).map({'yes': 0, 'no': 1}),
            eval_set=[(X_test, pd.Series(y_btts_test).map({'yes': 0, 'no': 1}))],
            verbose=False
        )
        
        # Fix the classes to ensure they're correctly mapped
        btts_model.classes_ = np.array(['yes', 'no'])
        
        # Save models
        logger.info("Saving models...")
        joblib.dump(match_model, 'models/xgboost/match_result_model.joblib')
        joblib.dump(over_model, 'models/xgboost/over_under_model.joblib')
        joblib.dump(btts_model, 'models/xgboost/btts_model.joblib')
        
        logger.info("Models created and saved successfully")
        
        # Test loading models
        logger.info("Testing model loading...")
        loaded_match_model = joblib.load('models/xgboost/match_result_model.joblib')
        loaded_over_model = joblib.load('models/xgboost/over_under_model.joblib')
        loaded_btts_model = joblib.load('models/xgboost/btts_model.joblib')
        
        # Make predictions with loaded models
        match_preds = loaded_match_model.predict_proba(X_test[:5])
        over_preds = loaded_over_model.predict_proba(X_test[:5])
        btts_preds = loaded_btts_model.predict_proba(X_test[:5])
        
        logger.info(f"Match result model classes: {loaded_match_model.classes_}")
        logger.info(f"Over/under model classes: {loaded_over_model.classes_}")
        logger.info(f"BTTS model classes: {loaded_btts_model.classes_}")
        
        logger.info("Models loaded and tested successfully")
        return True
    
    except Exception as e:
        logger.error(f"Error creating and saving models: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False

if __name__ == "__main__":
    logger.info("Starting ML model creation")
    success = create_and_save_models()
    if success:
        logger.info("ML models created and saved successfully")
    else:
        logger.error("ML model creation failed")
