#!/usr/bin/env python3
"""
Generate Predictions for Games with Odds
Uses fixed ML models to predict outcomes and build accumulators.
"""

import sys
import os
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from api.endpoints.ml_predictions import RealMLPredictionService
from services.accumulator_builder import AccumulatorBuilder, format_accumulator_for_display

def create_fixtures_with_odds():
    """Create fixture data from user's game list with odds."""
    fixtures = [
        # Games with odds from user
        {"fixture_id": 2001, "home_team": "FK Partizani", "away_team": "Nõmme Kalju", "league": "UEFA Conference League", "date": "2025-07-17T19:00:00", "status": "Not Started", "home_odds": 1.67, "draw_odds": 3.50, "away_odds": 5.00},
        {"fixture_id": 2002, "home_team": "Neman Grodno", "away_team": "Urartu", "league": "UEFA Conference League", "date": "2025-07-17T19:00:00", "status": "Not Started", "home_odds": 2.05, "draw_odds": 3.50, "away_odds": 3.10},
        {"fixture_id": 2003, "home_team": "Dynamo Brest", "away_team": "FK Sutjeska Nikšić", "league": "UEFA Conference League", "date": "2025-07-17T19:30:00", "status": "Not Started", "home_odds": 1.85, "draw_odds": 3.20, "away_odds": 4.20},
        {"fixture_id": 2004, "home_team": "Cliftonville FC", "away_team": "St Joseph's FC", "league": "UEFA Conference League", "date": "2025-07-17T19:45:00", "status": "Not Started", "home_odds": 2.15, "draw_odds": 3.20, "away_odds": 3.20},
        {"fixture_id": 2005, "home_team": "Klaksvíkar Ítróttarfelag", "away_team": "SJK", "league": "UEFA Conference League", "date": "2025-07-17T19:45:00", "status": "Not Started", "home_odds": 1.60, "draw_odds": 4.20, "away_odds": 4.20},
        {"fixture_id": 2006, "home_team": "Víkingur Reykjavík", "away_team": "FC Malisheva", "league": "UEFA Conference League", "date": "2025-07-17T19:45:00", "status": "Not Started", "home_odds": 1.22, "draw_odds": 6.00, "away_odds": 9.50},
        {"fixture_id": 2007, "home_team": "La Fiorita", "away_team": "FK Vardar Skopje", "league": "UEFA Conference League", "date": "2025-07-17T20:00:00", "status": "Not Started", "home_odds": 6.50, "draw_odds": 3.75, "away_odds": 1.44},
        {"fixture_id": 2008, "home_team": "Sweden", "away_team": "England", "league": "Women's Euro", "date": "2025-07-17T20:00:00", "status": "Not Started", "home_odds": 3.50, "draw_odds": 3.30, "away_odds": 2.15},
        {"fixture_id": 2009, "home_team": "Universidad de Chile", "away_team": "Guaraní", "league": "CONMEBOL Sudamericana", "date": "2025-07-17T23:00:00", "status": "Not Started", "home_odds": 1.42, "draw_odds": 4.75, "away_odds": 7.00},
        {"fixture_id": 2010, "home_team": "Fluminense", "away_team": "Cruzeiro", "league": "Brasileirão", "date": "2025-07-17T23:30:00", "status": "Not Started", "home_odds": 2.38, "draw_odds": 3.00, "away_odds": 3.30},
        {"fixture_id": 2011, "home_team": "Operário-PR", "away_team": "CRB", "league": "Brasileirão Série B", "date": "2025-07-17T23:30:00", "status": "Not Started", "home_odds": 1.91, "draw_odds": 3.00, "away_odds": 4.75},
        {"fixture_id": 2012, "home_team": "CD Real Tomayapo", "away_team": "CD Totora Real Oruro", "league": "Copa Division Profesional", "date": "2025-07-17T22:30:00", "status": "Not Started", "home_odds": 1.67, "draw_odds": 3.60, "away_odds": 4.20},
        {"fixture_id": 2013, "home_team": "Afturelding", "away_team": "Fram Reykjavík", "league": "Efsta deild", "date": "2025-07-17T20:15:00", "status": "Not Started", "home_odds": 2.55, "draw_odds": 3.40, "away_odds": 2.45},
        {"fixture_id": 2014, "home_team": "Darmstadt 98", "away_team": "FC St. Gallen 1879", "league": "Club Friendly", "date": "2025-07-17T14:00:00", "status": "Not Started", "home_odds": 2.75, "draw_odds": 3.70, "away_odds": 2.10},
        {"fixture_id": 2015, "home_team": "Hapoel Haifa", "away_team": "AE Larisa", "league": "Club Friendly", "date": "2025-07-17T16:30:00", "status": "Not Started", "home_odds": 2.50, "draw_odds": 3.20, "away_odds": 2.50},
        {"fixture_id": 2016, "home_team": "Beşiktaş", "away_team": "FC Petržalka 1898", "league": "Club Friendly", "date": "2025-07-17T17:30:00", "status": "Not Started", "home_odds": 1.40, "draw_odds": 4.00, "away_odds": 6.50},
        {"fixture_id": 2017, "home_team": "Aris Thessaloniki", "away_team": "Anorthosis Famagusta", "league": "Club Friendly", "date": "2025-07-17T18:00:00", "status": "Not Started", "home_odds": 1.50, "draw_odds": 3.50, "away_odds": 6.00},
        {"fixture_id": 2018, "home_team": "Orlando Pirates", "away_team": "Las Palmas", "league": "Club Friendly", "date": "2025-07-17T18:00:00", "status": "Not Started", "home_odds": 3.00, "draw_odds": 3.60, "away_odds": 2.00},
        
        # Additional games without specific odds (using defaults)
        {"fixture_id": 2019, "home_team": "Aktobe", "away_team": "Legia", "league": "UEFA Conference League", "date": "2025-07-17T18:00:00", "status": "Not Started", "home_odds": 3.20, "draw_odds": 3.40, "away_odds": 2.10},
        {"fixture_id": 2020, "home_team": "Ilves", "away_team": "Shakhtar", "league": "UEFA Conference League", "date": "2025-07-17T18:30:00", "status": "Not Started", "home_odds": 4.50, "draw_odds": 3.60, "away_odds": 1.70},
        {"fixture_id": 2021, "home_team": "Häcken", "away_team": "FC Spartak Trnava", "league": "UEFA Conference League", "date": "2025-07-17T19:00:00", "status": "Not Started", "home_odds": 1.80, "draw_odds": 3.50, "away_odds": 4.00},
        {"fixture_id": 2022, "home_team": "CFR Cluj", "away_team": "Paks", "league": "UEFA Conference League", "date": "2025-07-17T19:00:00", "status": "Not Started", "home_odds": 2.20, "draw_odds": 3.20, "away_odds": 3.10},
        {"fixture_id": 2023, "home_team": "Prishtina", "away_team": "Sheriff", "league": "UEFA Conference League", "date": "2025-07-17T19:30:00", "status": "Not Started", "home_odds": 2.80, "draw_odds": 3.30, "away_odds": 2.40},
        {"fixture_id": 2024, "home_team": "H. Be'er Sheva", "away_team": "Levski Sofia", "league": "UEFA Conference League", "date": "2025-07-17T19:45:00", "status": "Not Started", "home_odds": 2.10, "draw_odds": 3.40, "away_odds": 3.20},
        {"fixture_id": 2025, "home_team": "Celje", "away_team": "Sabah FK", "league": "UEFA Conference League", "date": "2025-07-17T19:45:00", "status": "Not Started", "home_odds": 1.90, "draw_odds": 3.50, "away_odds": 3.80},
        {"fixture_id": 2026, "home_team": "Partizan", "away_team": "AEK", "league": "UEFA Conference League", "date": "2025-07-17T20:00:00", "status": "Not Started", "home_odds": 2.60, "draw_odds": 3.20, "away_odds": 2.70},
    ]
    
    return fixtures

def main():
    """Generate predictions for games with odds."""
    print("🎯 GENERATING PREDICTIONS WITH FIXED MODELS")
    print("=" * 60)
    print(f"📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("🔧 Using fixed feature preparation with odds")
    print("=" * 60)
    
    try:
        # Get fixtures with odds
        fixtures = create_fixtures_with_odds()
        print(f"\n📊 PROCESSING {len(fixtures)} FIXTURES WITH ODDS:")
        
        # Initialize ML service
        ml_service = RealMLPredictionService()
        
        # Generate predictions for each fixture
        all_predictions = []
        successful_predictions = 0
        model_success_count = {}
        
        for i, fixture in enumerate(fixtures, 1):
            try:
                print(f"\n{i}. {fixture['home_team']} vs {fixture['away_team']} ({fixture['league']})")
                print(f"   Odds: {fixture['home_odds']} | {fixture['draw_odds']} | {fixture['away_odds']}")
                
                # Generate ML prediction
                prediction_result = ml_service.generate_predictions_for_fixture(fixture)
                
                if 'error' not in prediction_result:
                    all_predictions.append(prediction_result)
                    successful_predictions += 1
                    
                    # Count model successes
                    ml_preds = prediction_result.get('ml_predictions', {})
                    print(f"   🎯 Models used: {len(ml_preds)}")
                    
                    # Show top 3 predictions
                    if ml_preds:
                        sorted_preds = sorted(ml_preds.items(), key=lambda x: x[1].get('confidence', 0), reverse=True)
                        for j, (pred_name, pred_data) in enumerate(sorted_preds[:3], 1):
                            confidence = pred_data.get('confidence', 0)
                            prediction = pred_data.get('prediction', 'Unknown')
                            print(f"   {j}. {pred_name}: {prediction} ({confidence:.1%} confidence)")
                            
                            # Count model types
                            model_type = pred_data.get('model_type', 'unknown')
                            model_success_count[model_type] = model_success_count.get(model_type, 0) + 1
                    else:
                        print(f"   ⚠️  No predictions generated")
                else:
                    print(f"   ❌ Error: {prediction_result.get('error', 'Unknown')}")
                    
            except Exception as e:
                print(f"   ❌ Error processing: {str(e)}")
                continue
        
        print(f"\n📈 PREDICTION SUMMARY:")
        print(f"✅ Successful predictions: {successful_predictions}/{len(fixtures)}")
        print(f"📊 Success rate: {(successful_predictions/len(fixtures)*100):.1f}%")
        print(f"\n🤖 MODEL TYPE USAGE:")
        for model_type, count in model_success_count.items():
            print(f"   {model_type}: {count} predictions")
        
        if successful_predictions == 0:
            print("❌ No predictions generated. Cannot build accumulators.")
            return False
        
        # Build accumulators
        print(f"\n🎰 BUILDING ACCUMULATORS...")
        print("-" * 40)
        
        accumulator_builder = AccumulatorBuilder()
        accumulator_result = accumulator_builder.build_accumulators(all_predictions)
        
        if accumulator_result['status'] == 'success':
            accumulators = accumulator_result['accumulators']
            summary = accumulator_result['summary']
            
            print(f"✅ SUCCESS!")
            print(f"📊 Games analyzed: {accumulator_result['total_games_analyzed']}")
            print(f"🎯 High-confidence selections: {accumulator_result['high_confidence_selections']}")
            print(f"📈 Success rate: {summary['success_rate']}")
            
            print(f"\n🎰 ACCUMULATOR RESULTS:")
            print("=" * 60)
            
            for category, accumulator in accumulators.items():
                print(f"\n{category.upper()} ACCUMULATOR:")
                print("-" * 30)
                
                if accumulator.get('selected', False):
                    print(f"✅ SELECTED")
                    print(f"🎯 Total Odds: {accumulator['total_odds']}x")
                    print(f"🎮 Games: {accumulator['num_games']}")
                    print(f"📊 Avg Confidence: {accumulator['average_confidence']:.1%}")
                    print(f"⚠️  Risk Level: {accumulator['risk_level']}")
                    print(f"💡 Recommendation: {accumulator['recommendation']}")
                    
                    print(f"\n📋 GAMES IN THIS ACCUMULATOR:")
                    for j, game in enumerate(accumulator['games'], 1):
                        print(f"   {j}. {game['home_team']} vs {game['away_team']}")
                        print(f"      Prediction: {game['prediction_type']} = {game['prediction_value']}")
                        print(f"      Confidence: {game['confidence']:.1%}")
                        print(f"      Est. Odds: {game['estimated_odds']:.1f}x")
                    
                    # Show calculation
                    individual_odds = [game['estimated_odds'] for game in accumulator['games']]
                    calculation = " × ".join(f"{odds:.1f}" for odds in individual_odds)
                    print(f"\n🧮 CALCULATION: {calculation} = {accumulator['total_odds']:.2f}x")
                    
                else:
                    print(f"❌ NOT SELECTED")
                    print(f"💭 Reason: {accumulator.get('reason', 'Unknown')}")
                    print(f"🎯 Target: {accumulator.get('target_range', 'Unknown')} odds")
            
            print(f"\n📈 FINAL SUMMARY:")
            print(f"🎯 Categories with accumulators: {summary['categories_with_accumulators']}/{summary['total_categories']}")
            print(f"🎮 Total games used: {summary['total_games_in_accumulators']}")
            print(f"📊 Success rate: {summary['success_rate']}")
            
            return True
            
        else:
            print(f"❌ ERROR: {accumulator_result.get('message', 'Unknown error')}")
            return False
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        return False

if __name__ == "__main__":
    success = main()
    print(f"\n" + "=" * 60)
    if success:
        print("🎉 FIXED MODELS WORKING SUCCESSFULLY!")
        print("💡 All model types should now be contributing to predictions")
    else:
        print("❌ MODEL FIXES NEED MORE WORK")
    print("=" * 60)
    sys.exit(0 if success else 1)
