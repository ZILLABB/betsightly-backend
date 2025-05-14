"""
Prediction Service

This module provides a service for generating and managing predictions.
It implements efficient database storage and caching to minimize API calls.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd
import numpy as np

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from app.database.models.fixture import Fixture
from app.database.models.prediction import Prediction
from app.services.api_football_client import api_football_client
from app.ml.football_prediction_model import football_prediction_model
from app.config import settings

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PredictionService:
    """
    Service for generating and managing predictions.
    
    Features:
    - Generates predictions for today's fixtures
    - Categorizes predictions by odds value
    - Provides best picks for different odds categories
    - Generates rollover predictions
    - Implements database caching to minimize API calls and ML processing
    """
    
    def __init__(self):
        """Initialize the prediction service."""
        self.cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), settings.CACHE_DIR)
        os.makedirs(self.cache_dir, exist_ok=True)
        self.last_update = None
        self.update_interval = timedelta(hours=6)  # Longer interval to reduce API calls
    
    async def get_todays_fixtures(self, db: Session, force_update: bool = False) -> List[Fixture]:
        """
        Get today's fixtures from the database or API.
        
        Args:
            db: Database session
            force_update: Whether to force an update from the API
        
        Returns:
            List of Fixture objects
        """
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Check if we need to update
        if not force_update and self.last_update and datetime.now() - self.last_update < self.update_interval:
            # Get fixtures from database
            fixtures = db.query(Fixture).filter(Fixture.match_date.like(f"{today}%")).all()
            
            if fixtures:
                logger.info(f"Using database fixtures for {today}")
                return fixtures
        
        # Fetch fixtures from API and save to database
        logger.info(f"Fetching fixtures for {today} from API")
        api_fixtures = await api_football_client.get_fixtures(db, date=today, force_update=force_update)
        
        if not api_fixtures:
            logger.warning(f"No fixtures found for {today}")
            return []
        
        # Save fixtures to database
        fixtures = await api_football_client.save_fixtures_to_db(api_fixtures, db)
        
        # Update last update time
        self.last_update = datetime.now()
        
        return fixtures
    
    async def generate_predictions(self, db: Session, force_update: bool = False) -> Dict[str, List[Dict[str, Any]]]:
        """
        Generate predictions for today's fixtures.
        Prioritizes database lookup before generating new predictions.
        
        Args:
            db: Database session
            force_update: Whether to force an update
        
        Returns:
            Dictionary with predictions grouped by category
        """
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Check if we need to update
        if not force_update:
            # Try to get predictions from database first
            db_predictions = self._get_predictions_from_db(db, today)
            
            if db_predictions:
                logger.info(f"Using database predictions for {today}")
                return db_predictions
        
        # Check file cache
        cache_file = os.path.join(self.cache_dir, f"predictions_{today}.json")
        
        if not force_update and os.path.exists(cache_file):
            try:
                with open(cache_file, "r") as f:
                    cached_predictions = json.load(f)
                
                logger.info(f"Using cached predictions for {today}")
                return cached_predictions
            except Exception as e:
                logger.error(f"Error reading cached predictions: {str(e)}")
        
        # Get today's fixtures
        fixtures = await self.get_todays_fixtures(db, force_update)
        
        if not fixtures:
            logger.warning(f"No fixtures found for {today}")
            return {
                "2_odds": [],
                "5_odds": [],
                "10_odds": [],
                "rollover": []
            }
        
        # Generate predictions for each fixture
        all_predictions = []
        
        for fixture in fixtures:
            # Skip fixtures that have already started or finished
            if fixture.status not in ["NS", "TBD", "SCHEDULED"]:
                continue
            
            # Check if we already have predictions for this fixture
            existing_predictions = db.query(Prediction).filter(Prediction.fixture_id == fixture.id).all()
            
            if existing_predictions and not force_update:
                all_predictions.extend(existing_predictions)
                continue
            
            # Generate prediction
            prediction_result = football_prediction_model.predict(fixture.additional_data)
            
            if prediction_result["status"] != "success":
                logger.warning(f"Error generating prediction for fixture {fixture.id}: {prediction_result.get('message')}")
                continue
            
            # Create prediction objects
            for pred_data in prediction_result["predictions"]:
                prediction = Prediction(
                    fixture_id=fixture.id,
                    prediction_type=pred_data["prediction_type"],
                    prediction=pred_data["prediction"],
                    odds=pred_data["odds"],
                    confidence=pred_data["confidence"],
                    explanation=pred_data["explanation"],
                    source="ml_model",
                    status="pending"
                )
                
                db.add(prediction)
                all_predictions.append(prediction)
        
        # Commit changes
        db.commit()
        
        # Categorize predictions
        categorized = self._categorize_predictions(all_predictions)
        
        # Generate rollover predictions
        rollover = self._generate_rollover_predictions(all_predictions)
        categorized["rollover"] = rollover
        
        # Cache predictions
        try:
            with open(cache_file, "w") as f:
                json.dump(categorized, f, default=self._json_serializer)
            
            logger.info(f"Cached predictions for {today}")
        except Exception as e:
            logger.error(f"Error caching predictions: {str(e)}")
        
        return categorized
    
    def _get_predictions_from_db(self, db: Session, date: str) -> Optional[Dict[str, List[Dict[str, Any]]]]:
        """
        Get predictions from the database.
        
        Args:
            db: Database session
            date: Date in format YYYY-MM-DD
        
        Returns:
            Dictionary with predictions grouped by category or None if not found
        """
        try:
            # Get fixtures for the date
            fixtures = db.query(Fixture).filter(Fixture.match_date.like(f"{date}%")).all()
            
            if not fixtures:
                return None
            
            # Get predictions for these fixtures
            fixture_ids = [fixture.id for fixture in fixtures]
            predictions = db.query(Prediction).filter(Prediction.fixture_id.in_(fixture_ids)).all()
            
            if not predictions:
                return None
            
            # Categorize predictions
            categorized = self._categorize_predictions(predictions)
            
            # Generate rollover predictions
            rollover = self._generate_rollover_predictions(predictions)
            categorized["rollover"] = rollover
            
            return categorized
        
        except Exception as e:
            logger.error(f"Error getting predictions from database: {str(e)}")
            return None
    
    def _categorize_predictions(self, predictions: List[Prediction]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Categorize predictions by odds value.
        
        Args:
            predictions: List of Prediction objects
        
        Returns:
            Dictionary with predictions grouped by category
        """
        # Convert predictions to dictionaries
        pred_dicts = [self._prediction_to_dict(p) for p in predictions]
        
        # Filter and sort predictions for each category
        categories = {}
        
        # 2 odds category
        two_odds_config = settings.ODDS_CATEGORIES["2_odds"]
        two_odds = [p for p in pred_dicts if 
                   two_odds_config["min_odds"] <= p["odds"] <= two_odds_config["max_odds"] and
                   p["confidence"] >= two_odds_config["min_confidence"]]
        two_odds.sort(key=lambda p: p["confidence"], reverse=True)
        categories["2_odds"] = two_odds[:two_odds_config["limit"]]
        
        # 5 odds category
        five_odds_config = settings.ODDS_CATEGORIES["5_odds"]
        five_odds = [p for p in pred_dicts if 
                    five_odds_config["min_odds"] <= p["odds"] <= five_odds_config["max_odds"] and
                    p["confidence"] >= five_odds_config["min_confidence"]]
        # Sort by expected value (confidence * odds)
        five_odds.sort(key=lambda p: p["confidence"] * p["odds"], reverse=True)
        categories["5_odds"] = five_odds[:five_odds_config["limit"]]
        
        # 10 odds category
        ten_odds_config = settings.ODDS_CATEGORIES["10_odds"]
        ten_odds = [p for p in pred_dicts if 
                   ten_odds_config["min_odds"] <= p["odds"] <= ten_odds_config["max_odds"] and
                   p["confidence"] >= ten_odds_config["min_confidence"]]
        # Sort by confidence
        ten_odds.sort(key=lambda p: p["confidence"], reverse=True)
        categories["10_odds"] = ten_odds[:ten_odds_config["limit"]]
        
        return categories
    
    def _generate_rollover_predictions(self, predictions: List[Prediction]) -> List[Dict[str, Any]]:
        """
        Generate rollover predictions.
        
        Args:
            predictions: List of Prediction objects
        
        Returns:
            List of rollover predictions
        """
        rollover_config = settings.ODDS_CATEGORIES["rollover"]
        
        # Convert predictions to dictionaries
        pred_dicts = [self._prediction_to_dict(p) for p in predictions]
        
        # Filter predictions for rollover
        rollover_candidates = [p for p in pred_dicts if 
                              rollover_config["min_odds"] <= p["odds"] <= rollover_config["max_odds"] and
                              p["confidence"] >= rollover_config["min_confidence"]]
        
        # Sort by confidence
        rollover_candidates.sort(key=lambda p: p["confidence"], reverse=True)
        
        # Get top candidates
        top_candidates = rollover_candidates[:10]
        
        if len(top_candidates) < 2:
            return []
        
        # Find the best combination of 2-3 predictions with combined odds close to target
        best_combo = None
        best_diff = float('inf')
        target_odds = rollover_config["target_combined_odds"]
        
        # Try combinations of 2 predictions
        for i in range(len(top_candidates)):
            for j in range(i+1, len(top_candidates)):
                # Skip if same fixture
                if top_candidates[i]["fixture_id"] == top_candidates[j]["fixture_id"]:
                    continue
                
                combined_odds = top_candidates[i]["odds"] * top_candidates[j]["odds"]
                diff = abs(combined_odds - target_odds)
                
                if diff < best_diff:
                    best_diff = diff
                    best_combo = [top_candidates[i], top_candidates[j]]
        
        # Try combinations of 3 predictions
        for i in range(len(top_candidates)):
            for j in range(i+1, len(top_candidates)):
                for k in range(j+1, len(top_candidates)):
                    # Skip if same fixture
                    if (top_candidates[i]["fixture_id"] == top_candidates[j]["fixture_id"] or
                        top_candidates[i]["fixture_id"] == top_candidates[k]["fixture_id"] or
                        top_candidates[j]["fixture_id"] == top_candidates[k]["fixture_id"]):
                        continue
                    
                    combined_odds = top_candidates[i]["odds"] * top_candidates[j]["odds"] * top_candidates[k]["odds"]
                    diff = abs(combined_odds - target_odds)
                    
                    if diff < best_diff:
                        best_diff = diff
                        best_combo = [top_candidates[i], top_candidates[j], top_candidates[k]]
        
        if best_combo:
            # Calculate combined odds
            combined_odds = 1
            for p in best_combo:
                combined_odds *= p["odds"]
            
            # Add combined odds to each prediction
            for p in best_combo:
                p["combined_odds"] = round(combined_odds, 2)
            
            return best_combo
        
        return []
    
    def _prediction_to_dict(self, prediction: Prediction) -> Dict[str, Any]:
        """
        Convert a Prediction object to a dictionary.
        
        Args:
            prediction: Prediction object
        
        Returns:
            Dictionary representation of the prediction
        """
        return {
            "id": prediction.id,
            "fixture_id": prediction.fixture_id,
            "prediction_type": prediction.prediction_type,
            "prediction": prediction.prediction,
            "odds": prediction.odds,
            "confidence": prediction.confidence,
            "explanation": prediction.explanation,
            "category": prediction.category,
            "source": prediction.source,
            "status": prediction.status,
            "created_at": prediction.created_at.isoformat() if prediction.created_at else None,
            "updated_at": prediction.updated_at.isoformat() if prediction.updated_at else None,
            "fixture": prediction.fixture.to_dict() if prediction.fixture else None
        }
    
    def _json_serializer(self, obj):
        """JSON serializer for objects not serializable by default json code."""
        if isinstance(obj, (datetime, pd.Timestamp)):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")

# Create a singleton instance
prediction_service = PredictionService()
