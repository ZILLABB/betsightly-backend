"""
Real ML Predictions API Endpoints
Connects to the actual trained 24-model ML system.
"""

import logging
import sys
import os
from typing import List, Dict, Any, Optional
from datetime import datetime, date
from fastapi import APIRouter, HTTPException, Query
from pathlib import Path
import pandas as pd
import joblib

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from services.apifootball_service import APIFootballService

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter()

class RealMLPredictionService:
    """Service that uses the actual trained 24 ML models."""
    
    def __init__(self):
        """Initialize the real ML prediction service."""
        self.apifootball_service = APIFootballService()
        self.models_dir = Path("models")
        self.encoders = self.load_encoders()
        self.models = self.load_trained_models()
        
    def load_encoders(self) -> Dict[str, Any]:
        """Load the trained encoders from GitHub dataset training."""
        encoders = {}
        try:
            # Load encoders from pickle file (from our training)
            import pickle
            encoder_path = self.models_dir / 'encoders.pkl'
            if encoder_path.exists():
                with open(encoder_path, 'rb') as f:
                    encoders = pickle.load(f)
                logger.info(f"✅ Loaded encoders from GitHub training: {list(encoders.keys())}")
            else:
                logger.warning("⚠️  GitHub training encoders not found")

            return encoders

        except Exception as e:
            logger.error(f"Error loading encoders: {str(e)}")
            return {}
    
    def load_trained_models(self) -> Dict[str, Dict[str, Any]]:
        """Load all trained models from GitHub dataset training."""
        models = {}
        import pickle

        # Model types and their files (from our training)
        model_types = {
            'xgboost': [
                'match_result', 'over_2_5', 'over_1_5', 'over_3_5', 'btts',
                'clean_sheet_home', 'clean_sheet_away', 'win_to_nil_home', 'win_to_nil_away'
            ],
            'lightgbm': [
                'match_result', 'over_2_5', 'btts', 'clean_sheet_home', 'clean_sheet_away', 'over_3_5'
            ],
            'random_forest': [
                'match_result', 'over_2_5', 'btts'
            ],
            'neural_network': [
                'match_result', 'over_2_5', 'btts'
            ]
        }

        models_loaded = 0
        total_models = sum(len(model_names) for model_names in model_types.values())

        for model_type, model_names in model_types.items():
            models[model_type] = {}

            for model_name in model_names:
                try:
                    model_path = self.models_dir / f'{model_type}_{model_name}.pkl'

                    if model_path.exists():
                        # Load model
                        with open(model_path, 'rb') as f:
                            model = pickle.load(f)

                        models[model_type][model_name] = {
                            'model': model,
                            'scaler': None  # No scalers in our training
                        }

                        models_loaded += 1
                        logger.info(f"✅ Loaded {model_type}/{model_name}")
                    else:
                        logger.warning(f"⚠️  Model not found: {model_path}")

                except Exception as e:
                    logger.error(f"Error loading {model_type}/{model_name}: {str(e)}")

        logger.info(f"📊 Total models loaded: {models_loaded}/{total_models}")
        return models
    
    def encode_team_safe(self, team_name: str, encoder_type: str) -> int:
        """Safely encode team name, handling unknown teams."""
        try:
            encoder = self.encoders[encoder_type]
            
            # Check if team is in encoder's classes
            if team_name in encoder.classes_:
                return encoder.transform([team_name])[0]
            else:
                # Return a default encoding for unknown teams
                return 0
                
        except Exception as e:
            logger.error(f"Error encoding {team_name}: {str(e)}")
            return 0
    
    def prepare_fixture_for_prediction(self, fixture: Dict[str, Any]) -> Optional[pd.DataFrame]:
        """Prepare fixture data for ML prediction using trained model features."""
        try:
            home_team = fixture.get('home_team', 'Unknown')
            away_team = fixture.get('away_team', 'Unknown')
            league = fixture.get('league', 'Unknown')

            # Extract odds (default to neutral if not provided)
            home_odds = float(fixture.get('home_odds', 2.0))
            draw_odds = float(fixture.get('draw_odds', 3.0))
            away_odds = float(fixture.get('away_odds', 2.0))

            # Create feature vector matching training data
            features = {}

            # Team encoding (handle unknown teams gracefully)
            if 'home_team' in self.encoders and 'away_team' in self.encoders and 'league' in self.encoders:
                try:
                    # Try to encode teams, use default if unknown
                    home_encoded = self.encode_team_safe(home_team, 'home_team')
                    away_encoded = self.encode_team_safe(away_team, 'away_team')
                    league_encoded = self.encode_team_safe(league, 'league')

                    features['home_team_encoded'] = home_encoded
                    features['away_team_encoded'] = away_encoded
                    features['league_encoded'] = league_encoded

                except Exception as e:
                    logger.warning(f"Team encoding failed: {str(e)}")
                    features['home_team_encoded'] = 0
                    features['away_team_encoded'] = 0
                    features['league_encoded'] = 0
            else:
                # Default encoding if encoders not available
                features['home_team_encoded'] = 0
                features['away_team_encoded'] = 0
                features['league_encoded'] = 0

            # Odds features (exactly as in training)
            features['home_odds'] = home_odds
            features['draw_odds'] = draw_odds
            features['away_odds'] = away_odds
            features['odds_diff'] = home_odds - away_odds
            features['total_odds'] = home_odds + draw_odds + away_odds

            # Probability features (exactly as in training)
            total_prob = (1/home_odds) + (1/draw_odds) + (1/away_odds)
            features['home_win_prob'] = (1/home_odds) / total_prob
            features['draw_prob'] = (1/draw_odds) / total_prob
            features['away_win_prob'] = (1/away_odds) / total_prob

            # Form features (exactly as in training)
            features['home_form'] = max(0.1, min(1.0, 3.0 / home_odds))
            features['away_form'] = max(0.1, min(1.0, 3.0 / away_odds))
            features['form_diff'] = features['home_form'] - features['away_form']

            # Use only the exact feature columns from training
            expected_features = [
                'home_team_encoded', 'away_team_encoded', 'league_encoded',
                'home_odds', 'draw_odds', 'away_odds', 'odds_diff', 'total_odds',
                'home_win_prob', 'draw_prob', 'away_win_prob',
                'home_form', 'away_form', 'form_diff'
            ]

            # Create DataFrame with only expected features
            feature_data = {}
            for feature in expected_features:
                feature_data[feature] = features.get(feature, 0.0)

            return pd.DataFrame([feature_data])

        except Exception as e:
            logger.error(f"Error preparing fixture: {str(e)}")
            return None
    
    def generate_predictions_for_fixture(self, fixture: Dict[str, Any]) -> Dict[str, Any]:
        """Generate predictions for a single fixture using all models."""
        try:
            # Prepare features
            features_df = self.prepare_fixture_for_prediction(fixture)
            
            if features_df is None:
                return {"error": "Could not prepare features"}
            
            fixture_predictions = {
                'fixture_info': {
                    'fixture_id': fixture.get('fixture_id'),
                    'home_team': fixture.get('home_team'),
                    'away_team': fixture.get('away_team'),
                    'league': fixture.get('league_name'),
                    'date': fixture.get('date'),
                    'status': fixture.get('status')
                },
                'ml_predictions': {},
                'betting_categories': {},
                'model_summary': {'total_predictions': 0, 'successful_predictions': 0}
            }
            
            # Run predictions with each model type
            for model_type, type_models in self.models.items():
                for model_name, model_data in type_models.items():
                    try:
                        model = model_data['model']
                        scaler = model_data['scaler']
                        
                        # Prepare features
                        if scaler:
                            features_scaled = scaler.transform(features_df)
                            prediction = model.predict(features_scaled)[0]
                            probabilities = model.predict_proba(features_scaled)[0]
                        else:
                            prediction = model.predict(features_df)[0]
                            probabilities = model.predict_proba(features_df)[0]
                        
                        # Store prediction
                        pred_key = f"{model_type}_{model_name}"
                        fixture_predictions['ml_predictions'][pred_key] = {
                            'prediction': int(prediction),
                            'probabilities': probabilities.tolist(),
                            'confidence': float(max(probabilities)),
                            'model_type': model_type,
                            'model_name': model_name
                        }
                        
                        fixture_predictions['model_summary']['total_predictions'] += 1
                        
                    except Exception as e:
                        logger.error(f"Error with {model_type}/{model_name}: {str(e)}")
                        continue
            
            # Generate betting categories
            betting_categories = self.generate_betting_categories(fixture_predictions['ml_predictions'])
            fixture_predictions['betting_categories'] = betting_categories
            
            fixture_predictions['model_summary']['successful_predictions'] = len(fixture_predictions['ml_predictions'])
            
            return fixture_predictions
            
        except Exception as e:
            logger.error(f"Error generating predictions: {str(e)}")
            return {"error": str(e)}
    
    def generate_betting_categories(self, predictions: Dict[str, Any]) -> Dict[str, Any]:
        """Generate betting categories based on predictions."""
        betting_categories = {}
        
        # Define confidence thresholds for LOW RISK
        thresholds = {
            '2_odds': 0.85,   # Very high confidence - very low risk
            '5_odds': 0.80,   # High confidence - low risk  
            '10_odds': 0.75,  # High confidence - low-medium risk
            'rollover': 0.85  # Very high confidence for accumulator
        }
        
        for category, threshold in thresholds.items():
            best_prediction = None
            best_confidence = 0
            
            # Find best prediction that meets threshold
            for pred_key, pred_data in predictions.items():
                confidence = pred_data.get('confidence', 0)
                if confidence >= threshold and confidence > best_confidence:
                    best_confidence = confidence
                    best_prediction = {
                        'prediction_key': pred_key,
                        'prediction': pred_data['prediction'],
                        'confidence': confidence,
                        'model_type': pred_data['model_type'],
                        'model_name': pred_data['model_name']
                    }
            
            if best_prediction:
                betting_categories[category] = {
                    'selected': True,
                    'prediction': best_prediction,
                    'threshold_met': True,
                    'expected_odds': self.estimate_odds(category),
                    'risk_level': self.get_risk_level(category),
                    'recommendation': 'INCLUDE'
                }
            else:
                betting_categories[category] = {
                    'selected': False,
                    'threshold_met': False,
                    'reason': f'No predictions met {threshold} confidence threshold',
                    'recommendation': 'EXCLUDE'
                }
        
        return betting_categories
    
    def estimate_odds(self, category: str) -> float:
        """Estimate typical odds for betting category."""
        odds_mapping = {'2_odds': 1.8, '5_odds': 4.2, '10_odds': 8.5, 'rollover': 2.1}
        return odds_mapping.get(category, 2.0)
    
    def get_risk_level(self, category: str) -> str:
        """Get risk level for betting category."""
        risk_mapping = {'2_odds': 'VERY_LOW', '5_odds': 'LOW', '10_odds': 'LOW_MEDIUM', 'rollover': 'VERY_LOW'}
        return risk_mapping.get(category, 'MEDIUM')

# Initialize the service
ml_service = RealMLPredictionService()

# Simple cache for predictions (resets daily)
_predictions_cache = {
    'date': None,
    'data': None,
    'timestamp': None
}

@router.get("/today")
def get_todays_predictions(force_refresh: bool = Query(False, description="Force refresh predictions (default: False)")):
    """
    Get today's fixtures with real ML predictions and betting categories.
    
    Returns:
        List of fixtures with ML predictions and low-risk betting categories
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        current_time = datetime.now()

        # Check cache first (unless force refresh)
        if not force_refresh and _predictions_cache['date'] == today and _predictions_cache['data']:
            cache_age = (current_time - _predictions_cache['timestamp']).total_seconds() / 60
            if cache_age < 30:  # Cache for 30 minutes
                logger.info(f"🔄 Returning cached predictions (age: {cache_age:.1f} minutes)")
                return _predictions_cache['data']

        logger.info("🎯 Getting fresh ML predictions")

        # Get today's upcoming fixtures
        all_fixtures = ml_service.apifootball_service.get_daily_fixtures(today)
        
        # Filter for upcoming fixtures only (exclude all finished/live games)
        upcoming_fixtures = []
        excluded_statuses = [
            'Finished', 'FT', 'AET', 'PEN', 'After Pen.', 'After Extra Time',
            'Live', 'HT', 'Half Time', '1st Half', '2nd Half', 'Extra Time',
            'Penalty Shootout', 'Suspended', 'Postponed', 'Cancelled',
            'Abandoned', 'Interrupted', 'Awarded', 'WalkOver', 'Retired'
        ]

        for fixture in all_fixtures:
            status = fixture.get('status', '').strip()

            # Additional check: exclude if status contains finished game indicators
            status_lower = status.lower()
            finished_indicators = ['finished', 'ft', 'aet', 'pen', 'after', 'live', 'half', 'time', 'extra']

            is_finished = (status in excluded_statuses or
                          any(indicator in status_lower for indicator in finished_indicators))

            # Only include truly upcoming fixtures
            if not is_finished and status not in ['', 'Unknown']:
                # Additional date check - only future fixtures
                try:
                    fixture_date_str = fixture.get('date', '')
                    if fixture_date_str:
                        # Parse fixture date and compare with current time
                        fixture_date = datetime.fromisoformat(fixture_date_str.replace('Z', '+00:00'))
                        current_time = datetime.now()

                        # Only include if fixture is in the future
                        if fixture_date > current_time:
                            upcoming_fixtures.append(fixture)
                except:
                    # If date parsing fails, include only if status looks upcoming
                    if status in ['Not Started', 'Scheduled', 'Fixture']:
                        upcoming_fixtures.append(fixture)
        
        logger.info(f"📊 Found {len(upcoming_fixtures)} upcoming fixtures")
        
        # Generate predictions for each fixture
        predictions_results = []
        for fixture in upcoming_fixtures:
            prediction_result = ml_service.generate_predictions_for_fixture(fixture)
            if 'error' not in prediction_result:
                predictions_results.append(prediction_result)
        
        result = {
            "status": "success",
            "date": today,
            "total_fixtures": len(all_fixtures),
            "upcoming_fixtures": len(upcoming_fixtures),
            "predictions_generated": len(predictions_results),
            "models_used": sum(len(ml_service.models[mt]) for mt in ml_service.models),
            "predictions": predictions_results,
            "cached": False,
            "cache_info": "Fresh predictions generated"
        }

        # Update cache
        _predictions_cache['date'] = today
        _predictions_cache['data'] = result
        _predictions_cache['timestamp'] = current_time

        return result
        
    except Exception as e:
        logger.error(f"Error getting today's predictions: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@router.get("/categories")
def get_betting_categories():
    """
    Get today's betting categories with low-risk selections.
    
    Returns:
        Categorized betting recommendations for today's fixtures
    """
    try:
        # Get today's predictions
        predictions_response = get_todays_predictions()
        predictions = predictions_response.get('predictions', [])
        
        # Extract betting categories
        categorized_results = {
            '2_odds': [],
            '5_odds': [],
            '10_odds': [],
            'rollover': []
        }
        
        for prediction in predictions:
            betting_categories = prediction.get('betting_categories', {})
            fixture_info = prediction.get('fixture_info', {})
            
            for category, category_data in betting_categories.items():
                if category_data.get('selected', False):
                    categorized_results[category].append({
                        'fixture': fixture_info,
                        'prediction': category_data['prediction'],
                        'confidence': category_data['prediction']['confidence'],
                        'risk_level': category_data['risk_level'],
                        'expected_odds': category_data['expected_odds'],
                        'recommendation': category_data['recommendation']
                    })
        
        return {
            "status": "success",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "categories": categorized_results,
            "summary": {
                "2_odds_count": len(categorized_results['2_odds']),
                "5_odds_count": len(categorized_results['5_odds']),
                "10_odds_count": len(categorized_results['10_odds']),
                "rollover_count": len(categorized_results['rollover']),
                "total_selections": sum(len(cat) for cat in categorized_results.values())
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting betting categories: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@router.get("/fixture/{fixture_id}")
def get_fixture_prediction(fixture_id: int):
    """
    Get ML predictions for a specific fixture.
    
    Args:
        fixture_id: The ID of the fixture
        
    Returns:
        ML predictions and betting categories for the fixture
    """
    try:
        # Get today's fixtures
        today = datetime.now().strftime("%Y-%m-%d")
        all_fixtures = ml_service.apifootball_service.get_daily_fixtures(today)
        
        # Find the specific fixture
        target_fixture = None
        for fixture in all_fixtures:
            if fixture.get('fixture_id') == fixture_id:
                target_fixture = fixture
                break
        
        if not target_fixture:
            raise HTTPException(status_code=404, detail="Fixture not found")
        
        # Generate prediction for this fixture
        prediction_result = ml_service.generate_predictions_for_fixture(target_fixture)
        
        if 'error' in prediction_result:
            raise HTTPException(status_code=500, detail=prediction_result['error'])
        
        return {
            "status": "success",
            "fixture_id": fixture_id,
            "prediction": prediction_result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting fixture prediction: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@router.get("/models/status")
def get_models_status():
    """
    Get status of loaded ML models.
    
    Returns:
        Information about loaded models and their status
    """
    try:
        model_status = {}
        total_models = 0
        
        for model_type, type_models in ml_service.models.items():
            model_status[model_type] = {
                'count': len(type_models),
                'models': list(type_models.keys())
            }
            total_models += len(type_models)
        
        return {
            "status": "success",
            "total_models": total_models,
            "model_breakdown": model_status,
            "encoders_loaded": len(ml_service.encoders),
            "service_ready": total_models > 0
        }
        
    except Exception as e:
        logger.error(f"Error getting models status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
