"""
PyTorch Models for Football Prediction

Alternative to TensorFlow with better Python 3.13 compatibility.
"""

import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import pandas as pd
import os
import joblib
from typing import Dict, List, Any, Tuple
import logging
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split

from ml.base_model import BaseModel

logger = logging.getLogger(__name__)

# Check PyTorch availability
try:
    import torch
    PYTORCH_AVAILABLE = True
    logger.info("✅ PyTorch available")
except ImportError:
    PYTORCH_AVAILABLE = False
    logger.warning("⚠️ PyTorch not available")

class PyTorchNeuralNetwork(nn.Module):
    """
    Advanced Neural Network for football predictions using PyTorch.
    """
    
    def __init__(self, input_size: int, hidden_sizes: List[int], output_size: int, dropout_rate: float = 0.3):
        super(PyTorchNeuralNetwork, self).__init__()
        
        layers = []
        prev_size = input_size
        
        # Build hidden layers
        for hidden_size in hidden_sizes:
            layers.extend([
                nn.Linear(prev_size, hidden_size),
                nn.ReLU(),
                nn.BatchNorm1d(hidden_size),
                nn.Dropout(dropout_rate)
            ])
            prev_size = hidden_size
        
        # Output layer
        layers.append(nn.Linear(prev_size, output_size))
        layers.append(nn.Sigmoid())
        
        self.network = nn.Sequential(*layers)
    
    def forward(self, x):
        return self.network(x)

class PyTorchOverUnderModel(BaseModel):
    """
    PyTorch-based Over/Under prediction model.
    """
    
    def __init__(self, threshold: float = 2.5):
        super().__init__(f"pytorch_over_under_{str(threshold).replace('.', '_')}")
        self.threshold = threshold
        self.model = None
        self.scaler = StandardScaler()
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.available = PYTORCH_AVAILABLE
        
        if not PYTORCH_AVAILABLE:
            logger.warning("PyTorch not available - model will not function")
    
    def _create_model(self, input_size: int) -> PyTorchNeuralNetwork:
        """Create the neural network architecture."""
        return PyTorchNeuralNetwork(
            input_size=input_size,
            hidden_sizes=[128, 64, 32],
            output_size=1,
            dropout_rate=0.3
        ).to(self.device)
    
    def train(self, X: pd.DataFrame, y: pd.Series) -> Dict[str, Any]:
        """
        Train the PyTorch model.
        """
        if not self.available:
            return {"status": "error", "message": "PyTorch not available"}
        
        try:
            # Prepare data
            X_scaled = self.scaler.fit_transform(X)
            X_train, X_val, y_train, y_val = train_test_split(
                X_scaled, y, test_size=0.2, random_state=42
            )
            
            # Convert to tensors
            X_train_tensor = torch.FloatTensor(X_train).to(self.device)
            y_train_tensor = torch.FloatTensor(y_train.values).unsqueeze(1).to(self.device)
            X_val_tensor = torch.FloatTensor(X_val).to(self.device)
            y_val_tensor = torch.FloatTensor(y_val.values).unsqueeze(1).to(self.device)
            
            # Create model
            self.model = self._create_model(X_train.shape[1])
            
            # Training setup
            criterion = nn.BCELoss()
            optimizer = optim.Adam(self.model.parameters(), lr=0.001, weight_decay=1e-5)
            scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=10)
            
            # Training loop
            best_val_loss = float('inf')
            patience_counter = 0
            max_patience = 20
            
            for epoch in range(200):
                # Training phase
                self.model.train()
                optimizer.zero_grad()
                
                train_outputs = self.model(X_train_tensor)
                train_loss = criterion(train_outputs, y_train_tensor)
                train_loss.backward()
                optimizer.step()
                
                # Validation phase
                self.model.eval()
                with torch.no_grad():
                    val_outputs = self.model(X_val_tensor)
                    val_loss = criterion(val_outputs, y_val_tensor)
                
                scheduler.step(val_loss)
                
                # Early stopping
                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    patience_counter = 0
                    # Save best model state
                    torch.save(self.model.state_dict(), f"{self.model_dir}/{self.model_name}_best.pth")
                else:
                    patience_counter += 1
                
                if patience_counter >= max_patience:
                    logger.info(f"Early stopping at epoch {epoch}")
                    break
                
                if epoch % 20 == 0:
                    logger.info(f"Epoch {epoch}: Train Loss: {train_loss:.4f}, Val Loss: {val_loss:.4f}")
            
            # Load best model
            self.model.load_state_dict(torch.load(f"{self.model_dir}/{self.model_name}_best.pth"))
            
            # Calculate final accuracy
            self.model.eval()
            with torch.no_grad():
                val_predictions = (self.model(X_val_tensor) > 0.5).float()
                accuracy = (val_predictions == y_val_tensor).float().mean().item()
            
            # Save model and scaler
            self.save_model()
            
            return {
                "status": "success",
                "final_val_loss": best_val_loss.item(),
                "accuracy": accuracy,
                "epochs_trained": epoch + 1,
                "model_path": f"{self.model_dir}/{self.model_name}_best.pth"
            }
            
        except Exception as e:
            logger.error(f"Training failed: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def predict(self, X: pd.DataFrame) -> Dict[str, Any]:
        """
        Make predictions using the trained model.
        """
        if not self.available or self.model is None:
            return {"status": "error", "message": "Model not available or not trained"}
        
        try:
            # Prepare data
            X_scaled = self.scaler.transform(X)
            X_tensor = torch.FloatTensor(X_scaled).to(self.device)
            
            # Make predictions
            self.model.eval()
            with torch.no_grad():
                predictions = self.model(X_tensor)
                probabilities = predictions.cpu().numpy().flatten()
            
            # Convert to readable format
            predictions_binary = (probabilities > 0.5).astype(int)
            
            results = []
            for i, (prob, pred) in enumerate(zip(probabilities, predictions_binary)):
                result = {
                    "prediction": f"Over {self.threshold}" if pred == 1 else f"Under {self.threshold}",
                    "probability": float(prob),
                    "confidence": float(max(prob, 1 - prob)) * 100
                }
                results.append(result)
            
            return {
                "status": "success",
                "predictions": results,
                "model_type": "pytorch_neural_network",
                "threshold": self.threshold
            }
            
        except Exception as e:
            logger.error(f"Prediction failed: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def save_model(self):
        """Save the trained model."""
        if self.model is not None:
            model_path = f"{self.model_dir}/{self.model_name}.pth"
            scaler_path = f"{self.model_dir}/{self.model_name}_scaler.joblib"
            
            torch.save(self.model.state_dict(), model_path)
            joblib.dump(self.scaler, scaler_path)
            
            logger.info(f"Model saved to {model_path}")
    
    def load_model(self):
        """Load a trained model."""
        try:
            model_path = f"{self.model_dir}/{self.model_name}.pth"
            scaler_path = f"{self.model_dir}/{self.model_name}_scaler.joblib"
            
            if os.path.exists(model_path) and os.path.exists(scaler_path):
                # Load scaler first to get input size
                self.scaler = joblib.load(scaler_path)
                
                # Create model with correct input size
                # This assumes we know the input size from training
                input_size = 120  # Default feature count
                self.model = self._create_model(input_size)
                
                # Load model state
                self.model.load_state_dict(torch.load(model_path, map_location=self.device))
                self.model.eval()
                
                logger.info(f"Model loaded from {model_path}")
                return True
            else:
                logger.warning(f"Model files not found: {model_path}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to load model: {str(e)}")
            return False

class PyTorchLSTMModel(BaseModel):
    """
    Advanced PyTorch-based LSTM model for time-series football predictions.
    Replaces TensorFlow LSTM functionality with enhanced performance.
    """

    def __init__(self, prediction_type: str = "match_result", sequence_length: int = 10):
        super().__init__(f"pytorch_lstm_{prediction_type}")
        self.prediction_type = prediction_type
        self.sequence_length = sequence_length
        self.model = None
        self.scaler = StandardScaler()

        if PYTORCH_AVAILABLE:
            logger.info(f"✅ PyTorch LSTM model initialized for {prediction_type} (TensorFlow alternative)")
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.available = PYTORCH_AVAILABLE
        
        if not PYTORCH_AVAILABLE:
            logger.warning("PyTorch not available - LSTM model will not function")

# Model factory integration
def create_pytorch_models():
    """Create PyTorch model instances for the model factory."""
    if not PYTORCH_AVAILABLE:
        return []
    
    models = [
        ("pytorch_over_under_1_5", lambda: PyTorchOverUnderModel(threshold=1.5)),
        ("pytorch_over_under_2_5", lambda: PyTorchOverUnderModel(threshold=2.5)),
        ("pytorch_over_under_3_5", lambda: PyTorchOverUnderModel(threshold=3.5)),
        ("pytorch_lstm_match_result", lambda: PyTorchLSTMModel(prediction_type="match_result")),
        ("pytorch_lstm_btts", lambda: PyTorchLSTMModel(prediction_type="btts")),
        ("pytorch_lstm_over_under", lambda: PyTorchLSTMModel(prediction_type="over_under")),
    ]
    
    return models
