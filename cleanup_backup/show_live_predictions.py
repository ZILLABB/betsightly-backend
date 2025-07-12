#!/usr/bin/env python3
"""
Show detailed live predictions from the API
"""

import requests
import json
from datetime import datetime

def get_live_predictions():
    """Get and display live predictions."""
    print("🔮 LIVE BETSIGHTLY PREDICTIONS")
    print("=" * 60)
    print(f"📅 Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    try:
        # Get predictions from live API
        response = requests.get("http://localhost:8000/api/predictions/", timeout=30)
        
        if response.status_code != 200:
            print(f"❌ API Error: {response.status_code}")
            return
        
        data = response.json()
        
        # Show summary
        total_predictions = sum(len(v) if isinstance(v, list) else 0 for v in data.values())
        print(f"📊 SUMMARY:")
        print(f"   Total Predictions: {total_predictions}")
        print(f"   Categories: {list(data.keys())}")
        
        # Show predictions by category
        for category, predictions in data.items():
            if isinstance(predictions, list) and predictions:
                print(f"\n🎯 {category.upper()} CATEGORY ({len(predictions)} predictions):")
                
                for i, pred in enumerate(predictions, 1):
                    if isinstance(pred, dict) and 'fixture' in pred:
                        fixture = pred['fixture']
                        print(f"\n   📍 MATCH {i}:")
                        print(f"      🏟️  {fixture.get('home_team', 'Unknown')} vs {fixture.get('away_team', 'Unknown')}")
                        print(f"      🏆 Competition: {fixture.get('competition', 'Unknown')}")
                        print(f"      📅 Date: {fixture.get('date', 'Unknown')}")
                        print(f"      ⭐ Overall Confidence: {pred.get('confidence', 0)}%")
                        
                        # Show individual predictions
                        predictions_data = pred.get('predictions', {})
                        print(f"      🔮 Predictions:")
                        
                        for pred_type, pred_info in predictions_data.items():
                            if isinstance(pred_info, dict):
                                prediction = pred_info.get('prediction', 'Unknown')
                                confidence = pred_info.get('confidence', 0)
                                print(f"         • {pred_type}: {prediction} ({confidence}%)")
        
        # Show enhanced predictions
        print(f"\n🚀 GETTING ENHANCED PREDICTIONS...")
        enhanced_response = requests.get("http://localhost:8000/api/predictions/enhanced/", timeout=30)
        
        if enhanced_response.status_code == 200:
            enhanced_data = enhanced_response.json()
            print(f"✅ Enhanced predictions available")
            print(f"   Status: {enhanced_data.get('status', 'unknown')}")
            print(f"   Features: {enhanced_data.get('features', [])}")
        else:
            print(f"⚠️ Enhanced predictions: {enhanced_response.status_code}")
        
        # Show basketball status
        print(f"\n🏀 BASKETBALL STATUS:")
        basketball_response = requests.get("http://localhost:8000/api/basketball-predictions/", timeout=30)
        
        if basketball_response.status_code == 200:
            basketball_data = basketball_response.json()
            print(f"   Status: {basketball_data.get('status', 'unknown')}")
            print(f"   Games Today: {basketball_data.get('total_games', 0)}")
            print(f"   Note: Basketball is in off-season (expected)")
        
        print(f"\n🎉 LIVE PREDICTIONS SUCCESSFULLY RETRIEVED!")
        print(f"🌐 Access full API at: http://localhost:8000/docs")
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")

if __name__ == "__main__":
    get_live_predictions()
