#!/usr/bin/env python3
"""
Test APIFootball.com historical data availability for ML training.
"""

import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
load_dotenv()

from services.apifootball_service import APIFootballService


def test_historical_data():
    """Test historical data retrieval from APIFootball.com."""
    print("🔍 Testing APIFootball.com Historical Data Availability")
    print("=" * 60)
    
    service = APIFootballService()
    
    # Test connection first
    if not service.test_connection():
        print("❌ Connection failed!")
        return False
    
    print("✅ Connection successful!")
    
    # Test different date ranges
    test_ranges = [
        # Recent data (last week)
        {
            "name": "Last Week",
            "from": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
            "to": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        },
        # Last month
        {
            "name": "Last Month", 
            "from": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
            "to": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        },
        # 3 months ago
        {
            "name": "3 Months Ago",
            "from": (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"),
            "to": (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        }
    ]
    
    total_matches = 0
    
    for test_range in test_ranges:
        print(f"\n📅 Testing {test_range['name']} ({test_range['from']} to {test_range['to']})")
        
        matches = service.get_historical_matches(
            test_range['from'], 
            test_range['to']
        )
        
        print(f"   📊 Found {len(matches)} finished matches")
        total_matches += len(matches)
        
        if matches:
            # Show sample matches
            print("   🔝 Sample matches:")
            for i, match in enumerate(matches[:3], 1):
                home = match.get('home_team', 'Unknown')
                away = match.get('away_team', 'Unknown')
                home_score = match.get('home_score', 0)
                away_score = match.get('away_score', 0)
                league = match.get('league_name', 'Unknown')
                date = match.get('date', 'Unknown')[:10]
                
                print(f"      {i}. {home} {home_score}-{away_score} {away} ({league}) - {date}")
    
    print(f"\n📈 SUMMARY:")
    print(f"   Total Historical Matches: {total_matches}")
    
    if total_matches > 0:
        print("   ✅ APIFootball.com has historical data suitable for training!")
        
        # Test specific leagues
        print(f"\n🏆 Testing Major League Data:")
        
        # Get leagues first
        leagues = service.get_leagues()
        major_leagues = []
        
        # Find major leagues
        for league in leagues[:20]:  # Check first 20 leagues
            league_name = league.get('league_name', '').lower()
            if any(keyword in league_name for keyword in ['premier', 'liga', 'serie', 'bundesliga', 'ligue']):
                major_leagues.append(league)
        
        print(f"   📋 Found {len(major_leagues)} major leagues")
        
        # Test one major league
        if major_leagues:
            test_league = major_leagues[0]
            league_id = test_league.get('league_id')
            league_name = test_league.get('league_name')
            
            print(f"   🔍 Testing {league_name} (ID: {league_id})")
            
            league_matches = service.get_historical_matches(
                (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d"),
                league_id=league_id
            )
            
            print(f"   📊 {league_name}: {len(league_matches)} matches in last 30 days")
        
        return True
    else:
        print("   ❌ No historical data found - may need different date ranges or subscription plan")
        return False


def main():
    """Main test execution."""
    success = test_historical_data()
    
    if success:
        print(f"\n🎉 Historical data test successful!")
        print(f"💡 APIFootball.com can be used as additional training data source")
    else:
        print(f"\n⚠️  Historical data test failed or limited data available")
        print(f"💡 Will rely on GitHub datasets for training")
    
    return success


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
