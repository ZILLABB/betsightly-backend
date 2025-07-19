#!/usr/bin/env python3
"""
Simple test for APIFootball.com integration.
"""

import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Add the project root to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
load_dotenv()

from services.apifootball_service import APIFootballService


def main():
    """Test APIFootball.com integration."""
    print("🔍 Testing APIFootball.com Integration")
    print("=" * 50)
    
    # Check API key
    api_key = os.getenv("APIFOOTBALL_API_KEY")
    if not api_key:
        print("❌ APIFOOTBALL_API_KEY not found!")
        return False
    
    print(f"🔑 API Key: {api_key[:20]}...")
    
    # Create service
    service = APIFootballService()
    
    # Test connection
    print("\n🔍 Testing connection...")
    if service.test_connection():
        print("✅ Connection successful!")
    else:
        print("❌ Connection failed!")
        return False
    
    # Test getting leagues
    print("\n🏆 Testing leagues...")
    leagues = service.get_leagues()
    print(f"📋 Found {len(leagues)} leagues")
    
    if leagues:
        print("🔝 Top 5 leagues:")
        for i, league in enumerate(leagues[:5], 1):
            name = league.get('league_name', 'Unknown')
            country = league.get('country_name', 'Unknown')
            print(f"   {i}. {name} ({country})")
    
    # Test getting today's fixtures
    print("\n📅 Testing today's fixtures...")
    today = datetime.now().strftime("%Y-%m-%d")
    fixtures = service.get_daily_fixtures(today)
    print(f"⚽ Found {len(fixtures)} fixtures for {today}")
    
    if fixtures:
        print("🔝 Sample fixtures:")
        for i, fixture in enumerate(fixtures[:3], 1):
            home = fixture.get('home_team', 'Unknown')
            away = fixture.get('away_team', 'Unknown')
            league = fixture.get('league_name', 'Unknown')
            print(f"   {i}. {home} vs {away} ({league})")
    
    # Test live fixtures
    print("\n🔴 Testing live fixtures...")
    live_fixtures = service.get_live_fixtures()
    print(f"🔴 Found {len(live_fixtures)} live fixtures")
    
    print("\n🎉 APIFootball.com integration test completed successfully!")
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
