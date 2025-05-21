"""
Prediction Categorizer Module

This module provides functionality for categorizing predictions into different odds groups
and generating optimal combinations for each category.
"""

import logging
from typing import Dict, List, Any, Set, Tuple
from datetime import datetime, timedelta
import itertools

from app.utils.config import settings

# Set up logging
logger = logging.getLogger(__name__)

class PredictionCategorizer:
    """
    Service for categorizing predictions into different odds groups.
    
    Features:
    - Categorizes predictions into 2 odds, 5 odds, 10 odds groups
    - Generates 10-day rollover predictions with 3 odds per day
    - Ensures all predictions are high confidence
    - Avoids using the same games across different categories
    """
    
    def __init__(self):
        """Initialize the prediction categorizer."""
        self.odds_categories = settings.ODDS_CATEGORIES
        
    def categorize_predictions(self, predictions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Categorize predictions into different odds groups.
        
        Args:
            predictions: List of predictions with fixture info and confidence scores
            
        Returns:
            Dictionary with categorized predictions
        """
        # Filter high-confidence predictions
        high_confidence_predictions = self._filter_high_confidence_predictions(predictions)
        
        if not high_confidence_predictions:
            logger.warning("No high-confidence predictions found")
            return {
                "2_odds": [],
                "5_odds": [],
                "10_odds": [],
                "rollover": []
            }
        
        # Track used fixtures to avoid duplicates across categories
        used_fixtures: Set[int] = set()
        
        # Generate combinations for each category
        two_odds_combinations = self._generate_combinations_for_category(
            high_confidence_predictions, 
            "2_odds", 
            used_fixtures
        )
        
        five_odds_combinations = self._generate_combinations_for_category(
            high_confidence_predictions, 
            "5_odds", 
            used_fixtures
        )
        
        ten_odds_combinations = self._generate_combinations_for_category(
            high_confidence_predictions, 
            "10_odds", 
            used_fixtures
        )
        
        # Generate rollover predictions for 10 days
        rollover_combinations = self._generate_rollover_combinations(
            high_confidence_predictions,
            used_fixtures
        )
        
        return {
            "2_odds": two_odds_combinations,
            "5_odds": five_odds_combinations,
            "10_odds": ten_odds_combinations,
            "rollover": rollover_combinations
        }
    
    def _filter_high_confidence_predictions(self, predictions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter predictions to only include high-confidence ones.
        
        Args:
            predictions: List of predictions
            
        Returns:
            List of high-confidence predictions
        """
        # Use the minimum confidence threshold from all categories
        min_confidence = min(
            self.odds_categories["2_odds"]["min_confidence"],
            self.odds_categories["5_odds"]["min_confidence"],
            self.odds_categories["10_odds"]["min_confidence"],
            self.odds_categories["rollover"]["min_confidence"]
        )
        
        high_confidence_predictions = []
        
        for prediction in predictions:
            confidence = prediction.get("prediction", {}).get("confidence", 0)
            if confidence >= min_confidence:
                high_confidence_predictions.append(prediction)
        
        return high_confidence_predictions
    
    def _generate_combinations_for_category(
        self, 
        predictions: List[Dict[str, Any]], 
        category: str,
        used_fixtures: Set[int]
    ) -> List[Dict[str, Any]]:
        """
        Generate optimal combinations for a specific odds category.
        
        Args:
            predictions: List of predictions
            category: Category name (2_odds, 5_odds, 10_odds)
            used_fixtures: Set of fixture IDs that have already been used
            
        Returns:
            List of optimal combinations for the category
        """
        # Get category settings
        category_settings = self.odds_categories[category]
        target_odds = category_settings["target_combined_odds"]
        min_confidence = category_settings["min_confidence"]
        limit = category_settings["limit"]
        
        # Filter predictions by confidence and exclude already used fixtures
        filtered_predictions = []
        for prediction in predictions:
            fixture_id = prediction.get("fixture", {}).get("fixture_id")
            confidence = prediction.get("prediction", {}).get("confidence", 0)
            
            if confidence >= min_confidence and fixture_id not in used_fixtures:
                filtered_predictions.append(prediction)
        
        # Sort by confidence (highest first)
        sorted_predictions = sorted(
            filtered_predictions,
            key=lambda x: x.get("prediction", {}).get("confidence", 0),
            reverse=True
        )
        
        # Find optimal combinations
        combinations = []
        
        # Try combinations of 2-4 predictions
        for size in range(2, 5):
            if len(sorted_predictions) < size:
                continue
                
            for combo in itertools.combinations(sorted_predictions, size):
                # Calculate combined odds and confidence
                combined_odds, combined_confidence = self._calculate_combined_metrics(combo)
                
                # Check if combined odds are close to target
                if combined_odds >= target_odds * 0.8 and combined_odds <= target_odds * 1.2:
                    combinations.append({
                        "predictions": list(combo),
                        "combined_odds": combined_odds,
                        "combined_confidence": combined_confidence
                    })
        
        # Sort by combined confidence (highest first)
        combinations = sorted(
            combinations,
            key=lambda x: x.get("combined_confidence", 0),
            reverse=True
        )
        
        # Apply limit
        combinations = combinations[:limit]
        
        # Add used fixtures to the set
        for combo in combinations:
            for prediction in combo.get("predictions", []):
                fixture_id = prediction.get("fixture", {}).get("fixture_id")
                if fixture_id:
                    used_fixtures.add(fixture_id)
        
        return combinations
    
    def _generate_rollover_combinations(
        self, 
        predictions: List[Dict[str, Any]],
        used_fixtures: Set[int]
    ) -> List[Dict[str, Any]]:
        """
        Generate rollover combinations for 10 days.
        
        Args:
            predictions: List of predictions
            used_fixtures: Set of fixture IDs that have already been used
            
        Returns:
            List of rollover combinations for 10 days
        """
        # Get rollover settings
        rollover_settings = self.odds_categories["rollover"]
        target_odds = rollover_settings["target_combined_odds"]
        min_confidence = rollover_settings["min_confidence"]
        days = rollover_settings["days"]
        
        # Filter predictions by confidence and exclude already used fixtures
        filtered_predictions = []
        for prediction in predictions:
            fixture_id = prediction.get("fixture", {}).get("fixture_id")
            confidence = prediction.get("prediction", {}).get("confidence", 0)
            
            if confidence >= min_confidence and fixture_id not in used_fixtures:
                filtered_predictions.append(prediction)
        
        # Sort by confidence (highest first)
        sorted_predictions = sorted(
            filtered_predictions,
            key=lambda x: x.get("prediction", {}).get("confidence", 0),
            reverse=True
        )
        
        # Generate combinations for each day
        daily_combinations = []
        
        # Simulate 10 days
        for day in range(days):
            # Find optimal combinations for this day
            day_combinations = []
            
            # Try combinations of 2-3 predictions
            for size in range(2, 4):
                if len(sorted_predictions) < size:
                    continue
                    
                for combo in itertools.combinations(sorted_predictions, size):
                    # Calculate combined odds and confidence
                    combined_odds, combined_confidence = self._calculate_combined_metrics(combo)
                    
                    # Check if combined odds are close to target
                    if combined_odds >= target_odds * 0.8 and combined_odds <= target_odds * 1.2:
                        day_combinations.append({
                            "predictions": list(combo),
                            "combined_odds": combined_odds,
                            "combined_confidence": combined_confidence,
                            "day": day + 1
                        })
            
            # Sort by combined confidence (highest first)
            day_combinations = sorted(
                day_combinations,
                key=lambda x: x.get("combined_confidence", 0),
                reverse=True
            )
            
            # Take the best combination for this day
            if day_combinations:
                best_combo = day_combinations[0]
                daily_combinations.append(best_combo)
                
                # Add used fixtures to the set
                for prediction in best_combo.get("predictions", []):
                    fixture_id = prediction.get("fixture", {}).get("fixture_id")
                    if fixture_id:
                        used_fixtures.add(fixture_id)
                
                # Remove used predictions from the pool
                for prediction in best_combo.get("predictions", []):
                    if prediction in sorted_predictions:
                        sorted_predictions.remove(prediction)
        
        return daily_combinations
    
    def _calculate_combined_metrics(self, predictions: Tuple[Dict[str, Any], ...]) -> Tuple[float, float]:
        """
        Calculate combined odds and confidence for a set of predictions.
        
        Args:
            predictions: Tuple of predictions
            
        Returns:
            Tuple of (combined_odds, combined_confidence)
        """
        combined_odds = 1.0
        combined_confidence_factor = 1.0
        
        for prediction in predictions:
            odds = prediction.get("prediction", {}).get("odds", 1.0)
            confidence = prediction.get("prediction", {}).get("confidence", 0) / 100
            
            combined_odds *= odds
            combined_confidence_factor *= confidence
        
        combined_confidence = combined_confidence_factor * 100
        
        return combined_odds, combined_confidence

# Create a singleton instance
prediction_categorizer = PredictionCategorizer()
