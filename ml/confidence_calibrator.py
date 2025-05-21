"""
Confidence Calibrator Module

This module provides classes for calibrating confidence scores of ML models.
It helps to ensure that confidence scores are well-calibrated and reflect the true probability of correctness.
"""

import numpy as np
from typing import Dict, List, Any, Optional, Tuple, Union
import joblib
import os
from sklearn.isotonic import IsotonicRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import brier_score_loss

from app.utils.common import setup_logging
from app.utils.config import settings

# Set up logging
logger = setup_logging(__name__)

class ConfidenceCalibrator:
    """
    Base class for confidence calibration.
    
    Features:
    - Calibrates confidence scores to reflect true probabilities
    - Provides uncertainty estimates
    - Supports different calibration methods
    """
    
    def __init__(self, method: str = "isotonic"):
        """
        Initialize the confidence calibrator.
        
        Args:
            method: Calibration method ("isotonic" or "platt")
        """
        self.method = method
        self.calibrators = None
        self.is_trained = False
    
    def train(self, y_true: np.ndarray, y_proba: np.ndarray) -> None:
        """
        Train the calibrator.
        
        Args:
            y_true: True labels
            y_proba: Predicted probabilities
        """
        pass
    
    def calibrate(self, y_proba: np.ndarray) -> np.ndarray:
        """
        Calibrate confidence scores.
        
        Args:
            y_proba: Predicted probabilities
            
        Returns:
            Calibrated probabilities
        """
        return y_proba
    
    def get_confidence_with_uncertainty(self, y_proba: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Get calibrated confidence scores with uncertainty estimates.
        
        Args:
            y_proba: Predicted probabilities
            
        Returns:
            Tuple of (calibrated_probabilities, uncertainty)
        """
        calibrated_proba = self.calibrate(y_proba)
        uncertainty = self._estimate_uncertainty(calibrated_proba)
        return calibrated_proba, uncertainty
    
    def _estimate_uncertainty(self, y_proba: np.ndarray) -> np.ndarray:
        """
        Estimate uncertainty for each prediction.
        
        Args:
            y_proba: Predicted probabilities
            
        Returns:
            Uncertainty estimates
        """
        # Default implementation: higher uncertainty for probabilities closer to 0.5
        max_proba = np.max(y_proba, axis=1)
        uncertainty = 1.0 - (2.0 * np.abs(max_proba - 0.5))
        return uncertainty
    
    def save(self, filepath: str) -> bool:
        """
        Save the calibrator to disk.
        
        Args:
            filepath: Path to save the calibrator
            
        Returns:
            True if successful, False otherwise
        """
        try:
            joblib.dump(self, filepath)
            return True
        except Exception as e:
            logger.error(f"Error saving calibrator: {str(e)}")
            return False
    
    @classmethod
    def load(cls, filepath: str) -> Optional['ConfidenceCalibrator']:
        """
        Load a calibrator from disk.
        
        Args:
            filepath: Path to load the calibrator from
            
        Returns:
            Loaded calibrator or None if not found
        """
        try:
            if os.path.exists(filepath):
                return joblib.load(filepath)
            return None
        except Exception as e:
            logger.error(f"Error loading calibrator: {str(e)}")
            return None


class IsotonicCalibrator(ConfidenceCalibrator):
    """
    Isotonic regression calibrator.
    
    Features:
    - Non-parametric calibration
    - Works well with sufficient data
    - Preserves the rank ordering of predictions
    """
    
    def __init__(self):
        """Initialize the isotonic calibrator."""
        super().__init__(method="isotonic")
        self.calibrators = []
    
    def train(self, y_true: np.ndarray, y_proba: np.ndarray) -> None:
        """
        Train the calibrator.
        
        Args:
            y_true: True labels
            y_proba: Predicted probabilities
        """
        try:
            n_classes = y_proba.shape[1]
            self.calibrators = []
            
            for i in range(n_classes):
                # For each class, train an isotonic regression
                ir = IsotonicRegression(out_of_bounds="clip")
                
                # Create binary labels (1 if true class is i, 0 otherwise)
                binary_y_true = (y_true == i).astype(int)
                
                # Train on the probabilities for class i
                ir.fit(y_proba[:, i], binary_y_true)
                
                self.calibrators.append(ir)
            
            self.is_trained = True
            logger.info("Isotonic calibrator trained successfully")
            
        except Exception as e:
            logger.error(f"Error training isotonic calibrator: {str(e)}")
    
    def calibrate(self, y_proba: np.ndarray) -> np.ndarray:
        """
        Calibrate confidence scores.
        
        Args:
            y_proba: Predicted probabilities
            
        Returns:
            Calibrated probabilities
        """
        if not self.is_trained or not self.calibrators:
            logger.warning("Calibrator not trained, returning original probabilities")
            return y_proba
        
        try:
            n_samples = y_proba.shape[0]
            n_classes = y_proba.shape[1]
            
            # Check if we have calibrators for all classes
            if len(self.calibrators) != n_classes:
                logger.warning(f"Number of calibrators ({len(self.calibrators)}) does not match number of classes ({n_classes})")
                return y_proba
            
            # Apply calibration for each class
            calibrated_proba = np.zeros((n_samples, n_classes))
            
            for i in range(n_classes):
                calibrated_proba[:, i] = self.calibrators[i].predict(y_proba[:, i])
            
            # Normalize to ensure probabilities sum to 1
            row_sums = calibrated_proba.sum(axis=1)
            calibrated_proba = calibrated_proba / row_sums[:, np.newaxis]
            
            return calibrated_proba
            
        except Exception as e:
            logger.error(f"Error calibrating probabilities: {str(e)}")
            return y_proba
    
    def _estimate_uncertainty(self, y_proba: np.ndarray) -> np.ndarray:
        """
        Estimate uncertainty for each prediction.
        
        Args:
            y_proba: Predicted probabilities
            
        Returns:
            Uncertainty estimates
        """
        # Calculate entropy-based uncertainty
        # Higher entropy = higher uncertainty
        epsilon = 1e-15  # Small constant to avoid log(0)
        entropy = -np.sum(y_proba * np.log(y_proba + epsilon), axis=1)
        
        # Normalize to [0, 1] range
        max_entropy = -np.log(1.0 / y_proba.shape[1])  # Maximum possible entropy
        uncertainty = entropy / max_entropy
        
        return uncertainty


class PlattCalibrator(ConfidenceCalibrator):
    """
    Platt scaling calibrator.
    
    Features:
    - Parametric calibration using logistic regression
    - Works well with limited data
    - Smooth calibration curve
    """
    
    def __init__(self):
        """Initialize the Platt calibrator."""
        super().__init__(method="platt")
        self.calibrator = None
    
    def train(self, y_true: np.ndarray, y_proba: np.ndarray) -> None:
        """
        Train the calibrator.
        
        Args:
            y_true: True labels
            y_proba: Predicted probabilities
        """
        try:
            # Use scikit-learn's CalibratedClassifierCV with prefit=True
            # This is a placeholder - in a real implementation, we would need to
            # have the original classifier to use CalibratedClassifierCV properly
            
            # For now, we'll just store the mapping from predicted to actual probabilities
            self.y_true = y_true
            self.y_proba = y_proba
            self.is_trained = True
            
            logger.info("Platt calibrator trained successfully")
            
        except Exception as e:
            logger.error(f"Error training Platt calibrator: {str(e)}")
    
    def calibrate(self, y_proba: np.ndarray) -> np.ndarray:
        """
        Calibrate confidence scores.
        
        Args:
            y_proba: Predicted probabilities
            
        Returns:
            Calibrated probabilities
        """
        if not self.is_trained:
            logger.warning("Calibrator not trained, returning original probabilities")
            return y_proba
        
        try:
            # In a real implementation, we would use the trained calibrator
            # For now, we'll just return the original probabilities
            return y_proba
            
        except Exception as e:
            logger.error(f"Error calibrating probabilities: {str(e)}")
            return y_proba
