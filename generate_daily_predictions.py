#!/usr/bin/env python3
"""
Generate Daily Predictions Script
Run this once per day to generate predictions and store in database.
"""

import sys
import os
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.daily_predictions_service import DailyPredictionsService

def main():
    """Generate today's predictions."""
    print("🎯 GENERATING DAILY PREDICTIONS")
    print("=" * 50)
    print(f"📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    
    try:
        # Initialize service
        service = DailyPredictionsService()
        
        # Generate predictions for today
        result = service.generate_daily_predictions()
        
        print(f"\n📊 RESULT:")
        print(f"Status: {result['status']}")
        print(f"Date: {result['date']}")
        print(f"Message: {result['message']}")
        
        if 'summary' in result:
            summary = result['summary']
            print(f"\n📈 SUMMARY:")
            print(f"Total Fixtures: {summary['total_fixtures']}")
            print(f"Upcoming Fixtures: {summary['upcoming_fixtures']}")
            print(f"Predictions Generated: {summary['predictions_generated']}")
            print(f"Models Used: {summary['models_used']}")
            print(f"Betting Categories:")
            print(f"  - 2_odds: {summary['betting_counts']['2_odds']}")
            print(f"  - 5_odds: {summary['betting_counts']['5_odds']}")
            print(f"  - 10_odds: {summary['betting_counts']['10_odds']}")
            print(f"  - rollover: {summary['betting_counts']['rollover']}")
        
        if result['status'] == 'success':
            print(f"\n✅ SUCCESS: Predictions stored in database!")
            print(f"💡 Frontend can now fetch from: /api/daily-predictions/today")
        else:
            print(f"\n⚠️  {result['status'].upper()}: {result['message']}")
        
        return result['status'] == 'success'
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
