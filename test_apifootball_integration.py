#!/usr/bin/env python3
"""
Test script for APIFootball.com integration.
This script tests the new APIFootball.com service integration.
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Add the project root to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

from services.apifootball_service import APIFootballService


def test_apifootball_connection():
    """Test APIFootball.com connection."""
    print("\n" + "="*60)
    print("🔍 TESTING APIFOOTBALL.COM CONNECTION")
    print("="*60)
    
    try:
        service = APIFootballService()
        
        # Test connection
        print("📡 Testing API connection...")
        is_connected = service.test_connection()
        
        if is_connected:
            print("✅ APIFootball.com connection successful!")
            return True
        else:
            print("❌ APIFootball.com connection failed!")
            return False
            
    except Exception as e:
        print(f"❌ Error testing connection: {str(e)}")
        return False


def test_get_leagues():
    """Test getting leagues from APIFootball.com."""
    print("\n" + "="*60)
    print("🏆 TESTING LEAGUES RETRIEVAL")
    print("="*60)
    
    try:
        service = APIFootballService()
        leagues = service.get_leagues()
        
        print(f"📋 Retrieved {len(leagues)} leagues")
        
        if leagues:
            print("\n🔝 Top 10 leagues:")
            for i, league in enumerate(leagues[:10], 1):
                country = league.get('country_name', 'Unknown')
                name = league.get('league_name', 'Unknown League')
                league_id = league.get('league_id', 'N/A')
                print(f"   {i:2d}. {name} ({country}) - ID: {league_id}")
        
        return len(leagues) > 0
        
    except Exception as e:
        print(f"❌ Error getting leagues: {str(e)}")
        return False


def test_get_daily_fixtures():
    """Test getting daily fixtures."""
    print("\n" + "="*60)
    print("📅 TESTING DAILY FIXTURES RETRIEVAL")
    print("="*60)
    
    try:
        service = APIFootballService()
        
        # Test today's fixtures
        today = datetime.now().strftime("%Y-%m-%d")
        print(f"📅 Getting fixtures for today ({today})...")
        
        fixtures = service.get_daily_fixtures(today)
        print(f"⚽ Retrieved {len(fixtures)} fixtures for today")
        
        if fixtures:
            print("\n🔝 Sample fixtures:")
            for i, fixture in enumerate(fixtures[:5], 1):
                home = fixture.get('home_team', 'Unknown')
                away = fixture.get('away_team', 'Unknown')
                league = fixture.get('league_name', 'Unknown League')
                date_str = fixture.get('date', 'Unknown time')
                print(f"   {i}. {home} vs {away}")
                print(f"      League: {league}")
                print(f"      Date: {date_str}")
                print()
        
        # Test tomorrow's fixtures
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        print(f"📅 Getting fixtures for tomorrow ({tomorrow})...")
        
        tomorrow_fixtures = service.get_daily_fixtures(tomorrow)
        print(f"⚽ Retrieved {len(tomorrow_fixtures)} fixtures for tomorrow")
        
        return len(fixtures) > 0 or len(tomorrow_fixtures) > 0
        
    except Exception as e:
        print(f"❌ Error getting daily fixtures: {str(e)}")
        return False


def test_get_live_fixtures():
    """Test getting live fixtures."""
    print("\n" + "="*60)
    print("🔴 TESTING LIVE FIXTURES RETRIEVAL")
    print("="*60)
    
    try:
        service = APIFootballService()
        
        print("🔴 Getting live fixtures...")
        fixtures = service.get_live_fixtures()
        print(f"⚽ Retrieved {len(fixtures)} live fixtures")
        
        if fixtures:
            print("\n🔴 Live fixtures:")
            for i, fixture in enumerate(fixtures[:5], 1):
                home = fixture.get('home_team', 'Unknown')
                away = fixture.get('away_team', 'Unknown')
                league = fixture.get('league_name', 'Unknown League')
                status = fixture.get('status', 'Unknown')
                print(f"   {i}. {home} vs {away}")
                print(f"      League: {league}")
                print(f"      Status: {status}")
                print()
        else:
            print("ℹ️  No live fixtures currently available")
        
        return True  # Live fixtures can be empty, that's normal
        
    except Exception as e:
        print(f"❌ Error getting live fixtures: {str(e)}")
        return False


def test_data_format():
    """Test data format consistency."""
    print("\n" + "="*60)
    print("🔍 TESTING DATA FORMAT CONSISTENCY")
    print("="*60)
    
    try:
        service = APIFootballService()
        fixtures = service.get_daily_fixtures()
        
        if not fixtures:
            print("⚠️  No fixtures available for format testing")
            return True
        
        print(f"🔍 Analyzing format of {len(fixtures)} fixtures...")
        
        # Check required fields
        required_fields = [
            'fixture_id', 'home_team', 'away_team', 'league_name', 'date'
        ]
        
        format_issues = 0
        
        for i, fixture in enumerate(fixtures[:10]):  # Check first 10
            for field in required_fields:
                if field not in fixture:
                    print(f"❌ Missing field '{field}' in fixture {i+1}")
                    format_issues += 1
                elif not fixture[field]:
                    print(f"⚠️  Empty field '{field}' in fixture {i+1}")
        
        if format_issues == 0:
            print("✅ All fixtures have consistent format!")
            
            # Show sample fixture structure
            print("\n📋 Sample fixture structure:")
            sample = fixtures[0]
            for key, value in sample.items():
                print(f"   {key}: {value} ({type(value).__name__})")
        else:
            print(f"❌ Found {format_issues} format issues")
        
        return format_issues == 0
        
    except Exception as e:
        print(f"❌ Error testing data format: {str(e)}")
        return False


def main():
    """Run all APIFootball.com integration tests."""
    print("🚀 APIFOOTBALL.COM INTEGRATION TEST SUITE")
    print("="*60)
    
    # Check API key
    api_key = os.getenv("APIFOOTBALL_API_KEY")
    if not api_key:
        print("❌ APIFOOTBALL_API_KEY not found in environment variables!")
        print("   Please add your API key to .env file")
        return False
    
    print(f"🔑 API Key configured: {api_key[:20]}...")
    
    # Run tests
    tests = [
        ("Connection Test", test_apifootball_connection),
        ("Leagues Retrieval", test_get_leagues),
        ("Daily Fixtures", test_get_daily_fixtures),
        ("Live Fixtures", test_get_live_fixtures),
        ("Data Format", test_data_format),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ Test '{test_name}' crashed: {str(e)}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "="*60)
    print("📊 TEST RESULTS SUMMARY")
    print("="*60)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")
        if result:
            passed += 1
    
    print(f"\n📈 Overall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! APIFootball.com integration is working correctly.")
        print("\n🚀 Next steps:")
        print("   1. Test the API endpoints: /api/fixtures/apifootball/test")
        print("   2. Try syncing fixtures: /api/fixtures/apifootball/sync")
        print("   3. Check daily fixtures: /api/fixtures/apifootball/daily")
        return True
    else:
        print("⚠️  Some tests failed. Please check the configuration and try again.")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
