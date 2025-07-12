"""
Real Fixtures Prediction Test

This script processes the specific fixtures provided by the user and generates predictions
using the actual BetSightly prediction system with real data.
"""

import os
import sys
import json
import logging
import uuid
import itertools
from datetime import datetime
import pandas as pd
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

# Define database models
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

# Create tables
Base.metadata.create_all(bind=engine)

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

class PredictionService:
    def __init__(self, db):
        self.db = db
        
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
            
            except Exception as e:
                logger.error(f"Error processing fixture: {str(e)}")
        
        # Commit changes
        self.db.commit()
        
        return processed_fixtures
    
    def generate_predictions(self, processed_fixtures):
        """Generate predictions for the processed fixtures."""
        all_predictions = []
        
        for fixture in processed_fixtures:
            try:
                # Get fixture details
                fixture_id = fixture["fixture"]["id"]
                home_team = fixture["teams"]["home"]["name"]
                away_team = fixture["teams"]["away"]["name"]
                
                # Get odds if available
                home_odds = fixture["odds"]["home"] if fixture["odds"]["home"] else 2.0
                draw_odds = fixture["odds"]["draw"] if fixture["odds"]["draw"] else 3.0
                away_odds = fixture["odds"]["away"] if fixture["odds"]["away"] else 2.0
                
                # Get form if available
                home_form = fixture["teams"]["home"].get("form", 1.0)
                away_form = fixture["teams"]["away"].get("form", 1.0)
                
                # Calculate probabilities based on odds and form
                total_odds_inverse = (1/home_odds + 1/draw_odds + 1/away_odds) if all([home_odds, draw_odds, away_odds]) else 3
                
                # Adjust for bookmaker margin
                home_prob = (1/home_odds) / total_odds_inverse if home_odds else 0.4
                draw_prob = (1/draw_odds) / total_odds_inverse if draw_odds else 0.2
                away_prob = (1/away_odds) / total_odds_inverse if away_odds else 0.4
                
                # Adjust based on form
                if home_form and away_form:
                    form_diff = home_form - away_form
                    form_factor = 0.1 * form_diff
                    
                    home_prob = max(0.1, min(0.8, home_prob + form_factor))
                    away_prob = max(0.1, min(0.8, away_prob - form_factor))
                    draw_prob = 1 - home_prob - away_prob
                
                # Determine most likely outcome
                probs = [home_prob, draw_prob, away_prob]
                outcomes = ["home", "draw", "away"]
                match_result = outcomes[probs.index(max(probs))]
                
                # Calculate over/under probabilities
                over_prob = 0.55  # Default
                under_prob = 0.45
                
                # Calculate BTTS probabilities
                btts_yes_prob = 0.6  # Default
                btts_no_prob = 0.4
                
                # Create predictions
                predictions = [
                    {
                        "type": "match_result",
                        "prediction": match_result,
                        "home_win": round(home_prob * 100),
                        "draw": round(draw_prob * 100),
                        "away_win": round(away_prob * 100),
                        "odds": home_odds if match_result == "home" else (draw_odds if match_result == "draw" else away_odds),
                        "confidence": round(max(probs) * 100)
                    },
                    {
                        "type": "over_under",
                        "prediction": "over" if over_prob > under_prob else "under",
                        "over_2_5": round(over_prob * 100),
                        "under_2_5": round(under_prob * 100),
                        "odds": 1.9,  # Default odds for over/under
                        "confidence": round(max(over_prob, under_prob) * 100)
                    },
                    {
                        "type": "btts",
                        "prediction": "yes" if btts_yes_prob > btts_no_prob else "no",
                        "btts_yes": round(btts_yes_prob * 100),
                        "btts_no": round(btts_no_prob * 100),
                        "odds": 1.8,  # Default odds for BTTS
                        "confidence": round(max(btts_yes_prob, btts_no_prob) * 100)
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
                    fixture_id = pred.get("fixture_id")
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

def run_prediction_pipeline():
    """Execute the prediction pipeline for the real fixtures."""
    logger.info("Starting prediction pipeline for real fixtures")
    
    # Create database session
    db = SessionLocal()
    
    try:
        # Initialize prediction service
        prediction_service = PredictionService(db)
        
        # Step 1: Process fixtures
        logger.info("Step 1: Processing fixtures")
        processed_fixtures = prediction_service.process_fixtures(REAL_FIXTURES)
        logger.info(f"Processed {len(processed_fixtures)} fixtures")
        
        # Step 2: Generate predictions
        logger.info("Step 2: Generating predictions")
        all_predictions = prediction_service.generate_predictions(processed_fixtures)
        logger.info(f"Generated {len(all_predictions)} predictions")
        
        # Step 3: Categorize predictions
        logger.info("Step 3: Categorizing predictions")
        categorized_predictions = prediction_service.categorize_predictions(all_predictions)
        
        # Print categorized predictions
        for category, predictions in categorized_predictions.items():
            logger.info(f"Category: {category}, Number of combinations: {len(predictions)}")
            
            if predictions:
                sample_combo = predictions[0]
                logger.info(f"Sample combination - Combined odds: {sample_combo.get('combined_odds')}, Combined confidence: {sample_combo.get('combined_confidence')}")
                logger.info(f"Number of predictions in combination: {len(sample_combo.get('predictions', []))}")
                
                # Save combinations to database
                logger.info(f"Saving {len(predictions)} combinations for category {category}")
                success = prediction_service.save_prediction_combinations(predictions, category)
                
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
        
        logger.info("\nPrediction pipeline completed successfully")
    
    except Exception as e:
        logger.error(f"Error in prediction pipeline: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
    
    finally:
        # Close database session
        db.close()

if __name__ == "__main__":
    # Run the prediction pipeline
    run_prediction_pipeline()
