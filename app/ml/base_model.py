"""
Base Model

This module contains the base model class for all ML models.
"""

import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime
import logging
import joblib
from typing import Dict, List, Tuple, Any, Union

from app.utils.common import ensure_directory_exists
from app.utils.config import settings

# Set up logging
logger = logging.getLogger(__name__)

class BaseModel:
    """
    Base class for all ML models.
    """

    def __init__(self, model_name: str):
        """
        Initialize the model.

        Args:
            model_name: Name of the model
        """
        self.model_name = model_name
        self.model = None
        self.feature_scaler = None
        self.feature_names = None
        self.model_path = os.path.join(settings.ml.MODEL_DIR, f"{model_name}.joblib")
        self.scaler_path = os.path.join(settings.ml.MODEL_DIR, f"{model_name}_scaler.joblib")
        self.features_path = os.path.join(settings.ml.MODEL_DIR, f"{model_name}_features.joblib")

    def train(self, X: pd.DataFrame, y: pd.Series) -> Dict[str, Any]:
        """
        Train the model.

        Args:
            X: Features DataFrame
            y: Target Series

        Returns:
            Dictionary with training results
        """
        raise NotImplementedError("Subclasses must implement train method")

    def predict(self, features: pd.DataFrame) -> Dict[str, Any]:
        """
        Make predictions.

        Args:
            features: Features DataFrame

        Returns:
            Dictionary with predictions
        """
        raise NotImplementedError("Subclasses must implement predict method")

    def save(self) -> bool:
        """
        Save the model to disk.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Ensure directory exists
            ensure_directory_exists(os.path.dirname(self.model_path))

            # Save model
            joblib.dump(self.model, self.model_path)

            # Save scaler
            if self.feature_scaler is not None:
                joblib.dump(self.feature_scaler, self.scaler_path)

            # Save feature names
            if self.feature_names is not None:
                joblib.dump(self.feature_names, self.features_path)

            # Save model info
            model_info = {
                "name": self.model_name,
                "version": "1.0.0",
                "created_at": datetime.now().isoformat(),
                "feature_names": self.feature_names
            }

            info_path = os.path.join(os.path.dirname(self.model_path), f"{self.model_name}_info.joblib")
            joblib.dump(model_info, info_path)

            logger.info(f"Model {self.model_name} saved to {self.model_path}")
            logger.info(f"Feature scaler saved to {self.scaler_path}")
            logger.info(f"Feature names saved to {self.features_path}")
            logger.info(f"Model info saved to {info_path}")

            return True

        except Exception as e:
            logger.error(f"Error saving model {self.model_name}: {str(e)}")
            return False

    def load(self) -> bool:
        """
        Load the model from disk.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Check if model exists
            if not os.path.exists(self.model_path):
                logger.error(f"Model file not found: {self.model_path}")
                return False

            # Load model
            self.model = joblib.load(self.model_path)

            # Load scaler
            if os.path.exists(self.scaler_path):
                self.feature_scaler = joblib.load(self.scaler_path)

            # Load feature names
            if os.path.exists(self.features_path):
                self.feature_names = joblib.load(self.features_path)

            logger.info(f"Model {self.model_name} loaded from {self.model_path}")

            return True

        except Exception as e:
            logger.error(f"Error loading model {self.model_name}: {str(e)}")
            return False
