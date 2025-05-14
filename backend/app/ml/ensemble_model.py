"""
Ensemble Model Module

This module provides an ensemble machine learning model for football match prediction.
It combines multiple algorithms to improve prediction accuracy.
"""

import os
import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import joblib

from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, VotingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, log_loss
import xgboost as xgb
import lightgbm as lgb

from app.config import settings
from app.ml.feature_engineering import feature_engineer

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FootballEnsembleModel:
    """
    Ensemble machine learning model for football match prediction.
    
    Features:
    - Combines multiple algorithms (Random Forest, XGBoost, LightGBM, etc.)
    - Uses advanced feature engineering
    - Provides calibrated probability estimates
    - Supports different prediction types (match result, over/under, BTTS)
    """
    
    def __init__(self):
        """Initialize the ensemble model."""
        self.model_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), settings.MODEL_DIR)
        os.makedirs(self.model_dir, exist_ok=True)
        
        # Initialize models
        self.match_result_model = None
        self.over_under_model = None
        self.btts_model = None
        
        # Initialize feature scaler
        self.feature_scaler = None
        
        # Initialize feature names
        self.feature_names = None
        
        # Load models if they exist
        self.load_models()
    
    def load_models(self) -> bool:
        """
        Load trained models from disk.
        
        Returns:
            True if models were loaded successfully, False otherwise
        """
        try:
            match_result_path = os.path.join(self.model_dir, "match_result_ensemble.joblib")
            over_under_path = os.path.join(self.model_dir, "over_under_ensemble.joblib")
            btts_path = os.path.join(self.model_dir, "btts_ensemble.joblib")
            scaler_path = os.path.join(self.model_dir, "feature_scaler.joblib")
            feature_names_path = os.path.join(self.model_dir, "feature_names.joblib")
            
            if os.path.exists(match_result_path):
                self.match_result_model = joblib.load(match_result_path)
                logger.info("Match result ensemble model loaded successfully")
            
            if os.path.exists(over_under_path):
                self.over_under_model = joblib.load(over_under_path)
                logger.info("Over/under ensemble model loaded successfully")
            
            if os.path.exists(btts_path):
                self.btts_model = joblib.load(btts_path)
                logger.info("BTTS ensemble model loaded successfully")
            
            if os.path.exists(scaler_path):
                self.feature_scaler = joblib.load(scaler_path)
                logger.info("Feature scaler loaded successfully")
            
            if os.path.exists(feature_names_path):
                self.feature_names = joblib.load(feature_names_path)
                logger.info("Feature names loaded successfully")
            
            return self.match_result_model is not None
        
        except Exception as e:
            logger.error(f"Error loading models: {str(e)}")
            return False
    
    def save_models(self) -> None:
        """Save trained models to disk."""
        try:
            if self.match_result_model:
                joblib.dump(self.match_result_model, os.path.join(self.model_dir, "match_result_ensemble.joblib"))
                logger.info("Match result ensemble model saved successfully")
            
            if self.over_under_model:
                joblib.dump(self.over_under_model, os.path.join(self.model_dir, "over_under_ensemble.joblib"))
                logger.info("Over/under ensemble model saved successfully")
            
            if self.btts_model:
                joblib.dump(self.btts_model, os.path.join(self.model_dir, "btts_ensemble.joblib"))
                logger.info("BTTS ensemble model saved successfully")
            
            if self.feature_scaler:
                joblib.dump(self.feature_scaler, os.path.join(self.model_dir, "feature_scaler.joblib"))
                logger.info("Feature scaler saved successfully")
            
            if self.feature_names is not None:
                joblib.dump(self.feature_names, os.path.join(self.model_dir, "feature_names.joblib"))
                logger.info("Feature names saved successfully")
        
        except Exception as e:
            logger.error(f"Error saving models: {str(e)}")
    
    def train(self, features_df: pd.DataFrame, results_df: pd.DataFrame, historical_df: pd.DataFrame) -> Dict[str, Any]:
        """
        Train the ensemble models on historical data.
        
        Args:
            features_df: DataFrame containing features
            results_df: DataFrame containing results
            historical_df: DataFrame containing raw historical match data
            
        Returns:
            Dictionary with training results
        """
        try:
            logger.info(f"Training ensemble models on {len(features_df)} matches")
            
            # Set historical data for feature engineering
            feature_engineer.set_historical_data(historical_df)
            
            # Engineer features
            logger.info("Engineering features...")
            engineered_features = feature_engineer.engineer_features(features_df)
            
            # Merge with results
            data = pd.merge(engineered_features, results_df, on="match_id")
            
            # Preprocess data
            X, y_match_result, y_over_under, y_btts, feature_names = self._preprocess_data(data)
            
            # Save feature names
            self.feature_names = feature_names
            
            # Create feature scaler
            self.feature_scaler = StandardScaler()
            X_scaled = self.feature_scaler.fit_transform(X)
            
            # Split data into train and test sets
            X_train, X_test, y_mr_train, y_mr_test = train_test_split(
                X_scaled, y_match_result, test_size=0.2, random_state=42
            )
            _, _, y_ou_train, y_ou_test = train_test_split(
                X_scaled, y_over_under, test_size=0.2, random_state=42
            )
            _, _, y_btts_train, y_btts_test = train_test_split(
                X_scaled, y_btts, test_size=0.2, random_state=42
            )
            
            # Train match result model
            logger.info("Training match result ensemble model...")
            self.match_result_model = self._train_match_result_model(X_train, y_mr_train, X_test, y_mr_test)
            
            # Train over/under model
            logger.info("Training over/under ensemble model...")
            self.over_under_model = self._train_over_under_model(X_train, y_ou_train, X_test, y_ou_test)
            
            # Train BTTS model
            logger.info("Training BTTS ensemble model...")
            self.btts_model = self._train_btts_model(X_train, y_btts_train, X_test, y_btts_test)
            
            # Save models
            self.save_models()
            
            # Evaluate models
            mr_accuracy = accuracy_score(y_mr_test, self.match_result_model.predict(X_test))
            ou_accuracy = accuracy_score(y_ou_test, self.over_under_model.predict(X_test))
            btts_accuracy = accuracy_score(y_btts_test, self.btts_model.predict(X_test))
            
            return {
                "status": "success",
                "match_result_accuracy": mr_accuracy,
                "over_under_accuracy": ou_accuracy,
                "btts_accuracy": btts_accuracy,
                "trained_at": datetime.now().isoformat()
            }
        
        except Exception as e:
            logger.error(f"Error training ensemble models: {str(e)}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def predict(self, fixture_data: Dict[str, Any], historical_df: pd.DataFrame = None) -> Dict[str, Any]:
        """
        Make predictions for a fixture.
        
        Args:
            fixture_data: Dictionary containing fixture data
            historical_df: DataFrame containing historical match data (optional)
            
        Returns:
            Dictionary with predictions
        """
        try:
            # Check if models are loaded
            if not self.match_result_model or not self.over_under_model or not self.btts_model:
                if not self.load_models():
                    return {
                        "status": "error",
                        "message": "Models not loaded"
                    }
            
            # Extract features
            features = self._extract_features(fixture_data, historical_df)
            
            if features is None:
                return {
                    "status": "error",
                    "message": "Could not extract features"
                }
            
            # Scale features
            if self.feature_scaler:
                features_scaled = self.feature_scaler.transform([features])
            else:
                features_scaled = [features]
            
            # Make predictions
            match_result_pred = self.match_result_model.predict(features_scaled)[0]
            match_result_proba = self.match_result_model.predict_proba(features_scaled)[0]
            
            over_under_pred = self.over_under_model.predict(features_scaled)[0]
            over_under_proba = self.over_under_model.predict_proba(features_scaled)[0]
            
            btts_pred = self.btts_model.predict(features_scaled)[0]
            btts_proba = self.btts_model.predict_proba(features_scaled)[0]
            
            # Get confidence scores
            match_result_confidence = float(np.max(match_result_proba))
            over_under_confidence = float(np.max(over_under_proba))
            btts_confidence = float(np.max(btts_proba))
            
            # Create predictions
            predictions = []
            
            # Match result prediction
            if match_result_pred == "H":
                predictions.append({
                    "prediction_type": "Match Result",
                    "prediction": "Home Win",
                    "odds": self._calculate_odds(match_result_confidence),
                    "confidence": match_result_confidence * 100,
                    "explanation": f"Home team win predicted with {match_result_confidence:.1%} confidence"
                })
            elif match_result_pred == "D":
                predictions.append({
                    "prediction_type": "Match Result",
                    "prediction": "Draw",
                    "odds": self._calculate_odds(match_result_confidence),
                    "confidence": match_result_confidence * 100,
                    "explanation": f"Draw predicted with {match_result_confidence:.1%} confidence"
                })
            else:  # "A"
                predictions.append({
                    "prediction_type": "Match Result",
                    "prediction": "Away Win",
                    "odds": self._calculate_odds(match_result_confidence),
                    "confidence": match_result_confidence * 100,
                    "explanation": f"Away team win predicted with {match_result_confidence:.1%} confidence"
                })
            
            # Over/under prediction
            if over_under_pred == 1:  # Over 2.5
                predictions.append({
                    "prediction_type": "Over/Under",
                    "prediction": "Over 2.5",
                    "odds": self._calculate_odds(over_under_confidence),
                    "confidence": over_under_confidence * 100,
                    "explanation": f"Over 2.5 goals predicted with {over_under_confidence:.1%} confidence"
                })
            else:  # Under 2.5
                predictions.append({
                    "prediction_type": "Over/Under",
                    "prediction": "Under 2.5",
                    "odds": self._calculate_odds(over_under_confidence),
                    "confidence": over_under_confidence * 100,
                    "explanation": f"Under 2.5 goals predicted with {over_under_confidence:.1%} confidence"
                })
            
            # BTTS prediction
            if btts_pred == 1:  # Yes
                predictions.append({
                    "prediction_type": "BTTS",
                    "prediction": "Yes",
                    "odds": self._calculate_odds(btts_confidence),
                    "confidence": btts_confidence * 100,
                    "explanation": f"Both teams to score predicted with {btts_confidence:.1%} confidence"
                })
            else:  # No
                predictions.append({
                    "prediction_type": "BTTS",
                    "prediction": "No",
                    "odds": self._calculate_odds(btts_confidence),
                    "confidence": btts_confidence * 100,
                    "explanation": f"Both teams not to score predicted with {btts_confidence:.1%} confidence"
                })
            
            return {
                "status": "success",
                "predictions": predictions
            }
        
        except Exception as e:
            logger.error(f"Error making predictions: {str(e)}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def _preprocess_data(self, data: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series, List[str]]:
        """
        Preprocess data for training.
        
        Args:
            data: DataFrame containing features and targets
        
        Returns:
            Tuple of (X, y_match_result, y_over_under, y_btts, feature_names)
        """
        # Create copy to avoid modifying original data
        df = data.copy()
        
        # Drop non-feature columns
        drop_columns = [
            'match_id', 'date', 'home_team', 'away_team', 'home_score', 'away_score',
            'match_result', 'over_2_5', 'btts', 'competition_name', 'season'
        ]
        
        for col in drop_columns:
            if col in df.columns:
                df = df.drop(col, axis=1)
        
        # Extract target variables
        y_match_result = data['match_result']
        y_over_under = data['over_2_5']
        y_btts = data['btts']
        
        # Drop target columns
        X = df.drop(['match_result', 'over_2_5', 'btts'], axis=1, errors='ignore')
        
        # Handle missing values
        X = X.fillna(0)
        
        # Convert categorical variables to numeric
        for col in X.select_dtypes(include=['object']).columns:
            X[col] = pd.factorize(X[col])[0]
        
        # Get feature names
        feature_names = X.columns.tolist()
        
        return X, y_match_result, y_over_under, y_btts, feature_names
    
    def _train_match_result_model(self, X_train: np.ndarray, y_train: pd.Series, X_test: np.ndarray, y_test: pd.Series) -> VotingClassifier:
        """
        Train match result prediction model.
        
        Args:
            X_train: Training features
            y_train: Training target
            X_test: Test features
            y_test: Test target
        
        Returns:
            Trained model
        """
        # Create base models
        rf = RandomForestClassifier(n_estimators=100, random_state=42)
        xgb_model = xgb.XGBClassifier(n_estimators=100, random_state=42)
        lgb_model = lgb.LGBMClassifier(n_estimators=100, random_state=42)
        gb = GradientBoostingClassifier(n_estimators=100, random_state=42)
        
        # Create voting classifier
        ensemble = VotingClassifier(
            estimators=[
                ('rf', rf),
                ('xgb', xgb_model),
                ('lgb', lgb_model),
                ('gb', gb)
            ],
            voting='soft'
        )
        
        # Train model
        ensemble.fit(X_train, y_train)
        
        # Evaluate model
        y_pred = ensemble.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)
        
        logger.info(f"Match result ensemble model accuracy: {accuracy:.4f}")
        
        return ensemble
    
    def _train_over_under_model(self, X_train: np.ndarray, y_train: pd.Series, X_test: np.ndarray, y_test: pd.Series) -> VotingClassifier:
        """
        Train over/under prediction model.
        
        Args:
            X_train: Training features
            y_train: Training target
            X_test: Test features
            y_test: Test target
        
        Returns:
            Trained model
        """
        # Create base models
        rf = RandomForestClassifier(n_estimators=100, random_state=42)
        xgb_model = xgb.XGBClassifier(n_estimators=100, random_state=42)
        lgb_model = lgb.LGBMClassifier(n_estimators=100, random_state=42)
        gb = GradientBoostingClassifier(n_estimators=100, random_state=42)
        
        # Create voting classifier
        ensemble = VotingClassifier(
            estimators=[
                ('rf', rf),
                ('xgb', xgb_model),
                ('lgb', lgb_model),
                ('gb', gb)
            ],
            voting='soft'
        )
        
        # Train model
        ensemble.fit(X_train, y_train)
        
        # Evaluate model
        y_pred = ensemble.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)
        
        logger.info(f"Over/under ensemble model accuracy: {accuracy:.4f}")
        
        return ensemble
    
    def _train_btts_model(self, X_train: np.ndarray, y_train: pd.Series, X_test: np.ndarray, y_test: pd.Series) -> VotingClassifier:
        """
        Train BTTS prediction model.
        
        Args:
            X_train: Training features
            y_train: Training target
            X_test: Test features
            y_test: Test target
        
        Returns:
            Trained model
        """
        # Create base models
        rf = RandomForestClassifier(n_estimators=100, random_state=42)
        xgb_model = xgb.XGBClassifier(n_estimators=100, random_state=42)
        lgb_model = lgb.LGBMClassifier(n_estimators=100, random_state=42)
        gb = GradientBoostingClassifier(n_estimators=100, random_state=42)
        
        # Create voting classifier
        ensemble = VotingClassifier(
            estimators=[
                ('rf', rf),
                ('xgb', xgb_model),
                ('lgb', lgb_model),
                ('gb', gb)
            ],
            voting='soft'
        )
        
        # Train model
        ensemble.fit(X_train, y_train)
        
        # Evaluate model
        y_pred = ensemble.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)
        
        logger.info(f"BTTS ensemble model accuracy: {accuracy:.4f}")
        
        return ensemble
    
    def _extract_features(self, fixture_data: Dict[str, Any], historical_df: pd.DataFrame = None) -> Optional[List[float]]:
        """
        Extract features from fixture data for prediction.
        
        Args:
            fixture_data: Dictionary containing fixture data
            historical_df: DataFrame containing historical match data (optional)
            
        Returns:
            List of feature values or None if features could not be extracted
        """
        try:
            # Create a DataFrame with the fixture data
            fixture_df = pd.DataFrame([{
                'match_id': f"prediction_{fixture_data.get('fixture', {}).get('id', 'unknown')}",
                'date': fixture_data.get('fixture', {}).get('date'),
                'home_team': fixture_data.get('teams', {}).get('home', {}).get('name'),
                'away_team': fixture_data.get('teams', {}).get('away', {}).get('name'),
                'competition_name': fixture_data.get('league', {}).get('name'),
                'season': fixture_data.get('league', {}).get('season')
            }])
            
            # If historical data is provided, use it for feature engineering
            if historical_df is not None:
                feature_engineer.set_historical_data(historical_df)
            
            # Engineer features
            engineered_features = feature_engineer.engineer_features(fixture_df)
            
            # Drop non-feature columns
            drop_columns = [
                'match_id', 'date', 'home_team', 'away_team', 'competition_name', 'season'
            ]
            
            for col in drop_columns:
                if col in engineered_features.columns:
                    engineered_features = engineered_features.drop(col, axis=1)
            
            # Handle missing values
            engineered_features = engineered_features.fillna(0)
            
            # Convert categorical variables to numeric
            for col in engineered_features.select_dtypes(include=['object']).columns:
                engineered_features[col] = pd.factorize(engineered_features[col])[0]
            
            # Ensure all feature names are present
            if self.feature_names is not None:
                for feature in self.feature_names:
                    if feature not in engineered_features.columns:
                        engineered_features[feature] = 0
                
                # Reorder columns to match training data
                engineered_features = engineered_features[self.feature_names]
            
            # Convert to list
            features = engineered_features.iloc[0].tolist()
            
            return features
        
        except Exception as e:
            logger.error(f"Error extracting features: {str(e)}")
            return None
    
    def _calculate_odds(self, confidence: float) -> float:
        """
        Calculate odds based on confidence.
        
        Args:
            confidence: Confidence score (0-1)
        
        Returns:
            Odds value
        """
        # Simple formula: odds = 1 / probability
        # Add a small margin for the bookmaker
        margin = 0.1
        probability = confidence - margin
        
        # Ensure probability is between 0.1 and 0.9
        probability = max(0.1, min(0.9, probability))
        
        odds = 1 / probability
        
        # Round to 2 decimal places
        return round(odds, 2)

# Create a singleton instance
ensemble_model = FootballEnsembleModel()
