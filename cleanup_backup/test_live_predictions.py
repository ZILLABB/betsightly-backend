#!/usr/bin/env python3
"""
Test live predictions with real data
"""

import warnings
warnings.filterwarnings('ignore', category=UserWarning)

from services.quick_prediction_service import quick_prediction_service

def test_live_predictions():
    """Test live predictions with real data."""
    print("🔍 TESTING LIVE PREDICTIONS")
    print("=" * 50)
    
    # Get predictions for today
    result = quick_prediction_service.get_predictions_for_date()
    
    print(f"📊 Status: {result['status']}")
    print(f"📅 Date: {result['date']}")
    print(f"🏟️  Total fixtures: {result.get('summary', {}).get('total_fixtures', 0)}")
    print(f"🔮 Total predictions: {result.get('summary', {}).get('total_predictions', 0)}")
    print(f"⭐ High confidence: {result.get('summary', {}).get('high_confidence_predictions', 0)}")
    
    # Show categories
    categories = result.get('categories', {})
    print(f"\n📈 PREDICTION CATEGORIES:")
    for category, predictions in categories.items():
        print(f"   {category}: {len(predictions)} predictions")
    
    # Show sample predictions
    predictions = result.get('predictions', [])
    if predictions:
        print(f"\n🎯 SAMPLE PREDICTIONS:")
        for i, pred in enumerate(predictions[:2]):  # Show first 2
            fixture = pred['fixture']
            print(f"\n   Match {i+1}: {fixture['home_team']} vs {fixture['away_team']}")
            print(f"   Competition: {fixture['competition']}")
            print(f"   Overall Confidence: {pred['confidence']}%")
            
            for pred_type, pred_data in pred['predictions'].items():
                print(f"     {pred_type}: {pred_data['prediction']} ({pred_data['confidence']}%)")
    
    return result

if __name__ == "__main__":
    result = test_live_predictions()
    
    if result['status'] == 'success' and result.get('summary', {}).get('total_predictions', 0) > 0:
        print("\n🎉 LIVE PREDICTIONS WORKING PERFECTLY!")
    else:
        print(f"\n⚠️ Status: {result['status']}")
        print(f"Message: {result.get('message', 'No additional info')}")
