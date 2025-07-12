"""
Intelligent Ensemble System

Advanced ensemble methods for optimal model combination and weighting.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Any, Tuple
import logging
from sklearn.metrics import accuracy_score, log_loss
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import VotingClassifier
import json
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class IntelligentEnsemble:
    """
    Advanced ensemble system that intelligently weights models based on:
    - Historical accuracy
    - Prediction confidence
    - Model agreement
    - Context-specific performance
    """
    
    def __init__(self):
        self.model_weights = {}
        self.model_performance_history = {}
        self.context_weights = {}
        self.meta_model = None
        
    def calculate_dynamic_weights(self, 
                                model_predictions: Dict[str, Any], 
                                context: Dict[str, Any]) -> Dict[str, float]:
        """
        Calculate dynamic weights for each model based on context and performance.
        """
        weights = {}
        
        # Base weights from historical performance
        for model_name in model_predictions.keys():
            base_weight = self._get_base_weight(model_name)
            context_modifier = self._get_context_modifier(model_name, context)
            confidence_modifier = self._get_confidence_modifier(model_predictions[model_name])
            
            # Combine modifiers
            final_weight = base_weight * context_modifier * confidence_modifier
            weights[model_name] = final_weight
        
        # Normalize weights
        total_weight = sum(weights.values())
        if total_weight > 0:
            weights = {k: v / total_weight for k, v in weights.items()}
        
        return weights
    
    def _get_base_weight(self, model_name: str) -> float:
        """Get base weight from historical performance."""
        if model_name not in self.model_weights:
            # Default weights based on model type
            if "xgboost" in model_name:
                return 1.0  # XGBoost models get highest base weight
            elif "lightgbm" in model_name:
                return 0.9  # LightGBM gets high weight
            elif "enhanced" in model_name:
                return 0.8  # Enhanced models get good weight
            elif "advanced" in model_name:
                return 0.7  # Advanced models get decent weight
            elif "quick" in model_name:
                return 0.6  # Quick models get lower weight
            elif "ml_algo" in model_name:
                return 0.75  # ML algorithm models get good weight
            else:
                return 0.5  # Default weight
        
        return self.model_weights[model_name]
    
    def _get_context_modifier(self, model_name: str, context: Dict[str, Any]) -> float:
        """Get context-specific weight modifier."""
        modifier = 1.0
        
        # League-specific modifiers
        league = context.get('league', '').lower()
        if 'premier league' in league and 'xgboost' in model_name:
            modifier *= 1.1  # XGBoost performs better in Premier League
        elif 'championship' in league and 'lightgbm' in model_name:
            modifier *= 1.05  # LightGBM good for Championship
        
        # Match importance modifiers
        importance = context.get('match_importance', 'normal')
        if importance == 'high' and 'enhanced' in model_name:
            modifier *= 1.1  # Enhanced models better for important matches
        
        # Time-based modifiers
        match_date = context.get('match_date')
        if match_date:
            # Models might perform differently at different times of season
            pass
        
        return modifier
    
    def _get_confidence_modifier(self, prediction: Dict[str, Any]) -> float:
        """Get confidence-based weight modifier."""
        confidence = prediction.get('confidence', 70.0)
        
        # Higher confidence predictions get higher weight
        if confidence >= 90:
            return 1.2
        elif confidence >= 80:
            return 1.1
        elif confidence >= 70:
            return 1.0
        elif confidence >= 60:
            return 0.9
        else:
            return 0.8
    
    def weighted_ensemble_prediction(self, 
                                   model_predictions: Dict[str, Any], 
                                   context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create weighted ensemble prediction.
        """
        weights = self.calculate_dynamic_weights(model_predictions, context)
        
        # Aggregate predictions by type
        prediction_types = ['match_result', 'over_under', 'btts', 'clean_sheet', 'win_to_nil']
        ensemble_results = {}
        
        for pred_type in prediction_types:
            type_predictions = []
            type_weights = []
            
            for model_name, prediction in model_predictions.items():
                if pred_type in prediction.get('prediction', '').lower():
                    type_predictions.append(prediction)
                    type_weights.append(weights.get(model_name, 0.5))
            
            if type_predictions:
                ensemble_results[pred_type] = self._aggregate_predictions(
                    type_predictions, type_weights
                )
        
        return ensemble_results
    
    def _aggregate_predictions(self, predictions: List[Dict], weights: List[float]) -> Dict[str, Any]:
        """Aggregate predictions using weights."""
        if not predictions:
            return {}
        
        # Weighted average of confidences
        weighted_confidence = sum(
            pred.get('confidence', 70) * weight 
            for pred, weight in zip(predictions, weights)
        ) / sum(weights)
        
        # Most common prediction (weighted voting)
        prediction_votes = {}
        for pred, weight in zip(predictions, weights):
            pred_value = pred.get('prediction', '')
            prediction_votes[pred_value] = prediction_votes.get(pred_value, 0) + weight
        
        # Get prediction with highest weighted vote
        best_prediction = max(prediction_votes.items(), key=lambda x: x[1])[0]
        
        return {
            'prediction': best_prediction,
            'confidence': round(weighted_confidence, 1),
            'model_agreement': len(set(p.get('prediction', '') for p in predictions)),
            'total_models': len(predictions)
        }
    
    def update_model_performance(self, 
                               model_name: str, 
                               prediction: Any, 
                               actual_result: Any, 
                               context: Dict[str, Any]):
        """Update model performance tracking."""
        if model_name not in self.model_performance_history:
            self.model_performance_history[model_name] = []
        
        # Record performance
        performance_record = {
            'timestamp': datetime.now().isoformat(),
            'prediction': prediction,
            'actual': actual_result,
            'correct': prediction == actual_result,
            'context': context
        }
        
        self.model_performance_history[model_name].append(performance_record)
        
        # Update weights based on recent performance
        self._update_model_weights(model_name)
    
    def _update_model_weights(self, model_name: str):
        """Update model weights based on recent performance."""
        if model_name not in self.model_performance_history:
            return
        
        recent_records = self.model_performance_history[model_name][-100:]  # Last 100 predictions
        
        if len(recent_records) >= 10:  # Need minimum data
            accuracy = sum(1 for r in recent_records if r['correct']) / len(recent_records)
            
            # Update weight based on accuracy
            if accuracy >= 0.85:
                self.model_weights[model_name] = 1.0
            elif accuracy >= 0.80:
                self.model_weights[model_name] = 0.9
            elif accuracy >= 0.75:
                self.model_weights[model_name] = 0.8
            elif accuracy >= 0.70:
                self.model_weights[model_name] = 0.7
            else:
                self.model_weights[model_name] = 0.6
    
    def get_model_rankings(self) -> List[Tuple[str, float]]:
        """Get current model rankings by performance."""
        rankings = []
        
        for model_name, history in self.model_performance_history.items():
            if len(history) >= 10:
                recent_accuracy = sum(1 for r in history[-50:] if r['correct']) / len(history[-50:])
                rankings.append((model_name, recent_accuracy))
        
        return sorted(rankings, key=lambda x: x[1], reverse=True)
    
    def get_ensemble_stats(self) -> Dict[str, Any]:
        """Get ensemble performance statistics."""
        total_models = len(self.model_weights)
        active_models = sum(1 for w in self.model_weights.values() if w > 0.5)
        
        rankings = self.get_model_rankings()
        top_performers = rankings[:5] if rankings else []
        
        return {
            'total_models': total_models,
            'active_models': active_models,
            'top_performers': top_performers,
            'average_weight': np.mean(list(self.model_weights.values())) if self.model_weights else 0,
            'weight_distribution': dict(self.model_weights)
        }

# Global ensemble instance
intelligent_ensemble = IntelligentEnsemble()
