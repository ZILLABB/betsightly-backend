"""
ML Prediction Pipeline

This script processes real fixtures through the machine learning models
and generates categorized predictions (2 odds, 5 odds, 10 odds, rollover).
"""

import os
import sys
import json
import logging
import uuid
import itertools
from datetime import datetime
import pandas as pd
import numpy as np
import joblib
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Create a SQLite database for testing
DATABASE_URL = "sqlite:///real_predictions.db"
engine = create_engine(DATABASE_URL)
Base = declarative_base()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Define database models (same as in real_fixtures_prediction.py)
class Fixture(Base):
    __tablename__ = "fixtures"

    id = Column(Integer, primary_key=True)
    fixture_id = Column(Integer, unique=True, index=True)
    date = Column(DateTime)
    league_id = Column(Integer)
    league_name = Column(String(100))
    home_team_id = Column(Integer)
    home_team = Column(String(100))
    away_team_id = Column(Integer)
    away_team = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    predictions = relationship("Prediction", back_populates="fixture")

    def to_dict(self):
        return {
            "id": self.id,
            "fixture_id": self.fixture_id,
            "date": self.date.isoformat() if self.date else None,
            "league_id": self.league_id,
            "league_name": self.league_name,
            "home_team_id": self.home_team_id,
            "home_team": self.home_team,
            "away_team_id": self.away_team_id,
            "away_team": self.away_team
        }

# Association table for many-to-many relationship between predictions and combinations
prediction_combination_items = Table(
    "prediction_combination_items",
    Base.metadata,
    Column("id", Integer, primary_key=True),
    Column("combination_id", String(50), ForeignKey("prediction_combinations.id")),
    Column("prediction_id", Integer, ForeignKey("predictions.id"))
)

class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True)
    fixture_id = Column(Integer, ForeignKey("fixtures.fixture_id"))
    match_result_pred = Column(String(10))
    home_win_pred = Column(Float)
    draw_pred = Column(Float)
    away_win_pred = Column(Float)
    over_under_pred = Column(String(10))
    over_2_5_pred = Column(Float)
    under_2_5_pred = Column(Float)
    btts_pred = Column(String(10))
    btts_yes_pred = Column(Float)
    btts_no_pred = Column(Float)
    prediction_type = Column(String(20))
    odds = Column(Float)
    confidence = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    fixture = relationship("Fixture", back_populates="predictions")
    combinations = relationship("PredictionCombination", secondary=prediction_combination_items, back_populates="predictions")

    def to_dict(self):
        return {
            "id": self.id,
            "fixture_id": self.fixture_id,
            "match_result_pred": self.match_result_pred,
            "home_win_pred": self.home_win_pred,
            "draw_pred": self.draw_pred,
            "away_win_pred": self.away_win_pred,
            "over_under_pred": self.over_under_pred,
            "over_2_5_pred": self.over_2_5_pred,
            "under_2_5_pred": self.under_2_5_pred,
            "btts_pred": self.btts_pred,
            "btts_yes_pred": self.btts_yes_pred,
            "btts_no_pred": self.btts_no_pred,
            "prediction_type": self.prediction_type,
            "odds": self.odds,
            "confidence": self.confidence
        }

class PredictionCombination(Base):
    __tablename__ = "prediction_combinations"

    id = Column(String(50), primary_key=True)
    category = Column(String(20), index=True)
    combined_odds = Column(Float, default=0)
    combined_confidence = Column(Float, default=0)
    rollover_day = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    predictions = relationship("Prediction", secondary=prediction_combination_items, back_populates="combinations")

    def to_dict(self):
        return {
            "id": self.id,
            "category": self.category,
            "combined_odds": self.combined_odds,
            "combined_confidence": self.combined_confidence,
            "rollover_day": self.rollover_day,
            "predictions": [p.to_dict() for p in self.predictions]
        }

# Define the real fixtures provided by the user
REAL_FIXTURES = [
    {
        "fixture_id": 1001,
        "date": "2023-05-22T10:00:00",
        "league_name": "International - Club Friendlies",
        "home_team": "Blumenthaler SV",
        "away_team": "Werder Bremen",
        "home_form": 1.70,
        "away_form": 1.80,
        "home_odds": 41.00,
        "draw_odds": 19.50,
        "away_odds": 1.02
    },
    {
        "fixture_id": 1002,
        "date": "2023-05-22T12:30:00",
        "league_name": "Germany - Germany Play offs",
        "home_team": "Heidenheim",
        "away_team": "Elversberg",
        "home_form": 1.40,
        "away_form": 1.90,
        "home_odds": 2.25,
        "draw_odds": 3.55,
        "away_odds": 3.00
    },
    {
        "fixture_id": 1003,
        "date": "2023-05-22T12:00:00",
        "league_name": "Germany - State Leagues Weser Ems",
        "home_team": "Bad Bentheim",
        "away_team": "Germania Leer",
        "home_form": 0.48,
        "away_form": 0.15,
        "home_odds": None,
        "draw_odds": None,
        "away_odds": None
    },
    {
        "fixture_id": 1004,
        "date": "2023-05-22T13:00:00",
        "league_name": "Scotland - Scotland Play-offs",
        "home_team": "Livingston",
        "away_team": "Ross County",
        "home_form": 2.40,
        "away_form": 0.50,
        "home_odds": 2.19,
        "draw_odds": 3.30,
        "away_odds": 3.40
    },
    {
        "fixture_id": 1005,
        "date": "2023-05-22T12:30:00",
        "league_name": "Scotland - Feeder Leagues",
        "home_team": "Maud",
        "away_team": "Culter",
        "home_form": 1.71,
        "away_form": 2.54,
        "home_odds": None,
        "draw_odds": None,
        "away_odds": None
    }
]

class MLPredictionService:
    """Service for generating predictions using ML models."""

    def __init__(self, db):
        """Initialize the ML prediction service."""
        self.db = db

        # Load ML models
        self.models_dir = os.path.join(os.getcwd(), "models")
        self.load_ml_models()

    def load_ml_models(self):
        """Load the ML models."""
        try:
            # Try to load models from different directories
            model_dirs = ["models/xgboost", "models/enhanced", "models/advanced"]

            self.match_result_model = None
            self.over_under_model = None
            self.btts_model = None

            for model_dir in model_dirs:
                # Check if directory exists
                if os.path.exists(model_dir):
                    # Try to load match result model
                    match_result_path = os.path.join(model_dir, "match_result_model.joblib")
                    if os.path.exists(match_result_path):
                        self.match_result_model = joblib.load(match_result_path)
                        logger.info(f"Loaded match result model from {match_result_path}")

                    # Try to load over/under model
                    over_under_path = os.path.join(model_dir, "over_under_model.joblib")
                    if os.path.exists(over_under_path):
                        self.over_under_model = joblib.load(over_under_path)
                        logger.info(f"Loaded over/under model from {over_under_path}")

                    # Try to load BTTS model
                    btts_path = os.path.join(model_dir, "btts_model.joblib")
                    if os.path.exists(btts_path):
                        self.btts_model = joblib.load(btts_path)
                        logger.info(f"Loaded BTTS model from {btts_path}")

                    # If all models are loaded, break
                    if all([self.match_result_model, self.over_under_model, self.btts_model]):
                        logger.info("Successfully loaded all ML models")
                        break

            # If models couldn't be loaded, use fallback logic
            if not all([self.match_result_model, self.over_under_model, self.btts_model]):
                logger.warning("Could not load all ML models. Using fallback prediction logic.")

        except Exception as e:
            logger.error(f"Error loading ML models: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            logger.warning("Using fallback prediction logic.")

    def process_fixtures(self, fixtures):
        """Process fixtures and store them in the database."""
        processed_fixtures = []

        for fixture_data in fixtures:
            try:
                # Check if fixture already exists
                existing_fixture = self.db.query(Fixture).filter(Fixture.fixture_id == fixture_data["fixture_id"]).first()

                if not existing_fixture:
                    # Create new fixture
                    new_fixture = Fixture(
                        fixture_id=fixture_data["fixture_id"],
                        date=datetime.fromisoformat(fixture_data["date"]),
                        league_name=fixture_data["league_name"],
                        home_team=fixture_data["home_team"],
                        away_team=fixture_data["away_team"]
                    )

                    self.db.add(new_fixture)
                    logger.info(f"Added fixture to database: {fixture_data['home_team']} vs {fixture_data['away_team']}")

                    # Format for prediction
                    processed_fixture = {
                        "fixture": {
                            "id": fixture_data["fixture_id"],
                            "date": fixture_data["date"]
                        },
                        "league": {
                            "name": fixture_data["league_name"]
                        },
                        "teams": {
                            "home": {
                                "name": fixture_data["home_team"],
                                "form": fixture_data["home_form"]
                            },
                            "away": {
                                "name": fixture_data["away_team"],
                                "form": fixture_data["away_form"]
                            }
                        },
                        "odds": {
                            "home": fixture_data["home_odds"],
                            "draw": fixture_data["draw_odds"],
                            "away": fixture_data["away_odds"]
                        }
                    }

                    processed_fixtures.append(processed_fixture)
                else:
                    logger.info(f"Fixture already exists: {fixture_data['home_team']} vs {fixture_data['away_team']}")

                    # Format existing fixture for prediction
                    processed_fixture = {
                        "fixture": {
                            "id": existing_fixture.fixture_id,
                            "date": existing_fixture.date.isoformat() if existing_fixture.date else None
                        },
                        "league": {
                            "name": existing_fixture.league_name
                        },
                        "teams": {
                            "home": {
                                "name": existing_fixture.home_team,
                                "form": fixture_data["home_form"]
                            },
                            "away": {
                                "name": existing_fixture.away_team,
                                "form": fixture_data["away_form"]
                            }
                        },
                        "odds": {
                            "home": fixture_data["home_odds"],
                            "draw": fixture_data["draw_odds"],
                            "away": fixture_data["away_odds"]
                        }
                    }

                    processed_fixtures.append(processed_fixture)

            except Exception as e:
                logger.error(f"Error processing fixture: {str(e)}")

        # Commit changes
        self.db.commit()

        return processed_fixtures

    def create_features(self, fixture):
        """Create features for ML prediction."""
        try:
            # Extract basic information
            home_team = fixture["teams"]["home"]["name"]
            away_team = fixture["teams"]["away"]["name"]
            home_form = fixture["teams"]["home"]["form"]
            away_form = fixture["teams"]["away"]["form"]

            # Get odds if available
            home_odds = fixture["odds"]["home"] if fixture["odds"]["home"] else 2.0
            draw_odds = fixture["odds"]["draw"] if fixture["odds"]["draw"] else 3.0
            away_odds = fixture["odds"]["away"] if fixture["odds"]["away"] else 2.0

            # Calculate derived features
            form_diff = home_form - away_form
            odds_diff = home_odds - away_odds
            total_form = home_form + away_form
            total_odds = home_odds + draw_odds + away_odds

            # Create features for ML model (match the 9 features expected by the model)
            features = {
                "home_form": home_form,
                "away_form": away_form,
                "home_odds": home_odds,
                "draw_odds": draw_odds,
                "away_odds": away_odds,
                "form_diff": form_diff,
                "odds_diff": odds_diff,
                "total_form": total_form,
                "total_odds": total_odds
            }

            # Store additional info for fallback logic
            self.additional_info = {
                "home_team": home_team,
                "away_team": away_team,
                "home_win_prob": 1/home_odds if home_odds else 0.4,
                "draw_prob": 1/draw_odds if draw_odds else 0.2,
                "away_win_prob": 1/away_odds if away_odds else 0.4
            }

            return features

        except Exception as e:
            logger.error(f"Error creating features: {str(e)}")
            return None

    def predict_match_result(self, features):
        """Predict match result using ML model or fallback logic."""
        try:
            if self.match_result_model:
                # Prepare features for ML model
                feature_df = pd.DataFrame([features])

                # Make prediction
                prediction_probs = self.match_result_model.predict_proba(feature_df)[0]

                # Get class labels (home, draw, away)
                classes = self.match_result_model.classes_

                # Create prediction dictionary
                result = {
                    "home_win": prediction_probs[list(classes).index("home")] if "home" in classes else features["home_win_prob"],
                    "draw": prediction_probs[list(classes).index("draw")] if "draw" in classes else features["draw_prob"],
                    "away_win": prediction_probs[list(classes).index("away")] if "away" in classes else features["away_win_prob"]
                }

                # Determine most likely outcome
                probs = [result["home_win"], result["draw"], result["away_win"]]
                outcomes = ["home", "draw", "away"]
                result["prediction"] = outcomes[probs.index(max(probs))]

                # Get odds for the predicted outcome
                if result["prediction"] == "home":
                    result["odds"] = features["home_odds"]
                elif result["prediction"] == "draw":
                    result["odds"] = features["draw_odds"]
                else:
                    result["odds"] = features["away_odds"]

                # Calculate confidence
                result["confidence"] = max(probs)

                return result
            else:
                # Fallback logic
                home_prob = self.additional_info["home_win_prob"]
                draw_prob = self.additional_info["draw_prob"]
                away_prob = self.additional_info["away_win_prob"]

                # Adjust based on form
                form_diff = features["form_diff"]
                form_factor = 0.1 * form_diff

                home_prob = max(0.1, min(0.8, home_prob + form_factor))
                away_prob = max(0.1, min(0.8, away_prob - form_factor))

                # Normalize probabilities
                total_prob = home_prob + draw_prob + away_prob
                home_prob /= total_prob
                draw_prob /= total_prob
                away_prob /= total_prob

                # Determine most likely outcome
                probs = [home_prob, draw_prob, away_prob]
                outcomes = ["home", "draw", "away"]
                prediction = outcomes[probs.index(max(probs))]

                # Get odds for the predicted outcome
                if prediction == "home":
                    odds = features["home_odds"]
                elif prediction == "draw":
                    odds = features["draw_odds"]
                else:
                    odds = features["away_odds"]

                return {
                    "prediction": prediction,
                    "home_win": home_prob,
                    "draw": draw_prob,
                    "away_win": away_prob,
                    "odds": odds,
                    "confidence": max(probs)
                }

        except Exception as e:
            logger.error(f"Error predicting match result: {str(e)}")

            # Return default prediction
            home_odds = features.get("home_odds", 2.0)
            away_odds = features.get("away_odds", 2.0)
            return {
                "prediction": "home" if home_odds < away_odds else "away",
                "home_win": 0.4,
                "draw": 0.2,
                "away_win": 0.4,
                "odds": min(home_odds, away_odds),
                "confidence": 0.6
            }

    def predict_over_under(self, features):
        """Predict over/under using ML model or fallback logic."""
        try:
            if self.over_under_model:
                # Prepare features for ML model
                feature_df = pd.DataFrame([features])

                # Make prediction
                prediction_probs = self.over_under_model.predict_proba(feature_df)[0]

                # Get class labels (over, under)
                classes = self.over_under_model.classes_

                # Create prediction dictionary
                result = {
                    "over_2_5": prediction_probs[list(classes).index("over")] if "over" in classes else 0.55,
                    "under_2_5": prediction_probs[list(classes).index("under")] if "under" in classes else 0.45
                }

                # Determine most likely outcome
                result["prediction"] = "over" if result["over_2_5"] > result["under_2_5"] else "under"

                # Set default odds
                result["odds"] = 1.9

                # Calculate confidence
                result["confidence"] = max(result["over_2_5"], result["under_2_5"])

                return result
            else:
                # Fallback logic based on team form and odds
                # Higher form teams tend to score more goals
                total_form = features.get("total_form", 2.0)

                # Calculate over/under probabilities
                over_prob = 0.5 + (0.05 * (total_form - 2))  # Adjust based on form
                over_prob = max(0.3, min(0.7, over_prob))  # Limit to reasonable range
                under_prob = 1 - over_prob

                return {
                    "prediction": "over" if over_prob > under_prob else "under",
                    "over_2_5": over_prob,
                    "under_2_5": under_prob,
                    "odds": 1.9,  # Default odds for over/under
                    "confidence": max(over_prob, under_prob)
                }

        except Exception as e:
            logger.error(f"Error predicting over/under: {str(e)}")

            # Return default prediction
            return {
                "prediction": "over",
                "over_2_5": 0.55,
                "under_2_5": 0.45,
                "odds": 1.9,
                "confidence": 0.55
            }

    def predict_btts(self, features):
        """Predict both teams to score using ML model or fallback logic."""
        try:
            if self.btts_model:
                # Prepare features for ML model
                feature_df = pd.DataFrame([features])

                # Make prediction
                prediction_probs = self.btts_model.predict_proba(feature_df)[0]

                # Get class labels (yes, no)
                classes = self.btts_model.classes_

                # Create prediction dictionary
                result = {
                    "btts_yes": prediction_probs[list(classes).index("yes")] if "yes" in classes else 0.6,
                    "btts_no": prediction_probs[list(classes).index("no")] if "no" in classes else 0.4
                }

                # Determine most likely outcome
                result["prediction"] = "yes" if result["btts_yes"] > result["btts_no"] else "no"

                # Set default odds
                result["odds"] = 1.8

                # Calculate confidence
                result["confidence"] = max(result["btts_yes"], result["btts_no"])

                return result
            else:
                # Fallback logic based on team form
                # Higher form teams tend to score more goals
                home_form = features.get("home_form", 1.0)
                away_form = features.get("away_form", 1.0)

                # Calculate BTTS probabilities
                btts_yes_prob = 0.5 + (0.05 * (home_form + away_form - 2))  # Adjust based on form
                btts_yes_prob = max(0.3, min(0.7, btts_yes_prob))  # Limit to reasonable range
                btts_no_prob = 1 - btts_yes_prob

                return {
                    "prediction": "yes" if btts_yes_prob > btts_no_prob else "no",
                    "btts_yes": btts_yes_prob,
                    "btts_no": btts_no_prob,
                    "odds": 1.8,  # Default odds for BTTS
                    "confidence": max(btts_yes_prob, btts_no_prob)
                }

        except Exception as e:
            logger.error(f"Error predicting BTTS: {str(e)}")

            # Return default prediction
            return {
                "prediction": "yes",
                "btts_yes": 0.6,
                "btts_no": 0.4,
                "odds": 1.8,
                "confidence": 0.6
            }

    def generate_predictions(self, processed_fixtures):
        """Generate predictions for the processed fixtures using ML models."""
        all_predictions = []

        for fixture in processed_fixtures:
            try:
                # Get fixture details
                fixture_id = fixture["fixture"]["id"]
                home_team = fixture["teams"]["home"]["name"]
                away_team = fixture["teams"]["away"]["name"]

                # Create features for prediction
                features = self.create_features(fixture)

                if not features:
                    logger.error(f"Could not create features for {home_team} vs {away_team}")
                    continue

                # Generate predictions
                match_result = self.predict_match_result(features)
                over_under = self.predict_over_under(features)
                btts = self.predict_btts(features)

                # Create predictions
                predictions = [
                    {
                        "type": "match_result",
                        "prediction": match_result["prediction"],
                        "home_win": round(match_result["home_win"] * 100),
                        "draw": round(match_result["draw"] * 100),
                        "away_win": round(match_result["away_win"] * 100),
                        "odds": match_result["odds"],
                        "confidence": round(match_result["confidence"] * 100)
                    },
                    {
                        "type": "over_under",
                        "prediction": over_under["prediction"],
                        "over_2_5": round(over_under["over_2_5"] * 100),
                        "under_2_5": round(over_under["under_2_5"] * 100),
                        "odds": over_under["odds"],
                        "confidence": round(over_under["confidence"] * 100)
                    },
                    {
                        "type": "btts",
                        "prediction": btts["prediction"],
                        "btts_yes": round(btts["btts_yes"] * 100),
                        "btts_no": round(btts["btts_no"] * 100),
                        "odds": btts["odds"],
                        "confidence": round(btts["confidence"] * 100)
                    }
                ]

                # Add to all predictions
                fixture_info = {
                    "fixture_id": fixture_id,
                    "date": fixture["fixture"]["date"],
                    "league": fixture["league"]["name"],
                    "home_team": home_team,
                    "away_team": away_team
                }

                all_predictions.append({
                    "fixture": fixture_info,
                    "predictions": predictions
                })

                logger.info(f"Generated prediction for {home_team} vs {away_team}")

                # Save prediction to database
                for pred in predictions:
                    prediction_type = pred["type"]

                    if prediction_type == "match_result":
                        match_result_pred = pred["prediction"]
                        home_win_pred = pred["home_win"] / 100
                        draw_pred = pred["draw"] / 100
                        away_win_pred = pred["away_win"] / 100
                        over_under_pred = None
                        over_2_5_pred = None
                        under_2_5_pred = None
                        btts_pred = None
                        btts_yes_pred = None
                        btts_no_pred = None
                    elif prediction_type == "over_under":
                        match_result_pred = None
                        home_win_pred = None
                        draw_pred = None
                        away_win_pred = None
                        over_under_pred = pred["prediction"]
                        over_2_5_pred = pred["over_2_5"] / 100
                        under_2_5_pred = pred["under_2_5"] / 100
                        btts_pred = None
                        btts_yes_pred = None
                        btts_no_pred = None
                    elif prediction_type == "btts":
                        match_result_pred = None
                        home_win_pred = None
                        draw_pred = None
                        away_win_pred = None
                        over_under_pred = None
                        over_2_5_pred = None
                        under_2_5_pred = None
                        btts_pred = pred["prediction"]
                        btts_yes_pred = pred["btts_yes"] / 100
                        btts_no_pred = pred["btts_no"] / 100

                    # Create prediction object
                    prediction = Prediction(
                        fixture_id=fixture_id,
                        match_result_pred=match_result_pred,
                        home_win_pred=home_win_pred,
                        draw_pred=draw_pred,
                        away_win_pred=away_win_pred,
                        over_under_pred=over_under_pred,
                        over_2_5_pred=over_2_5_pred,
                        under_2_5_pred=under_2_5_pred,
                        btts_pred=btts_pred,
                        btts_yes_pred=btts_yes_pred,
                        btts_no_pred=btts_no_pred,
                        prediction_type=prediction_type,
                        odds=pred["odds"],
                        confidence=pred["confidence"] / 100
                    )

                    self.db.add(prediction)

            except Exception as e:
                logger.error(f"Error generating prediction: {str(e)}")

        # Commit changes
        self.db.commit()

        return all_predictions

    def categorize_predictions(self, predictions):
        """Categorize predictions into different odds groups."""
        # Track used fixtures to avoid duplicates across categories
        used_fixtures = set()

        # Generate combinations for each category
        categorized = {
            "2_odds": [],
            "5_odds": [],
            "10_odds": [],
            "rollover": []
        }

        # Process categories in order of priority
        for category in ["rollover", "10_odds", "5_odds", "2_odds"]:
            # Target odds for each category
            target_odds = {
                "2_odds": 2.0,
                "5_odds": 5.0,
                "10_odds": 10.0,
                "rollover": 3.0
            }

            # Get available predictions (excluding already used fixtures)
            available_predictions = []
            for prediction in predictions:
                fixture = prediction.get("fixture", {})
                fixture_id = fixture.get("fixture_id")

                if fixture_id not in used_fixtures:
                    available_predictions.append(prediction)

            # Create combinations for this category
            combinations = self.create_prediction_combinations(
                available_predictions, target_odds[category]
            )

            # Mark used fixtures
            for combo in combinations:
                for pred in combo.get("predictions", []):
                    fixture_id = pred.get("fixture", {}).get("fixture_id")
                    if fixture_id:
                        used_fixtures.add(fixture_id)

            # Add combinations to category
            categorized[category] = combinations

            # Add day number for rollover
            if category == "rollover":
                for i, combo in enumerate(categorized[category]):
                    combo["day"] = i + 1

        return categorized

    def create_prediction_combinations(self, predictions, target_odds):
        """Create combinations of predictions to reach target odds."""
        if not predictions:
            return []

        # Extract individual predictions
        individual_predictions = []
        for pred_group in predictions:
            fixture = pred_group.get("fixture", {})
            for pred in pred_group.get("predictions", []):
                # Add fixture info to prediction
                pred_with_fixture = pred.copy()
                pred_with_fixture["fixture"] = fixture
                individual_predictions.append(pred_with_fixture)

        # Sort by confidence (highest first)
        sorted_predictions = sorted(
            individual_predictions,
            key=lambda p: p.get("confidence", 0),
            reverse=True
        )

        # Try combinations of different sizes
        combinations = []

        # Try combinations of 1-4 predictions
        for size in range(1, min(5, len(sorted_predictions) + 1)):
            for combo in itertools.combinations(sorted_predictions, size):
                # Calculate combined odds
                combined_odds = 1.0
                combined_confidence = 0.0

                for pred in combo:
                    odds = pred.get("odds", 1.0)
                    confidence = pred.get("confidence", 0.0)

                    combined_odds *= odds
                    combined_confidence += confidence

                # Calculate average confidence
                avg_confidence = combined_confidence / len(combo) if combo else 0.0

                # Check if combined odds are close to target
                if combined_odds >= target_odds * 0.8 and combined_odds <= target_odds * 1.2:
                    combinations.append({
                        "id": f"combo_{uuid.uuid4()}",
                        "predictions": list(combo),
                        "combined_odds": combined_odds,
                        "combined_confidence": avg_confidence
                    })

        # Sort by combined confidence (highest first)
        sorted_combinations = sorted(
            combinations,
            key=lambda x: x.get("combined_confidence", 0),
            reverse=True
        )

        return sorted_combinations[:5]  # Limit to 5 combinations

    def save_prediction_combinations(self, combinations, category):
        """Save prediction combinations to the database."""
        try:
            # Save each combination
            for combo in combinations:
                # Create combination record
                combination = PredictionCombination(
                    id=combo.get("id", f"{category}_{uuid.uuid4()}"),
                    category=category,
                    combined_odds=combo.get("combined_odds", 0),
                    combined_confidence=combo.get("combined_confidence", 0),
                    rollover_day=combo.get("day")
                )

                # Add to database
                self.db.add(combination)
                self.db.flush()  # Flush to get the ID

                # Add predictions to combination
                for pred_dict in combo.get("predictions", []):
                    # Get fixture info
                    fixture = pred_dict.get("fixture", {})
                    fixture_id = fixture.get("fixture_id")
                    prediction_type = pred_dict.get("type")

                    if fixture_id and prediction_type:
                        # Find prediction in database
                        prediction = self.db.query(Prediction).filter(
                            Prediction.fixture_id == fixture_id,
                            Prediction.prediction_type == prediction_type
                        ).first()

                        # Add prediction to combination
                        if prediction:
                            combination.predictions.append(prediction)

            # Commit changes
            self.db.commit()

            return True

        except Exception as e:
            logger.error(f"Error saving prediction combinations: {str(e)}")
            self.db.rollback()
            return False

def run_ml_prediction_pipeline():
    """Execute the ML prediction pipeline for the real fixtures."""
    logger.info("Starting ML prediction pipeline for real fixtures")

    # Create database session
    db = SessionLocal()

    try:
        # Initialize ML prediction service
        ml_prediction_service = MLPredictionService(db)

        # Step 1: Process fixtures
        logger.info("Step 1: Processing fixtures")
        processed_fixtures = ml_prediction_service.process_fixtures(REAL_FIXTURES)
        logger.info(f"Processed {len(processed_fixtures)} fixtures")

        # Step 2: Generate predictions using ML models
        logger.info("Step 2: Generating predictions using ML models")
        all_predictions = ml_prediction_service.generate_predictions(processed_fixtures)
        logger.info(f"Generated {len(all_predictions)} predictions")

        # Step 3: Categorize predictions
        logger.info("Step 3: Categorizing predictions")
        categorized_predictions = ml_prediction_service.categorize_predictions(all_predictions)

        # Print categorized predictions
        for category, predictions in categorized_predictions.items():
            logger.info(f"Category: {category}, Number of combinations: {len(predictions)}")

            if predictions:
                sample_combo = predictions[0]
                logger.info(f"Sample combination - Combined odds: {sample_combo.get('combined_odds')}, Combined confidence: {sample_combo.get('combined_confidence')}")
                logger.info(f"Number of predictions in combination: {len(sample_combo.get('predictions', []))}")

                # Save combinations to database
                logger.info(f"Saving {len(predictions)} combinations for category {category}")
                success = ml_prediction_service.save_prediction_combinations(predictions, category)

                if success:
                    logger.info(f"Successfully saved combinations for category {category}")
                else:
                    logger.error(f"Failed to save combinations for category {category}")

        # Step 4: Print detailed predictions for each fixture
        logger.info("\nDetailed predictions for each fixture:")
        for prediction in all_predictions:
            fixture = prediction.get("fixture", {})
            home_team = fixture.get("home_team")
            away_team = fixture.get("away_team")

            logger.info(f"\n{home_team} vs {away_team}:")

            for pred in prediction.get("predictions", []):
                pred_type = pred.get("type")

                if pred_type == "match_result":
                    result = pred.get("prediction")
                    confidence = pred.get("confidence")
                    odds = pred.get("odds")

                    if result == "home":
                        logger.info(f"  Match Result: {home_team} to win (Confidence: {confidence}%, Odds: {odds})")
                    elif result == "draw":
                        logger.info(f"  Match Result: Draw (Confidence: {confidence}%, Odds: {odds})")
                    elif result == "away":
                        logger.info(f"  Match Result: {away_team} to win (Confidence: {confidence}%, Odds: {odds})")

                elif pred_type == "over_under":
                    result = pred.get("prediction")
                    confidence = pred.get("confidence")
                    odds = pred.get("odds")

                    logger.info(f"  Over/Under: {result.capitalize()} 2.5 goals (Confidence: {confidence}%, Odds: {odds})")

                elif pred_type == "btts":
                    result = pred.get("prediction")
                    confidence = pred.get("confidence")
                    odds = pred.get("odds")

                    logger.info(f"  Both Teams to Score: {result.capitalize()} (Confidence: {confidence}%, Odds: {odds})")

        logger.info("\nML prediction pipeline completed successfully")

    except Exception as e:
        logger.error(f"Error in ML prediction pipeline: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

    finally:
        # Close database session
        db.close()

if __name__ == "__main__":
    # Run the ML prediction pipeline
    run_ml_prediction_pipeline()
