"""
Prediction service for managing predictions.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.prediction import Prediction
from app.models.fixture import Fixture

logger = logging.getLogger(__name__)

class PredictionService:
    """Service for managing predictions."""

    def __init__(self, db: Session):
        """Initialize the service with a database session."""
        self.db = db

    def get_prediction_by_id(self, prediction_id: int) -> Optional[Prediction]:
        """Get a prediction by ID."""
        return self.db.query(Prediction).filter(Prediction.id == prediction_id).first()

    def get_predictions_by_fixture_id(self, fixture_id: int) -> List[Prediction]:
        """Get predictions for a fixture."""
        return self.db.query(Prediction).filter(Prediction.fixture_id == fixture_id).all()

    def get_predictions_by_date(self, date: datetime) -> List[Prediction]:
        """Get predictions for a specific date."""
        start_date = datetime(date.year, date.month, date.day, 0, 0, 0)
        end_date = start_date + timedelta(days=1)

        return self.db.query(Prediction).join(Fixture).filter(
            Fixture.date >= start_date,
            Fixture.date < end_date
        ).all()

    def get_predictions_by_category(self, category: str) -> List[Prediction]:
        """Get predictions by category (2_odds, 5_odds, 10_odds, rollover)."""
        return self.db.query(Prediction).filter(Prediction.prediction_type == category).all()

    def create_prediction(self, prediction_data: Dict[str, Any]) -> Prediction:
        """Create a new prediction."""
        # Filter out fields that might not exist in the Prediction model
        valid_fields = {
            "fixture_id", "match_result_pred", "home_win_pred", "draw_pred",
            "away_win_pred", "over_under_pred", "over_2_5_pred", "under_2_5_pred",
            "btts_pred", "btts_yes_pred", "btts_no_pred"
        }

        # Only include fields that are known to exist in the model
        filtered_data = {k: v for k, v in prediction_data.items() if k in valid_fields}

        # Create the prediction with filtered data
        prediction = Prediction(**filtered_data)
        self.db.add(prediction)
        self.db.commit()
        self.db.refresh(prediction)
        return prediction

    def create_or_update_prediction(self, prediction_data: Dict[str, Any]) -> Prediction:
        """Create or update a prediction."""
        fixture_id = prediction_data.get("fixture_id")
        prediction_type = prediction_data.get("prediction_type", "")

        try:
            # Check if prediction already exists
            existing_prediction = self.db.query(Prediction).filter(
                Prediction.fixture_id == fixture_id,
                Prediction.prediction_type == prediction_type
            ).first()
        except Exception as e:
            # If prediction_type column doesn't exist, try without it
            try:
                existing_prediction = self.db.query(Prediction).filter(
                    Prediction.fixture_id == fixture_id
                ).first()
            except Exception as e2:
                # If that also fails, assume no existing prediction
                existing_prediction = None

        if existing_prediction:
            # Update existing prediction
            for key, value in prediction_data.items():
                if hasattr(existing_prediction, key):
                    setattr(existing_prediction, key, value)
            self.db.commit()
            self.db.refresh(existing_prediction)
            return existing_prediction
        else:
            # Create new prediction
            return self.create_prediction(prediction_data)

    def create_or_update_predictions(self, predictions_data: List[Dict[str, Any]]) -> List[Prediction]:
        """Create or update multiple predictions."""
        predictions = []
        for prediction_data in predictions_data:
            prediction = self.create_or_update_prediction(prediction_data)
            predictions.append(prediction)
        return predictions

    def categorize_predictions(self, predictions: List[Prediction]) -> Dict[str, List[Prediction]]:
        """
        Categorize predictions into different odds categories.

        Categories:
        - 2_odds: Predictions with odds between 1.5 and 3.0
        - 5_odds: Predictions with odds between 3.0 and 7.0
        - 10_odds: Predictions with odds >= 7.0
        - rollover: Predictions with rollover_day set
        """
        categorized = {
            "2_odds": [],
            "5_odds": [],
            "10_odds": [],
            "rollover": []
        }

        # First, update prediction types if needed
        for prediction in predictions:
            # Make sure all predictions have a type and odds
            if not prediction.prediction_type or not prediction.odds:
                if prediction.btts_pred == 'YES' and prediction.btts_yes_pred >= 0.7:
                    prediction.prediction_type = 'btts'
                    prediction.odds = 1.8
                    prediction.confidence = prediction.btts_yes_pred
                elif prediction.over_under_pred == 'OVER' and prediction.over_2_5_pred >= 0.7:
                    prediction.prediction_type = 'over_2_5'
                    prediction.odds = 1.9
                    prediction.confidence = prediction.over_2_5_pred
                elif prediction.match_result_pred == 'HOME' and prediction.home_win_pred >= 0.7:
                    prediction.prediction_type = 'home_win'
                    prediction.odds = 2.0
                    prediction.confidence = prediction.home_win_pred
                elif prediction.match_result_pred == 'DRAW' and prediction.draw_pred >= 0.7:
                    prediction.prediction_type = 'draw'
                    prediction.odds = 3.5
                    prediction.confidence = prediction.draw_pred
                elif prediction.match_result_pred == 'AWAY' and prediction.away_win_pred >= 0.7:
                    prediction.prediction_type = 'away_win'
                    prediction.odds = 3.0
                    prediction.confidence = prediction.away_win_pred

            # Now categorize based on odds
            if prediction.rollover_day:
                categorized["rollover"].append(prediction)
            elif prediction.odds >= 7.0:
                categorized["10_odds"].append(prediction)
            elif prediction.odds >= 3.0:
                categorized["5_odds"].append(prediction)
            elif prediction.odds >= 1.5:
                categorized["2_odds"].append(prediction)

        # Save changes to database
        self.db.commit()

        return categorized

    def create_prediction_combinations(self, predictions: List[Prediction], target_odds: float) -> List[Dict[str, Any]]:
        """
        Create combinations of predictions to reach target odds.

        Args:
            predictions: List of predictions to combine
            target_odds: Target odds to reach

        Returns:
            List of combinations, each with predictions and combined odds
        """
        if not predictions:
            return []

        # Sort predictions by confidence (highest first)
        sorted_predictions = sorted(predictions, key=lambda p: p.confidence or 0, reverse=True)

        # Make sure we have unique fixtures (don't use multiple predictions from same fixture)
        unique_fixture_preds = []
        seen_fixtures = set()
        for pred in sorted_predictions:
            if pred.fixture_id not in seen_fixtures:
                unique_fixture_preds.append(pred)
                seen_fixtures.add(pred.fixture_id)

        # Use the unique predictions list
        sorted_predictions = unique_fixture_preds

        combinations = []

        # For 2 odds category, use single best prediction
        if abs(target_odds - 2.0) < 0.5:
            # Just use the best single prediction
            if sorted_predictions:
                pred = sorted_predictions[0]
                combo_id = str(uuid.uuid4())
                pred.combo_id = combo_id
                pred.combined_odds = pred.odds
                pred.combined_confidence = pred.confidence

                combinations.append({
                    "id": combo_id,
                    "predictions": [pred.to_dict()],
                    "combined_odds": pred.odds,
                    "combined_confidence": pred.confidence
                })

                # Add a few more single predictions if available
                for i in range(1, min(3, len(sorted_predictions))):
                    pred = sorted_predictions[i]
                    combo_id = str(uuid.uuid4())
                    pred.combo_id = combo_id
                    pred.combined_odds = pred.odds
                    pred.combined_confidence = pred.confidence

                    combinations.append({
                        "id": combo_id,
                        "predictions": [pred.to_dict()],
                        "combined_odds": pred.odds,
                        "combined_confidence": pred.confidence
                    })

        # For 5 odds category, use pairs of predictions
        elif abs(target_odds - 5.0) < 0.5:
            # Try pairs of predictions
            for i in range(len(sorted_predictions)):
                for j in range(i + 1, len(sorted_predictions)):
                    pred1 = sorted_predictions[i]
                    pred2 = sorted_predictions[j]
                    combined_odds = pred1.odds * pred2.odds

                    if 4.0 <= combined_odds <= 6.0:
                        combo_id = str(uuid.uuid4())
                        pred1.combo_id = combo_id
                        pred2.combo_id = combo_id

                        # Calculate combined confidence
                        combined_confidence = (pred1.confidence + pred2.confidence) / 2

                        pred1.combined_odds = combined_odds
                        pred2.combined_odds = combined_odds
                        pred1.combined_confidence = combined_confidence
                        pred2.combined_confidence = combined_confidence

                        combinations.append({
                            "id": combo_id,
                            "predictions": [pred1.to_dict(), pred2.to_dict()],
                            "combined_odds": combined_odds,
                            "combined_confidence": combined_confidence
                        })

        # For 10 odds category, use 3-4 predictions
        elif abs(target_odds - 10.0) < 1.0:
            # Try combinations of 3-4 predictions
            if len(sorted_predictions) >= 4:
                # Use top 4 predictions
                preds = sorted_predictions[:4]
                combined_odds = preds[0].odds * preds[1].odds * preds[2].odds * preds[3].odds
                combo_id = str(uuid.uuid4())

                for pred in preds:
                    pred.combo_id = combo_id
                    pred.combined_odds = combined_odds

                # Calculate combined confidence
                combined_confidence = sum(p.confidence for p in preds) / len(preds)

                for pred in preds:
                    pred.combined_confidence = combined_confidence

                combinations.append({
                    "id": combo_id,
                    "predictions": [p.to_dict() for p in preds],
                    "combined_odds": combined_odds,
                    "combined_confidence": combined_confidence
                })
            elif len(sorted_predictions) >= 3:
                # Use top 3 predictions
                preds = sorted_predictions[:3]
                combined_odds = preds[0].odds * preds[1].odds * preds[2].odds
                combo_id = str(uuid.uuid4())

                for pred in preds:
                    pred.combo_id = combo_id
                    pred.combined_odds = combined_odds

                # Calculate combined confidence
                combined_confidence = sum(p.confidence for p in preds) / len(preds)

                for pred in preds:
                    pred.combined_confidence = combined_confidence

                combinations.append({
                    "id": combo_id,
                    "predictions": [p.to_dict() for p in preds],
                    "combined_odds": combined_odds,
                    "combined_confidence": combined_confidence
                })

        # For rollover, create a 3-day rollover with one prediction per day
        elif target_odds == 3.0 and len(sorted_predictions) >= 3:
            # Use top 3 predictions for a 3-day rollover
            for i, day in enumerate(range(1, 4)):
                if i < len(sorted_predictions):
                    pred = sorted_predictions[i]
                    pred.rollover_day = day
                    combo_id = f"rollover_day_{day}"
                    pred.combo_id = combo_id

                    combinations.append({
                        "id": combo_id,
                        "day": day,
                        "predictions": [pred.to_dict()],
                        "combined_odds": pred.odds,
                        "combined_confidence": pred.confidence
                    })

        # If we still don't have combinations, try the original approach
        if not combinations:
            # Try combinations of 1-3 predictions
            for i in range(len(sorted_predictions)):
                # Single prediction
                pred1 = sorted_predictions[i]
                if abs(pred1.odds - target_odds) <= 0.5:
                    combo_id = str(uuid.uuid4())
                    pred1.combo_id = combo_id
                    pred1.combined_odds = pred1.odds
                    pred1.combined_confidence = pred1.confidence

                    combinations.append({
                        "id": combo_id,
                        "predictions": [pred1.to_dict()],
                        "combined_odds": pred1.odds,
                        "combined_confidence": pred1.confidence
                    })

                # Try pairs
                for j in range(i + 1, len(sorted_predictions)):
                    pred2 = sorted_predictions[j]
                    combined_odds = pred1.odds * pred2.odds

                    if abs(combined_odds - target_odds) <= 1.0:
                        combo_id = str(uuid.uuid4())
                        pred1.combo_id = combo_id
                        pred2.combo_id = combo_id

                        # Calculate combined confidence
                        combined_confidence = (pred1.confidence + pred2.confidence) / 2

                        pred1.combined_odds = combined_odds
                        pred2.combined_odds = combined_odds
                        pred1.combined_confidence = combined_confidence
                        pred2.combined_confidence = combined_confidence

                        combinations.append({
                            "id": combo_id,
                            "predictions": [pred1.to_dict(), pred2.to_dict()],
                            "combined_odds": combined_odds,
                            "combined_confidence": combined_confidence
                        })

                    # Try triplets
                    for k in range(j + 1, len(sorted_predictions)):
                        pred3 = sorted_predictions[k]
                        combined_odds = pred1.odds * pred2.odds * pred3.odds

                        if abs(combined_odds - target_odds) <= 1.5:
                            combo_id = str(uuid.uuid4())
                            pred1.combo_id = combo_id
                            pred2.combo_id = combo_id
                            pred3.combo_id = combo_id

                            # Calculate combined confidence
                            combined_confidence = (pred1.confidence + pred2.confidence + pred3.confidence) / 3

                            pred1.combined_odds = combined_odds
                            pred2.combined_odds = combined_odds
                            pred3.combined_odds = combined_odds
                            pred1.combined_confidence = combined_confidence
                            pred2.combined_confidence = combined_confidence
                            pred3.combined_confidence = combined_confidence

                            combinations.append({
                                "id": combo_id,
                                "predictions": [pred1.to_dict(), pred2.to_dict(), pred3.to_dict()],
                                "combined_odds": combined_odds,
                                "combined_confidence": combined_confidence
                            })

        # Save changes to database
        self.db.commit()

        # Sort combinations by combined confidence (highest first)
        return sorted(combinations, key=lambda c: c["combined_confidence"], reverse=True)
