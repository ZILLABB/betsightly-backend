#!/usr/bin/env python3
"""
Test Accumulator System
Demonstrates how games are combined to create target odds.
"""

import sys
import os
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.accumulator_builder import AccumulatorBuilder, format_accumulator_for_display

def create_sample_predictions():
    """Create sample predictions to test accumulator building."""
    return [
        {
            'fixture_info': {
                'fixture_id': 1,
                'home_team': 'Man City',
                'away_team': 'Arsenal',
                'league': 'Premier League',
                'date': '2025-07-17T15:00:00',
                'status': 'Not Started'
            },
            'ml_predictions': {
                'xgboost_clean_sheet_away': {
                    'prediction': 0,
                    'confidence': 0.944,
                    'model_type': 'xgboost',
                    'model_name': 'clean_sheet_away'
                },
                'lightgbm_btts': {
                    'prediction': 1,
                    'confidence': 0.856,
                    'model_type': 'lightgbm',
                    'model_name': 'btts'
                }
            }
        },
        {
            'fixture_info': {
                'fixture_id': 2,
                'home_team': 'Liverpool',
                'away_team': 'Chelsea',
                'league': 'Premier League',
                'date': '2025-07-17T17:30:00',
                'status': 'Not Started'
            },
            'ml_predictions': {
                'xgboost_over_2_5': {
                    'prediction': 1,
                    'confidence': 0.823,
                    'model_type': 'xgboost',
                    'model_name': 'over_2_5'
                },
                'random_forest_match_result': {
                    'prediction': 0,
                    'confidence': 0.789,
                    'model_type': 'random_forest',
                    'model_name': 'match_result'
                }
            }
        },
        {
            'fixture_info': {
                'fixture_id': 3,
                'home_team': 'Barcelona',
                'away_team': 'Real Madrid',
                'league': 'La Liga',
                'date': '2025-07-17T20:00:00',
                'status': 'Not Started'
            },
            'ml_predictions': {
                'neural_network_btts': {
                    'prediction': 1,
                    'confidence': 0.912,
                    'model_type': 'neural_network',
                    'model_name': 'btts'
                },
                'xgboost_win_to_nil_home': {
                    'prediction': 0,
                    'confidence': 0.867,
                    'model_type': 'xgboost',
                    'model_name': 'win_to_nil_home'
                }
            }
        },
        {
            'fixture_info': {
                'fixture_id': 4,
                'home_team': 'Bayern Munich',
                'away_team': 'Dortmund',
                'league': 'Bundesliga',
                'date': '2025-07-17T18:30:00',
                'status': 'Not Started'
            },
            'ml_predictions': {
                'lightgbm_clean_sheet_home': {
                    'prediction': 1,
                    'confidence': 0.798,
                    'model_type': 'lightgbm',
                    'model_name': 'clean_sheet_home'
                }
            }
        },
        {
            'fixture_info': {
                'fixture_id': 5,
                'home_team': 'PSG',
                'away_team': 'Marseille',
                'league': 'Ligue 1',
                'date': '2025-07-17T21:00:00',
                'status': 'Not Started'
            },
            'ml_predictions': {
                'xgboost_over_1_5': {
                    'prediction': 1,
                    'confidence': 0.934,
                    'model_type': 'xgboost',
                    'model_name': 'over_1_5'
                }
            }
        }
    ]

def main():
    """Test the accumulator system."""
    print("🎯 TESTING ACCUMULATOR SYSTEM")
    print("=" * 60)
    print(f"📅 Test Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("🎲 Demonstrating how games combine to create target odds")
    print("=" * 60)
    
    # Create sample predictions
    sample_predictions = create_sample_predictions()
    print(f"\n📊 SAMPLE GAMES ({len(sample_predictions)} fixtures):")
    for i, pred in enumerate(sample_predictions, 1):
        fixture = pred['fixture_info']
        ml_preds = pred['ml_predictions']
        
        print(f"\n{i}. {fixture['home_team']} vs {fixture['away_team']} ({fixture['league']})")
        for pred_key, pred_data in ml_preds.items():
            model_name = pred_data['model_name']
            confidence = pred_data['confidence']
            print(f"   📈 {model_name}: {confidence:.1%} confidence")
    
    # Build accumulators
    print(f"\n🔄 BUILDING ACCUMULATORS...")
    print("-" * 40)
    
    accumulator_builder = AccumulatorBuilder()
    result = accumulator_builder.build_accumulators(sample_predictions)
    
    if result['status'] == 'success':
        accumulators = result['accumulators']
        summary = result['summary']
        
        print(f"✅ SUCCESS!")
        print(f"📊 Analyzed: {result['total_games_analyzed']} games")
        print(f"🎯 High-confidence selections: {result['high_confidence_selections']}")
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
        
        print(f"\n📈 SUMMARY:")
        print(f"🎯 Categories with accumulators: {summary['categories_with_accumulators']}/{summary['total_categories']}")
        print(f"🎮 Total games used: {summary['total_games_in_accumulators']}")
        print(f"📊 Success rate: {summary['success_rate']}")
        
    else:
        print(f"❌ ERROR: {result.get('message', 'Unknown error')}")
    
    print(f"\n" + "=" * 60)
    print("🎉 ACCUMULATOR TEST COMPLETED!")
    print("💡 This shows how individual games combine to create target odds")
    print("🎯 Frontend will receive these pre-built accumulators")
    print("=" * 60)

if __name__ == "__main__":
    main()
