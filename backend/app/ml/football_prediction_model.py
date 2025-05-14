"""
Football Prediction Model

This module provides a machine learning model for predicting football match outcomes.
It uses the ensemble model for improved prediction accuracy.
"""

import os
import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import joblib

from app.config import settings
from app.ml.ensemble_model import ensemble_model

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FootballPredictionModel:
    """
    Machine learning model for predicting football match outcomes.
    
    Features:
    - Uses ensemble model for improved prediction accuracy
    - Predicts match outcomes (home win, draw, away win)
    - Predicts over/under goals
    - Predicts both teams to score
    - Provides confidence scores for predictions
    """
    
    def __init__(self):
        """Initialize the football prediction model."""
        self.model_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), settings.MODEL_DIR)
        os.makedirs(self.model_dir, exist_ok=True)
        
        # Historical data for feature engineering
        self.historical_data = None
        
        # Load historical data if available
        self._load_historical_data()
    
    def _load_historical_data(self) -> bool:
        """
        Load historical data for feature engineering.
        
        Returns:
            True if data was loaded successfully, False otherwise
        """
        try:
            historical_data_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "data", "historical", "raw", "matches.parquet"
            )
            
            if os.path.exists(historical_data_path):
                self.historical_data = pd.read_parquet(historical_data_path)
                logger.info(f"Loaded {len(self.historical_data)} historical matches for feature engineering")
                return True
            else:
                logger.warning(f"Historical data file not found at {historical_data_path}")
                return False
        
        except Exception as e:
            logger.error(f"Error loading historical data: {str(e)}")
            return False
    
    def predict(self, fixture_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make predictions for a fixture.
        
        Args:
            fixture_data: Dictionary containing fixture data
        
        Returns:
            Dictionary with predictions
        """
        try:
            # Use ensemble model for prediction
            prediction_result = ensemble_model.predict(fixture_data, self.historical_data)
            
            # If ensemble model prediction fails, use fallback method
            if prediction_result["status"] != "success":
                logger.warning(f"Ensemble model prediction failed: {prediction_result.get('message')}")
                prediction_result = self._fallback_prediction(fixture_data)
            
            return prediction_result
        
        except Exception as e:
            logger.error(f"Error making predictions: {str(e)}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def _fallback_prediction(self, fixture_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fallback prediction method when ensemble model fails.
        
        Args:
            fixture_data: Dictionary containing fixture data
        
        Returns:
            Dictionary with predictions
        """
        try:
            # Extract basic information
            home_team = fixture_data.get("teams", {}).get("home", {}).get("name", "Unknown")
            away_team = fixture_data.get("teams", {}).get("away", {}).get("name", "Unknown")
            
            # Simple heuristic: home advantage
            home_win_prob = 0.45  # Home advantage
            away_win_prob = 0.30
            draw_prob = 0.25
            
            # Adjust based on team rankings if available
            home_rank = fixture_data.get("teams", {}).get("home", {}).get("position", 10)
            away_rank = fixture_data.get("teams", {}).get("away", {}).get("position", 10)
            
            if isinstance(home_rank, int) and isinstance(away_rank, int):
                # Adjust probabilities based on team rankings
                rank_diff = home_rank - away_rank
                
                # Positive rank_diff means away team is higher ranked
                if rank_diff > 0:
                    # Boost away team chances
                    adjustment = min(0.15, rank_diff * 0.01)
                    home_win_prob -= adjustment
                    away_win_prob += adjustment
                elif rank_diff < 0:
                    # Boost home team chances
                    adjustment = min(0.15, abs(rank_diff) * 0.01)
                    home_win_prob += adjustment
                    away_win_prob -= adjustment
            
            # Normalize probabilities
            total = home_win_prob + away_win_prob + draw_prob
            home_win_prob /= total
            away_win_prob /= total
            draw_prob /= total
            
            # Create predictions
            predictions = []
            
            # Match result prediction
            result_probs = [home_win_prob, draw_prob, away_win_prob]
            result_idx = np.argmax(result_probs)
            result_confidence = result_probs[result_idx]
            
            if result_idx == 0:  # Home win
                predictions.append({
                    "prediction_type": "Match Result",
                    "prediction": "Home Win",
                    "odds": self._calculate_odds(result_confidence),
                    "confidence": result_confidence * 100,
                    "explanation": f"Home team win predicted with {result_confidence:.1%} confidence"
                })
            elif result_idx == 1:  # Draw
                predictions.append({
                    "prediction_type": "Match Result",
                    "prediction": "Draw",
                    "odds": self._calculate_odds(result_confidence),
                    "confidence": result_confidence * 100,
                    "explanation": f"Draw predicted with {result_confidence:.1%} confidence"
                })
            else:  # Away win
                predictions.append({
                    "prediction_type": "Match Result",
                    "prediction": "Away Win",
                    "odds": self._calculate_odds(result_confidence),
                    "confidence": result_confidence * 100,
                    "explanation": f"Away team win predicted with {result_confidence:.1%} confidence"
                })
            
            # Over/under prediction
            over_prob = 0.55  # Slightly favor over 2.5 goals
            
            predictions.append({
                "prediction_type": "Over/Under",
                "prediction": "Over 2.5",
                "odds": self._calculate_odds(over_prob),
                "confidence": over_prob * 100,
                "explanation": f"Over 2.5 goals predicted with {over_prob:.1%} confidence"
            })
            
            # BTTS prediction
            btts_prob = 0.60  # Slightly favor both teams to score
            
            predictions.append({
                "prediction_type": "BTTS",
                "prediction": "Yes",
                "odds": self._calculate_odds(btts_prob),
                "confidence": btts_prob * 100,
                "explanation": f"Both teams to score predicted with {btts_prob:.1%} confidence"
            })
            
            return {
                "status": "success",
                "predictions": predictions
            }
        
        except Exception as e:
            logger.error(f"Error making fallback predictions: {str(e)}")
            return {
                "status": "error",
                "message": f"Fallback prediction failed: {str(e)}"
            }
    
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
football_prediction_model = FootballPredictionModel()
