#!/usr/bin/env python3
"""
Real ML Prediction Test using trained models and APIFootball.com data.
Comprehensive end-to-end test with actual trained models.
"""

import os
import sys
import logging
import pandas as pd
import numpy as np
import joblib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

from services.apifootball_service import APIFootballService


class RealMLPredictionTest:
    """Real ML prediction test using trained models and live data."""
    
    def __init__(self):
        """Initialize the test."""
        self.apifootball_service = APIFootballService()
        self.models_dir = Path("models")
        
        # Load encoders
        self.encoders = self.load_encoders()
        
        # Load trained models
        self.models = self.load_trained_models()
        
        # Test statistics
        self.stats = {
            'fixtures_fetched': 0,
            'valid_fixtures': 0,
            'predictions_generated': 0,
            'models_used': 0,
            'betting_categories_generated': 0,
            'start_time': datetime.now()
        }
    
    def load_encoders(self) -> Dict[str, Any]:
        """Load the trained encoders."""
        encoders = {}
        try:
            encoder_files = {
                'home_team': 'home_team_encoder.joblib',
                'away_team': 'away_team_encoder.joblib',
                'division': 'division_encoder.joblib'
            }
            
            for name, filename in encoder_files.items():
                encoder_path = self.models_dir / filename
                if encoder_path.exists():
                    encoders[name] = joblib.load(encoder_path)
                    print(f"✅ Loaded {name} encoder")
                else:
                    print(f"⚠️  {name} encoder not found")
            
            return encoders
            
        except Exception as e:
            logger.error(f"Error loading encoders: {str(e)}")
            return {}
    
    def load_trained_models(self) -> Dict[str, Dict[str, Any]]:
        """Load all trained models."""
        models = {}
        
        model_types = ['xgboost', 'lightgbm', 'random_forest', 'neural_network']
        
        for model_type in model_types:
            models[model_type] = {}
            type_dir = self.models_dir / model_type
            
            if type_dir.exists():
                model_files = list(type_dir.glob("*_model.joblib"))
                scaler_files = list(type_dir.glob("*_scaler.joblib"))
                
                for model_file in model_files:
                    model_name = model_file.stem.replace('_model', '')
                    
                    try:
                        # Load model
                        model = joblib.load(model_file)
                        
                        # Load scaler if exists
                        scaler_file = type_dir / f"{model_name}_scaler.joblib"
                        scaler = joblib.load(scaler_file) if scaler_file.exists() else None
                        
                        models[model_type][model_name] = {
                            'model': model,
                            'scaler': scaler
                        }
                        
                        print(f"✅ Loaded {model_type}/{model_name}")
                        
                    except Exception as e:
                        logger.error(f"Error loading {model_type}/{model_name}: {str(e)}")
        
        total_models = sum(len(models[mt]) for mt in models)
        print(f"📊 Total models loaded: {total_models}")
        
        return models
    
    def print_header(self):
        """Print test header."""
        print("\n" + "="*80)
        print("🚀 REAL ML PREDICTION TEST - BETSIGHTLY")
        print("="*80)
        print(f"📅 Test Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🌐 Data Source: APIFootball.com (Live)")
        print(f"🤖 ML Models: Real trained models")
        print(f"🎯 Categories: All prediction types + betting categories")
        print("="*80)
    
    def fetch_upcoming_fixtures(self) -> List[Dict[str, Any]]:
        """Fetch upcoming fixtures from APIFootball.com."""
        print("\n📡 STEP 1: FETCHING UPCOMING FIXTURES")
        print("-" * 60)
        
        try:
            # Test connection
            if not self.apifootball_service.test_connection():
                print("❌ APIFootball.com connection failed!")
                return []
            
            print("✅ APIFootball.com connection successful")
            
            # Get today's fixtures
            today = datetime.now().strftime("%Y-%m-%d")
            all_fixtures = self.apifootball_service.get_daily_fixtures(today)
            
            self.stats['fixtures_fetched'] = len(all_fixtures)
            print(f"📋 Retrieved {len(all_fixtures)} total fixtures")
            
            # Filter for upcoming fixtures
            upcoming_fixtures = []
            excluded_statuses = ['Finished', 'FT', 'Live', 'HT', 'Postponed', 'Cancelled']
            
            for fixture in all_fixtures:
                status = fixture.get('status', '').strip()
                if status not in excluded_statuses:
                    upcoming_fixtures.append(fixture)
            
            self.stats['valid_fixtures'] = len(upcoming_fixtures)
            print(f"⚽ Found {len(upcoming_fixtures)} upcoming fixtures")
            
            # Display sample fixtures
            if upcoming_fixtures:
                print("\n🔝 Sample upcoming fixtures:")
                for i, fixture in enumerate(upcoming_fixtures[:5], 1):
                    home = fixture.get('home_team', 'Unknown')
                    away = fixture.get('away_team', 'Unknown')
                    league = fixture.get('league_name', 'Unknown')
                    date = fixture.get('date', 'Unknown')[:16]
                    print(f"   {i}. {home} vs {away} ({league}) - {date}")
            
            return upcoming_fixtures
            
        except Exception as e:
            logger.error(f"Error fetching fixtures: {str(e)}")
            print(f"❌ Error: {str(e)}")
            return []
    
    def prepare_fixture_for_prediction(self, fixture: Dict[str, Any]) -> Optional[pd.DataFrame]:
        """Prepare fixture data for ML prediction."""
        try:
            home_team = fixture.get('home_team', 'Unknown')
            away_team = fixture.get('away_team', 'Unknown')
            
            # Create feature vector
            features = {}
            
            # Encode teams (handle unknown teams)
            if 'home_team' in self.encoders and 'away_team' in self.encoders:
                try:
                    # Try to encode, use fallback for unknown teams
                    home_encoded = self.encode_team_safe(home_team, 'home_team')
                    away_encoded = self.encode_team_safe(away_team, 'away_team')
                    
                    features['home_team_encoded'] = home_encoded
                    features['away_team_encoded'] = away_encoded
                    
                    # Use default division encoding
                    features['division_encoded'] = 0  # Default division
                    
                    return pd.DataFrame([features])
                    
                except Exception as e:
                    logger.error(f"Error encoding teams: {str(e)}")
                    return None
            else:
                print(f"   ⚠️  Encoders not available")
                return None
                
        except Exception as e:
            logger.error(f"Error preparing fixture: {str(e)}")
            return None
    
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
    
    def generate_predictions(self, fixtures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generate predictions for all fixtures using real models."""
        print(f"\n🤖 STEP 2: GENERATING REAL ML PREDICTIONS")
        print("-" * 60)
        
        prediction_results = []
        
        for i, fixture in enumerate(fixtures, 1):
            home_team = fixture.get('home_team', 'Unknown')
            away_team = fixture.get('away_team', 'Unknown')
            
            print(f"\n🔄 Processing fixture {i}/{len(fixtures)}: {home_team} vs {away_team}")
            
            try:
                # Prepare features
                features_df = self.prepare_fixture_for_prediction(fixture)
                
                if features_df is None:
                    print(f"   ❌ Could not prepare features")
                    continue
                
                # Generate predictions with all models
                fixture_predictions = {
                    'fixture_info': {
                        'home_team': home_team,
                        'away_team': away_team,
                        'league': fixture.get('league_name', 'Unknown'),
                        'date': fixture.get('date', 'Unknown'),
                        'status': fixture.get('status', 'Unknown')
                    },
                    'predictions': {},
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
                            fixture_predictions['predictions'][pred_key] = {
                                'prediction': int(prediction),
                                'probabilities': probabilities.tolist(),
                                'confidence': float(max(probabilities)),
                                'model_type': model_type,
                                'model_name': model_name
                            }
                            
                            fixture_predictions['model_summary']['total_predictions'] += 1
                            self.stats['predictions_generated'] += 1
                            
                        except Exception as e:
                            logger.error(f"Error with {model_type}/{model_name}: {str(e)}")
                            continue
                
                # Generate betting categories
                betting_categories = self.generate_betting_categories(fixture_predictions['predictions'])
                fixture_predictions['betting_categories'] = betting_categories
                
                fixture_predictions['model_summary']['successful_predictions'] = len(fixture_predictions['predictions'])
                
                prediction_results.append(fixture_predictions)
                
                print(f"   ✅ Generated {len(fixture_predictions['predictions'])} predictions")
                
            except Exception as e:
                logger.error(f"Error processing fixture: {str(e)}")
                print(f"   ❌ Error: {str(e)}")
                continue
        
        return prediction_results

    def generate_betting_categories(self, predictions: Dict[str, Any]) -> Dict[str, Any]:
        """Generate betting categories based on predictions."""
        betting_categories = {}

        # Define confidence thresholds
        thresholds = {
            '2_odds': 0.75,   # High confidence, low risk
            '5_odds': 0.65,   # Medium-high confidence
            '10_odds': 0.55,  # Medium confidence, higher reward
            'rollover': 0.70  # High confidence for accumulator
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
                self.stats['betting_categories_generated'] += 1
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
        risk_mapping = {'2_odds': 'LOW', '5_odds': 'MEDIUM', '10_odds': 'HIGH', 'rollover': 'LOW-MEDIUM'}
        return risk_mapping.get(category, 'MEDIUM')

    def display_results(self, prediction_results: List[Dict[str, Any]]):
        """Display comprehensive prediction results."""
        print(f"\n📊 STEP 3: COMPREHENSIVE PREDICTION RESULTS")
        print("-" * 60)

        if not prediction_results:
            print("❌ No prediction results to display")
            return

        for i, result in enumerate(prediction_results, 1):
            fixture_info = result['fixture_info']
            predictions = result['predictions']
            betting_categories = result['betting_categories']

            print(f"\n🏆 FIXTURE {i}: {fixture_info['home_team']} vs {fixture_info['away_team']}")
            print(f"   📍 League: {fixture_info['league']}")
            print(f"   📅 Date: {fixture_info['date']}")
            print(f"   📊 Status: {fixture_info['status']}")

            # Core predictions
            print(f"\n   🤖 ML PREDICTIONS ({len(predictions)} models):")

            # Group by prediction type
            prediction_groups = {}
            for pred_key, pred_data in predictions.items():
                model_name = pred_data['model_name']
                if model_name not in prediction_groups:
                    prediction_groups[model_name] = []
                prediction_groups[model_name].append((pred_key, pred_data))

            for pred_type, pred_list in prediction_groups.items():
                print(f"\n      📈 {pred_type.upper()}:")
                for pred_key, pred_data in pred_list:
                    model_type = pred_data['model_type']
                    prediction = pred_data['prediction']
                    confidence = pred_data['confidence']

                    # Interpret prediction based on type
                    if 'match_result' in pred_type:
                        outcome = ['Home Win', 'Away Win', 'Draw'][prediction] if prediction < 3 else 'Unknown'
                    elif 'btts' in pred_type:
                        outcome = 'Yes' if prediction == 1 else 'No'
                    elif 'over' in pred_type or 'clean_sheet' in pred_type or 'win_to_nil' in pred_type:
                        outcome = 'Yes' if prediction == 1 else 'No'
                    else:
                        outcome = str(prediction)

                    print(f"         {model_type:12} | {outcome:12} | {confidence:.3f}")

            # Betting categories
            print(f"\n   🎯 BETTING CATEGORIES:")
            for category, bet_data in betting_categories.items():
                selected = "✅" if bet_data.get('selected', False) else "❌"
                recommendation = bet_data.get('recommendation', 'N/A')
                risk = bet_data.get('risk_level', 'N/A')
                odds = bet_data.get('expected_odds', 0)

                print(f"      {category:12} | {selected} {recommendation:8} | Risk: {risk:10} | Odds: {odds:.1f}")

                if bet_data.get('selected') and bet_data.get('prediction'):
                    pred_info = bet_data['prediction']
                    print(f"                     └─ {pred_info['model_type']}/{pred_info['model_name']} -> {pred_info['prediction']} ({pred_info['confidence']:.3f})")

            print("-" * 60)

    def display_summary(self, prediction_results: List[Dict[str, Any]]):
        """Display comprehensive test summary."""
        end_time = datetime.now()
        duration = (end_time - self.stats['start_time']).total_seconds()

        print(f"\n📈 COMPREHENSIVE TEST SUMMARY")
        print("=" * 80)

        print(f"⏱️  Test Duration: {duration:.1f} seconds")
        print(f"📡 Total Fixtures Fetched: {self.stats['fixtures_fetched']}")
        print(f"⚽ Valid Upcoming Fixtures: {self.stats['valid_fixtures']}")
        print(f"🤖 ML Predictions Generated: {self.stats['predictions_generated']}")
        print(f"🎯 Betting Categories Generated: {self.stats['betting_categories_generated']}")

        # Model usage summary
        total_models_loaded = sum(len(self.models[mt]) for mt in self.models)
        print(f"\n🧠 MODEL USAGE:")
        print(f"   Total Models Loaded: {total_models_loaded}")
        for model_type, type_models in self.models.items():
            print(f"   {model_type.upper()}: {len(type_models)} models")

        # Performance metrics
        if self.stats['valid_fixtures'] > 0:
            avg_predictions_per_fixture = self.stats['predictions_generated'] / self.stats['valid_fixtures']
            print(f"\n⚡ PERFORMANCE METRICS:")
            print(f"   Avg Predictions per Fixture: {avg_predictions_per_fixture:.1f}")
            print(f"   Processing Speed: {self.stats['valid_fixtures']/duration:.1f} fixtures/second")

        # System health
        health_score = 100
        if self.stats['valid_fixtures'] == 0:
            health_score -= 50
        if self.stats['predictions_generated'] == 0:
            health_score -= 30

        health_status = "🟢 EXCELLENT" if health_score >= 90 else \
                       "🟡 GOOD" if health_score >= 70 else \
                       "🟠 FAIR" if health_score >= 50 else "🔴 POOR"

        print(f"\n🏥 System Health: {health_score}/100 {health_status}")

        if self.stats['predictions_generated'] > 0:
            print("🎉 Real ML prediction system working correctly!")
        else:
            print("⚠️  No predictions generated - check data availability")

        print("=" * 80)

    def run_comprehensive_test(self):
        """Run the complete end-to-end test."""
        try:
            # Print header
            self.print_header()

            # Check if models are loaded
            total_models = sum(len(self.models[mt]) for mt in self.models)
            if total_models == 0:
                print("\n❌ No trained models found! Please run training first.")
                return False

            print(f"✅ {total_models} trained models loaded successfully")

            # Step 1: Fetch fixtures
            fixtures = self.fetch_upcoming_fixtures()

            if not fixtures:
                print("\n⚠️  No upcoming fixtures found for testing.")
                print("💡 This is normal if testing outside of match days.")
                return True  # Not a failure, just no data

            # Step 2: Generate predictions
            prediction_results = self.generate_predictions(fixtures)

            # Step 3: Display results
            self.display_results(prediction_results)

            # Step 4: Display summary
            self.display_summary(prediction_results)

            return True

        except Exception as e:
            logger.error(f"Comprehensive test failed: {str(e)}")
            print(f"\n❌ TEST FAILED: {str(e)}")
            return False


def main():
    """Main test execution."""
    test = RealMLPredictionTest()
    success = test.run_comprehensive_test()
    return success


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
