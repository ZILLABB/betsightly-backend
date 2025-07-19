#!/usr/bin/env python3
"""
Generate Predictions for User-Provided Games
Uses trained ML models to predict outcomes and build accumulators.
"""

import sys
import os
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from api.endpoints.ml_predictions import RealMLPredictionService
from services.accumulator_builder import AccumulatorBuilder, format_accumulator_for_display

def create_user_fixtures():
    """Create fixture data from user's game list."""
    fixtures = [
        # UEFA Conference League Qualifiers
        {"fixture_id": 1001, "home_team": "Aktobe", "away_team": "Legia", "league": "UEFA Conference League", "date": "2025-07-17T18:00:00", "status": "Not Started"},
        {"fixture_id": 1002, "home_team": "Ilves", "away_team": "Shakhtar", "league": "UEFA Conference League", "date": "2025-07-17T18:30:00", "status": "Not Started"},
        {"fixture_id": 1003, "home_team": "Häcken", "away_team": "FC Spartak Trnava", "league": "UEFA Conference League", "date": "2025-07-17T19:00:00", "status": "Not Started"},
        {"fixture_id": 1004, "home_team": "CFR Cluj", "away_team": "Paks", "league": "UEFA Conference League", "date": "2025-07-17T19:00:00", "status": "Not Started"},
        {"fixture_id": 1005, "home_team": "Prishtina", "away_team": "Sheriff", "league": "UEFA Conference League", "date": "2025-07-17T19:30:00", "status": "Not Started"},
        {"fixture_id": 1006, "home_team": "H. Be'er Sheva", "away_team": "Levski Sofia", "league": "UEFA Conference League", "date": "2025-07-17T19:45:00", "status": "Not Started"},
        {"fixture_id": 1007, "home_team": "Celje", "away_team": "Sabah FK", "league": "UEFA Conference League", "date": "2025-07-17T19:45:00", "status": "Not Started"},
        {"fixture_id": 1008, "home_team": "Partizan", "away_team": "AEK", "league": "UEFA Conference League", "date": "2025-07-17T20:00:00", "status": "Not Started"},
        
        # Additional European Qualifiers
        {"fixture_id": 1009, "home_team": "Daugavpils", "away_team": "Vllaznia", "league": "UEFA Conference League", "date": "2025-07-17T18:00:00", "status": "Not Started"},
        {"fixture_id": 1010, "home_team": "Dila", "away_team": "Racing", "league": "UEFA Conference League", "date": "2025-07-17T18:30:00", "status": "Not Started"},
        {"fixture_id": 1011, "home_team": "Hegelmann", "away_team": "St. Patrick's", "league": "UEFA Conference League", "date": "2025-07-17T19:00:00", "status": "Not Started"},
        {"fixture_id": 1012, "home_team": "Ordabasy", "away_team": "Torpedo Kutaisi", "league": "UEFA Conference League", "date": "2025-07-17T19:00:00", "status": "Not Started"},
        {"fixture_id": 1013, "home_team": "Santa Coloma", "away_team": "Borac", "league": "UEFA Conference League", "date": "2025-07-17T19:30:00", "status": "Not Started"},
        {"fixture_id": 1014, "home_team": "Rabotnički", "away_team": "Torpedo-BelAZ", "league": "UEFA Conference League", "date": "2025-07-17T19:45:00", "status": "Not Started"},
        {"fixture_id": 1015, "home_team": "Flora", "away_team": "Valur", "league": "UEFA Conference League", "date": "2025-07-17T19:45:00", "status": "Not Started"},
        {"fixture_id": 1016, "home_team": "HJK", "away_team": "NSÍ Runavík", "league": "UEFA Conference League", "date": "2025-07-17T20:00:00", "status": "Not Started"},
        
        # More European Games
        {"fixture_id": 1017, "home_team": "Pyunik", "away_team": "Tre Fiori", "league": "UEFA Conference League", "date": "2025-07-17T18:00:00", "status": "Not Started"},
        {"fixture_id": 1018, "home_team": "Paide", "away_team": "FC Bruno's Magpies", "league": "UEFA Conference League", "date": "2025-07-17T18:30:00", "status": "Not Started"},
        {"fixture_id": 1019, "home_team": "Dudelange", "away_team": "AC Escaldes", "league": "UEFA Conference League", "date": "2025-07-17T19:00:00", "status": "Not Started"},
        {"fixture_id": 1020, "home_team": "Petrocub", "away_team": "Birkirkara", "league": "UEFA Conference League", "date": "2025-07-17T19:00:00", "status": "Not Started"},
        {"fixture_id": 1021, "home_team": "Sileks", "away_team": "FK Dečić", "league": "UEFA Conference League", "date": "2025-07-17T19:30:00", "status": "Not Started"},
        {"fixture_id": 1022, "home_team": "Haverfordwest", "away_team": "Floriana", "league": "UEFA Conference League", "date": "2025-07-17T19:45:00", "status": "Not Started"},
        
        # Additional Matches
        {"fixture_id": 1023, "home_team": "Penybont", "away_team": "FK Kauno Žalgiris", "league": "UEFA Conference League", "date": "2025-07-17T18:00:00", "status": "Not Started"},
        {"fixture_id": 1024, "home_team": "FC Koper", "away_team": "FK Željezničar", "league": "UEFA Conference League", "date": "2025-07-17T18:30:00", "status": "Not Started"},
        {"fixture_id": 1025, "home_team": "FK Partizani", "away_team": "Nõmme Kalju", "league": "UEFA Conference League", "date": "2025-07-17T19:00:00", "status": "Not Started"},
        {"fixture_id": 1026, "home_team": "Neman Grodno", "away_team": "Urartu", "league": "UEFA Conference League", "date": "2025-07-17T19:00:00", "status": "Not Started"},
        {"fixture_id": 1027, "home_team": "Dynamo Brest", "away_team": "FK Sutjeska Nikšić", "league": "UEFA Conference League", "date": "2025-07-17T19:30:00", "status": "Not Started"},
        {"fixture_id": 1028, "home_team": "Cliftonville FC", "away_team": "St Joseph's FC", "league": "UEFA Conference League", "date": "2025-07-17T19:45:00", "status": "Not Started"},
        {"fixture_id": 1029, "home_team": "Klaksvíkar Ítróttarfelag", "away_team": "SJK", "league": "UEFA Conference League", "date": "2025-07-17T19:45:00", "status": "Not Started"},
        {"fixture_id": 1030, "home_team": "Víkingur Reykjavík", "away_team": "FC Malisheva", "league": "UEFA Conference League", "date": "2025-07-17T20:00:00", "status": "Not Started"},
        {"fixture_id": 1031, "home_team": "La Fiorita", "away_team": "FK Vardar Skopje", "league": "UEFA Conference League", "date": "2025-07-17T20:00:00", "status": "Not Started"},
        
        # Major Matches
        {"fixture_id": 1032, "home_team": "Sweden", "away_team": "England", "league": "Women's Euro", "date": "2025-07-17T20:00:00", "status": "Not Started"},
        {"fixture_id": 1033, "home_team": "Universidad de Chile", "away_team": "Guaraní", "league": "CONMEBOL Sudamericana", "date": "2025-07-17T23:00:00", "status": "Not Started"},
        {"fixture_id": 1034, "home_team": "Fluminense", "away_team": "Cruzeiro", "league": "Brasileirão", "date": "2025-07-17T23:30:00", "status": "Not Started"},
        {"fixture_id": 1035, "home_team": "Operário-PR", "away_team": "CRB", "league": "Brasileirão Série B", "date": "2025-07-17T23:30:00", "status": "Not Started"},
        
        # Friendlies
        {"fixture_id": 1036, "home_team": "Darmstadt 98", "away_team": "FC St. Gallen 1879", "league": "Club Friendly", "date": "2025-07-17T14:00:00", "status": "Not Started"},
        {"fixture_id": 1037, "home_team": "Başakşehir FK", "away_team": "Fortuna Düsseldorf", "league": "Club Friendly", "date": "2025-07-17T15:00:00", "status": "Not Started"},
        {"fixture_id": 1038, "home_team": "Beşiktaş", "away_team": "FC Petržalka 1898", "league": "Club Friendly", "date": "2025-07-17T17:30:00", "status": "Not Started"},
        {"fixture_id": 1039, "home_team": "Fenerbahçe", "away_team": "Portimonense SAD", "league": "Club Friendly", "date": "2025-07-17T20:00:00", "status": "Not Started"},
    ]
    
    return fixtures

def main():
    """Generate predictions for user's games."""
    print("🎯 GENERATING PREDICTIONS FOR USER GAMES")
    print("=" * 60)
    print(f"📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("🎮 Processing user-provided fixtures")
    print("=" * 60)
    
    try:
        # Get user fixtures
        fixtures = create_user_fixtures()
        print(f"\n📊 PROCESSING {len(fixtures)} FIXTURES:")
        
        # Initialize ML service
        ml_service = RealMLPredictionService()
        
        # Generate predictions for each fixture
        all_predictions = []
        successful_predictions = 0
        
        for i, fixture in enumerate(fixtures, 1):
            try:
                print(f"\n{i}. {fixture['home_team']} vs {fixture['away_team']} ({fixture['league']})")
                
                # Generate ML prediction
                prediction_result = ml_service.generate_predictions_for_fixture(fixture)
                
                if 'error' not in prediction_result:
                    all_predictions.append(prediction_result)
                    successful_predictions += 1
                    
                    # Show top prediction
                    ml_preds = prediction_result.get('ml_predictions', {})
                    if ml_preds:
                        best_pred = max(ml_preds.items(), key=lambda x: x[1].get('confidence', 0))
                        pred_name, pred_data = best_pred
                        confidence = pred_data.get('confidence', 0)
                        print(f"   🎯 Best: {pred_name} ({confidence:.1%} confidence)")
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
        print("🎉 PREDICTIONS COMPLETED SUCCESSFULLY!")
        print("💡 These are the best accumulator combinations from your games")
    else:
        print("❌ PREDICTION GENERATION FAILED")
    print("=" * 60)
    sys.exit(0 if success else 1)
