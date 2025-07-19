#!/usr/bin/env python3
"""
Generate Predictions with Real Odds
Uses user's games with actual betting odds to create accurate predictions.
"""

import sys
import os
import json
from datetime import datetime, date

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.daily_predictions_service import DailyPredictionsService, DailyPrediction, DailyPredictionSummary
from api.endpoints.ml_predictions import RealMLPredictionService
from services.accumulator_builder import AccumulatorBuilder
from database import get_db

def create_fixtures_with_real_odds():
    """Create fixture data from user's games with real betting odds."""
    fixtures = [
        # UEFA Europa League
        {"fixture_id": 4001, "home_team": "FC Aktobe", "away_team": "Legia Warszawa", "league": "UEFA Europa League", "date": "2025-07-17T17:00:00", "status": "Not Started", "home_odds": 4.60, "draw_odds": 3.60, "away_odds": 1.70, "over_2_5_odds": 2.05, "under_2_5_odds": 1.73},
        {"fixture_id": 4002, "home_team": "Tampereen Ilves", "away_team": "Shakhtar D", "league": "UEFA Europa League", "date": "2025-07-17T17:00:00", "status": "Not Started", "home_odds": 5.73, "draw_odds": 5.00, "away_odds": 1.38, "over_3_odds": 1.78, "under_3_odds": 2.00},
        {"fixture_id": 4003, "home_team": "Hacken Gothenburg", "away_team": "Spartak Trnava", "league": "UEFA Europa League", "date": "2025-07-17T18:00:00", "status": "Not Started", "home_odds": 1.33, "draw_odds": 5.10, "away_odds": 7.09, "over_3_odds": 1.97, "under_3_odds": 1.81},
        {"fixture_id": 4004, "home_team": "CFR Cluj", "away_team": "Paksi FC", "league": "UEFA Europa League", "date": "2025-07-17T18:30:00", "status": "Not Started", "home_odds": 1.35, "draw_odds": 5.00, "away_odds": 6.85, "over_3_odds": 2.00, "under_3_odds": 1.79},
        {"fixture_id": 4005, "home_team": "FC Prishtina", "away_team": "FC Sheriff Tiraspol", "league": "UEFA Europa League", "date": "2025-07-17T19:00:00", "status": "Not Started", "home_odds": 2.78, "draw_odds": 3.40, "away_odds": 2.24, "over_2_5_odds": 1.73, "under_2_5_odds": 2.05},
        {"fixture_id": 4006, "home_team": "Hapoel Be'er Sheva FC", "away_team": "PFC Levski Sofia", "league": "UEFA Europa League", "date": "2025-07-17T19:00:00", "status": "Not Started", "home_odds": 1.90, "draw_odds": 3.25, "away_odds": 4.00, "over_2_odds": 1.73, "under_2_odds": 2.05},
        {"fixture_id": 4007, "home_team": "NK Celje", "away_team": "Sabah Masazir", "league": "UEFA Europa League", "date": "2025-07-17T19:00:00", "status": "Not Started", "home_odds": 1.67, "draw_odds": 4.00, "away_odds": 4.03, "over_3_odds": 2.10, "under_3_odds": 1.71},
        {"fixture_id": 4008, "home_team": "FK Partizan Belgrade", "away_team": "AEK Larnaca", "league": "UEFA Europa League", "date": "2025-07-17T20:00:00", "status": "Not Started", "home_odds": 3.35, "draw_odds": 3.10, "away_odds": 2.15, "over_2_odds": 1.70, "under_2_odds": 2.10},
        
        # UEFA Conference League
        {"fixture_id": 4009, "home_team": "BFC Daugavpils", "away_team": "Vllaznia Shkoder", "league": "UEFA Conference League", "date": "2025-07-17T16:00:00", "status": "Not Started", "home_odds": 3.52, "draw_odds": 3.40, "away_odds": 1.95, "over_2_5_odds": 2.15, "under_2_5_odds": 1.67},
        {"fixture_id": 4010, "home_team": "FC Dila Gori", "away_team": "Racing Union Luxembourg", "league": "UEFA Conference League", "date": "2025-07-17T17:00:00", "status": "Not Started", "home_odds": 1.45, "draw_odds": 4.50, "away_odds": 5.87, "over_2_5_odds": 1.81, "under_2_5_odds": 1.97},
        {"fixture_id": 4011, "home_team": "FC Hegelmann Kaunas", "away_team": "Saint Patrick's Athletic FC", "league": "UEFA Conference League", "date": "2025-07-17T17:00:00", "status": "Not Started", "home_odds": 2.77, "draw_odds": 3.40, "away_odds": 2.27, "over_2_5_odds": 2.05, "under_2_5_odds": 1.76},
        {"fixture_id": 4012, "home_team": "FC Ordabasy", "away_team": "FC Torpedo Kutaisi", "league": "UEFA Conference League", "date": "2025-07-17T17:00:00", "status": "Not Started", "home_odds": 1.67, "draw_odds": 4.00, "away_odds": 4.05, "over_2_5_odds": 1.70, "under_2_5_odds": 2.10},
        {"fixture_id": 4013, "home_team": "FC Pyunik Yerevan", "away_team": "SP Tre Fiori", "league": "UEFA Conference League", "date": "2025-07-17T17:00:00", "status": "Not Started", "home_odds": 1.04, "draw_odds": 12.50, "away_odds": 45.29, "over_3_5_odds": 2.00, "under_3_5_odds": 1.79},
        {"fixture_id": 4014, "home_team": "Vikingur Reykjavik", "away_team": "KF Malisheva", "league": "UEFA Conference League", "date": "2025-07-17T19:45:00", "status": "Not Started", "home_odds": 1.20, "draw_odds": 6.30, "away_odds": 11.43, "over_3_odds": 1.97, "under_3_odds": 1.81},
        {"fixture_id": 4015, "home_team": "SP La Fiorita", "away_team": "FK Vardar Skopje", "league": "UEFA Conference League", "date": "2025-07-17T20:00:00", "status": "Not Started", "home_odds": 6.71, "draw_odds": 4.20, "away_odds": 1.44, "over_2_5_odds": 1.91, "under_2_5_odds": 1.86},
        
        # Women's Euro
        {"fixture_id": 4016, "home_team": "Sweden", "away_team": "England", "league": "UEFA Euro Women", "date": "2025-07-17T20:00:00", "status": "Not Started", "home_odds": 3.21, "draw_odds": 3.40, "away_odds": 2.08, "over_2_5_odds": 1.94, "under_2_5_odds": 1.83},
        
        # Brazilian Leagues
        {"fixture_id": 4017, "home_team": "Fluminense FC RJ", "away_team": "Cruzeiro EC MG", "league": "Brasileiro Serie A", "date": "2025-07-17T23:30:00", "status": "Not Started", "home_odds": 2.21, "draw_odds": 3.00, "away_odds": 3.58, "over_2_odds": 2.10, "under_2_odds": 1.72},
        {"fixture_id": 4018, "home_team": "Operario Ferroviario EC PR", "away_team": "CR Brasil AL", "league": "Brasileiro Serie B", "date": "2025-07-17T23:30:00", "status": "Not Started", "home_odds": 1.95, "draw_odds": 3.10, "away_odds": 4.21, "over_2_odds": 1.87, "under_2_odds": 1.91},
        
        # CONMEBOL Sudamericana
        {"fixture_id": 4019, "home_team": "Universidad de Chile", "away_team": "Club Guarani Asuncion", "league": "CONMEBOL Sudamericana", "date": "2025-07-17T23:00:00", "status": "Not Started", "home_odds": 1.39, "draw_odds": 4.90, "away_odds": 6.63, "over_3_odds": 2.05, "under_3_odds": 1.73},
        
        # Iceland
        {"fixture_id": 4020, "home_team": "Afturelding", "away_team": "Fram Reykjavik", "league": "Besta deild", "date": "2025-07-17T20:15:00", "status": "Not Started", "home_odds": 2.54, "draw_odds": 3.60, "away_odds": 2.23, "over_3_odds": 1.99, "under_3_odds": 1.79},
    ]
    
    return fixtures

def analyze_model_performance(predictions):
    """Analyze which models perform best for selection."""
    model_stats = {}
    
    for prediction in predictions:
        ml_predictions = prediction.get('ml_predictions', {})
        
        for pred_key, pred_data in ml_predictions.items():
            model_type = pred_data.get('model_type', 'unknown')
            model_name = pred_data.get('model_name', pred_key)
            confidence = pred_data.get('confidence', 0)
            
            if model_type not in model_stats:
                model_stats[model_type] = {
                    'count': 0,
                    'total_confidence': 0,
                    'high_confidence_count': 0,
                    'predictions': []
                }
            
            model_stats[model_type]['count'] += 1
            model_stats[model_type]['total_confidence'] += confidence
            
            if confidence >= 0.80:
                model_stats[model_type]['high_confidence_count'] += 1
            
            model_stats[model_type]['predictions'].append({
                'model_name': model_name,
                'confidence': confidence,
                'prediction': pred_data.get('prediction')
            })
    
    return model_stats

def main():
    """Generate predictions with real odds and analyze model performance."""
    print("🎯 GENERATING PREDICTIONS WITH REAL ODDS")
    print("=" * 60)
    print(f"📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("🎮 Processing games with actual betting odds")
    print("=" * 60)
    
    try:
        # Get today's date
        today = datetime.now().date()
        
        # Get database session
        db = next(get_db())
        
        # Clear existing predictions for today
        print("🧹 Clearing existing predictions for today...")
        db.query(DailyPrediction).filter(
            DailyPrediction.prediction_date == today
        ).delete()
        
        db.query(DailyPredictionSummary).filter(
            DailyPredictionSummary.prediction_date == today
        ).delete()
        
        db.commit()
        
        # Get fixtures with real odds
        fixtures = create_fixtures_with_real_odds()
        print(f"\n📊 Processing {len(fixtures)} fixtures with real odds...")
        
        # Initialize services
        ml_service = RealMLPredictionService()
        accumulator_builder = AccumulatorBuilder()
        
        # Generate predictions for all fixtures
        all_predictions = []
        successful_predictions = 0
        
        for i, fixture in enumerate(fixtures, 1):
            try:
                print(f"{i}. {fixture['home_team']} vs {fixture['away_team']} - ", end="")
                
                # Generate ML prediction
                prediction_result = ml_service.generate_predictions_for_fixture(fixture)
                
                if 'error' not in prediction_result:
                    all_predictions.append(prediction_result)
                    successful_predictions += 1
                    print("✅")
                else:
                    print(f"❌ {prediction_result.get('error', 'Unknown')}")
                    
            except Exception as e:
                print(f"❌ Error: {str(e)}")
                continue
        
        print(f"\n📈 Generated {successful_predictions}/{len(fixtures)} predictions")
        
        if successful_predictions == 0:
            print("❌ No predictions generated")
            return False
        
        # Analyze model performance
        print(f"\n🤖 ANALYZING MODEL PERFORMANCE:")
        print("-" * 40)
        model_stats = analyze_model_performance(all_predictions)
        
        for model_type, stats in model_stats.items():
            avg_confidence = stats['total_confidence'] / stats['count']
            high_conf_rate = (stats['high_confidence_count'] / stats['count']) * 100
            
            print(f"{model_type.upper()}:")
            print(f"   Total Predictions: {stats['count']}")
            print(f"   Avg Confidence: {avg_confidence:.1%}")
            print(f"   High Confidence (80%+): {stats['high_confidence_count']} ({high_conf_rate:.1f}%)")
            
            # Show top 3 predictions
            top_predictions = sorted(stats['predictions'], key=lambda x: x['confidence'], reverse=True)[:3]
            print(f"   Top Predictions:")
            for j, pred in enumerate(top_predictions, 1):
                print(f"      {j}. {pred['model_name']}: {pred['confidence']:.1%}")
            print()
        
        # Build accumulators
        print("🎰 Building accumulators...")
        accumulator_result = accumulator_builder.build_accumulators(all_predictions)
        accumulators = accumulator_result.get('accumulators', {})
        
        # Create summary record
        summary = DailyPredictionSummary(
            prediction_date=today,
            total_fixtures=len(fixtures),
            upcoming_fixtures=len(fixtures),
            predictions_generated=successful_predictions,
            models_used=sum(stats['count'] for stats in model_stats.values()),
            betting_2_odds_count=1 if accumulators.get('2_odds', {}).get('selected', False) else 0,
            betting_5_odds_count=1 if accumulators.get('5_odds', {}).get('selected', False) else 0,
            betting_10_odds_count=1 if accumulators.get('10_odds', {}).get('selected', False) else 0,
            betting_rollover_count=1 if accumulators.get('rollover', {}).get('selected', False) else 0,
            generation_status="completed",
            generation_time=datetime.utcnow()
        )
        
        db.add(summary)
        
        # Store predictions with accumulator data
        for prediction_result in all_predictions:
            try:
                fixture_info = prediction_result['fixture_info']
                ml_predictions = prediction_result['ml_predictions']
                
                # Calculate highest confidence
                highest_confidence = 0.0
                for pred_data in ml_predictions.values():
                    confidence = pred_data.get('confidence', 0.0)
                    if confidence > highest_confidence:
                        highest_confidence = confidence
                
                # Create database record
                league_name = fixture_info.get('league') or fixture_info.get('league_name') or 'Unknown League'
                
                db_prediction = DailyPrediction(
                    prediction_date=today,
                    fixture_id=fixture_info.get('fixture_id', 0),
                    home_team=fixture_info.get('home_team', 'Unknown'),
                    away_team=fixture_info.get('away_team', 'Unknown'),
                    league_name=league_name,
                    fixture_date=datetime.fromisoformat(fixture_info.get('date', datetime.now().isoformat())),
                    fixture_status=fixture_info.get('status', 'Not Started'),
                    ml_predictions=json.dumps(ml_predictions),
                    betting_2_odds=json.dumps(accumulators.get('2_odds', {})),
                    betting_5_odds=json.dumps(accumulators.get('5_odds', {})),
                    betting_10_odds=json.dumps(accumulators.get('10_odds', {})),
                    betting_rollover=json.dumps(accumulators.get('rollover', {})),
                    total_models_used=len(ml_predictions),
                    highest_confidence=highest_confidence
                )
                
                db.add(db_prediction)
                
            except Exception as e:
                print(f"Error storing prediction: {str(e)}")
                continue
        
        # Commit all changes
        db.commit()
        db.close()
        
        print(f"\n✅ SUCCESS!")
        print(f"📊 Stored {successful_predictions} predictions in database")
        print(f"🎰 Accumulator categories:")
        for category, accumulator in accumulators.items():
            if accumulator.get('selected', False):
                print(f"   ✅ {category}: {accumulator['total_odds']:.2f}x odds ({accumulator['num_games']} games)")
            else:
                print(f"   ❌ {category}: Not selected")
        
        print(f"\n🌐 Frontend endpoints now have data with REAL ODDS:")
        print(f"   GET /api/accumulators/today")
        print(f"   GET /api/accumulators/2-odds")
        print(f"   GET /api/accumulators/5-odds")
        print(f"   GET /api/accumulators/10-odds")
        print(f"   GET /api/accumulators/rollover")
        
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        return False

if __name__ == "__main__":
    success = main()
    print(f"\n" + "=" * 60)
    if success:
        print("🎉 PREDICTIONS WITH REAL ODDS GENERATED!")
        print("💡 Model performance analysis complete")
    else:
        print("❌ FAILED TO GENERATE PREDICTIONS")
    print("=" * 60)
    sys.exit(0 if success else 1)
