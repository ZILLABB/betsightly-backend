"""
XGBoost Models for Football Prediction

This module contains XGBoost-based models for various football prediction tasks.
"""

import numpy as np
import pandas as pd
import xgboost as xgb
from typing import Dict, List, Any, Tuple
import logging
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score

from app.ml.base_model import BaseModel
from app.utils.config import settings

# Set up logging
logger = logging.getLogger(__name__)

class XGBoostMatchResultModel(BaseModel):
    """
    XGBoost model for predicting match results (home win, draw, away win).
    """
    
    def __init__(self):
        """Initialize the model."""
        super().__init__("xgboost_match_result")
        self.model = None
        self.feature_scaler = None
        self.feature_names = None
        
    def train(self, X: pd.DataFrame, y: pd.Series) -> Dict[str, Any]:
        """
        Train the model.
        
        Args:
            X: Features DataFrame
            y: Target Series
            
        Returns:
            Dictionary with training results
        """
        try:
            # Save feature names
            self.feature_names = X.columns.tolist()
            
            # Scale features
            self.feature_scaler = StandardScaler()
            X_scaled = self.feature_scaler.fit_transform(X)
            
            # Split data
            X_train, X_test, y_train, y_test = train_test_split(
                X_scaled, y, test_size=0.2, random_state=42
            )
            
            # Define parameter grid for optimization
            param_grid = {
                'max_depth': [3, 5, 7],
                'learning_rate': [0.01, 0.1, 0.2],
                'n_estimators': [100, 200],
                'subsample': [0.8, 1.0],
                'colsample_bytree': [0.8, 1.0]
            }
            
            # Create base model
            base_model = xgb.XGBClassifier(
                objective='multi:softprob',
                num_class=3,  # Home, Draw, Away
                eval_metric='mlogloss',
                use_label_encoder=False,
                random_state=42
            )
            
            # Use grid search to find best parameters
            grid_search = GridSearchCV(
                estimator=base_model,
                param_grid=param_grid,
                cv=3,
                scoring='accuracy',
                verbose=1,
                n_jobs=-1
            )
            
            # Train model with best parameters
            grid_search.fit(X_train, y_train)
            self.model = grid_search.best_estimator_
            
            # Evaluate model
            y_pred = self.model.predict(X_test)
            accuracy = accuracy_score(y_test, y_pred)
            precision = precision_score(y_test, y_pred, average='weighted')
            recall = recall_score(y_test, y_pred, average='weighted')
            f1 = f1_score(y_test, y_pred, average='weighted')
            
            # Save model
            self.save()
            
            # Update model info
            self.model_info["metrics"] = {
                "accuracy": float(accuracy),
                "precision": float(precision),
                "recall": float(recall),
                "f1": float(f1),
                "best_params": grid_search.best_params_
            }
            
            return {
                "status": "success",
                "accuracy": float(accuracy),
                "precision": float(precision),
                "recall": float(recall),
                "f1": float(f1),
                "best_params": grid_search.best_params_,
                "message": f"XGBoost match result model trained successfully with accuracy: {accuracy:.4f}"
            }
            
        except Exception as e:
            logger.error(f"Error training XGBoost match result model: {str(e)}")
            return {
                "status": "error",
                "message": f"Error training XGBoost match result model: {str(e)}"
            }
    
    def predict(self, features: pd.DataFrame) -> Dict[str, Any]:
        """
        Make predictions.
        
        Args:
            features: Features DataFrame
            
        Returns:
            Dictionary with predictions
        """
        try:
            # Load model if not loaded
            if self.model is None:
                self._load_model()
                
            # Check if model is loaded
            if self.model is None:
                return {
                    "status": "error",
                    "message": "XGBoost match result model not loaded"
                }
                
            # Ensure features have the correct columns
            for col in self.feature_names:
                if col not in features.columns:
                    features[col] = 0.0
                    
            # Select and order features
            X = features[self.feature_names]
            
            # Scale features
            X_scaled = self.feature_scaler.transform(X)
            
            # Make predictions
            y_pred = self.model.predict(X_scaled)
            y_proba = self.model.predict_proba(X_scaled)
            
            # Map predictions to labels
            labels = ["H", "D", "A"]
            predictions = [labels[p] for p in y_pred]
            
            # Create confidence scores
            confidence = [float(p.max()) * 100 for p in y_proba]
            
            return {
                "status": "success",
                "predictions": predictions,
                "confidence": confidence,
                "probabilities": y_proba.tolist()
            }
            
        except Exception as e:
            logger.error(f"Error predicting with XGBoost match result model: {str(e)}")
            return {
                "status": "error",
                "message": f"Error predicting with XGBoost match result model: {str(e)}"
            }
