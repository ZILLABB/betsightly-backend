#!/usr/bin/env python3
"""
Test API Keys and Get Today's Matches

This script tests your API keys and fetches today's football matches.
"""

import os
import sys
import requests
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_football_data_org():
    """Test Football-Data.org API and get today's matches."""
    print("🏈 Testing Football-Data.org API...")
    
    api_key = os.getenv("FOOTBALL_DATA_KEY")
    if not api_key:
        print("❌ FOOTBALL_DATA_KEY not found in environment")
        return False
    
    # Football-Data.org API endpoint for today's matches
    base_url = "https://api.football-data.org/v4"
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    headers = {
        "X-Auth-Token": api_key
    }
    
    try:
        # Get today's matches
        url = f"{base_url}/matches"
        params = {
            "dateFrom": today,
            "dateTo": tomorrow
        }
        
        print(f"📡 Making request to: {url}")
        print(f"📅 Date range: {today} to {tomorrow}")
        
        response = requests.get(url, headers=headers, params=params, timeout=30)
        
        print(f"📊 Response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            matches = data.get("matches", [])
            
            print(f"✅ Football-Data.org API working!")
            print(f"🎯 Found {len(matches)} matches for today/tomorrow")
            
            # Show first few matches
            for i, match in enumerate(matches[:3]):
                home_team = match.get("homeTeam", {}).get("name", "Unknown")
                away_team = match.get("awayTeam", {}).get("name", "Unknown")
                competition = match.get("competition", {}).get("name", "Unknown")
                match_date = match.get("utcDate", "Unknown")
                
                print(f"  {i+1}. {home_team} vs {away_team} ({competition}) - {match_date}")
            
            if len(matches) > 3:
                print(f"  ... and {len(matches) - 3} more matches")
            
            return True
            
        elif response.status_code == 403:
            print("❌ API key invalid or quota exceeded")
            print("💡 Check your API key at: https://www.football-data.org/client/register")
            return False
        elif response.status_code == 429:
            print("❌ Rate limit exceeded")
            print("💡 Free tier: 10 calls/minute, 100 calls/day")
            return False
        else:
            print(f"❌ API error: {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error testing Football-Data.org API: {str(e)}")
        return False

def test_api_football():
    """Test API-Football and get today's matches."""
    print("\n⚽ Testing API-Football...")
    
    api_key = os.getenv("API_FOOTBALL_KEY")
    if not api_key:
        print("❌ API_FOOTBALL_KEY not found in environment")
        return False
    
    # API-Football endpoint for today's fixtures
    base_url = "https://v3.football.api-sports.io"
    today = datetime.now().strftime("%Y-%m-%d")
    
    headers = {
        "x-rapidapi-host": "v3.football.api-sports.io",
        "x-rapidapi-key": api_key
    }
    
    try:
        # Get today's fixtures
        url = f"{base_url}/fixtures"
        params = {
            "date": today
        }
        
        print(f"📡 Making request to: {url}")
        print(f"📅 Date: {today}")
        
        response = requests.get(url, headers=headers, params=params, timeout=30)
        
        print(f"📊 Response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            fixtures = data.get("response", [])
            
            print(f"✅ API-Football working!")
            print(f"🎯 Found {len(fixtures)} fixtures for today")
            
            # Show first few fixtures
            for i, fixture in enumerate(fixtures[:3]):
                home_team = fixture.get("teams", {}).get("home", {}).get("name", "Unknown")
                away_team = fixture.get("teams", {}).get("away", {}).get("name", "Unknown")
                league = fixture.get("league", {}).get("name", "Unknown")
                fixture_date = fixture.get("fixture", {}).get("date", "Unknown")
                
                print(f"  {i+1}. {home_team} vs {away_team} ({league}) - {fixture_date}")
            
            if len(fixtures) > 3:
                print(f"  ... and {len(fixtures) - 3} more fixtures")
            
            return True
            
        elif response.status_code == 403:
            print("❌ API key invalid or quota exceeded")
            print("💡 Check your API key at: https://rapidapi.com/api-sports/api/api-football")
            return False
        elif response.status_code == 429:
            print("❌ Rate limit exceeded")
            print("💡 Free tier: 100 calls/day")
            return False
        else:
            print(f"❌ API error: {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error testing API-Football: {str(e)}")
        return False

def test_betsightly_api():
    """Test BetSightly API endpoints."""
    print("\n🎯 Testing BetSightly API...")
    
    try:
        # Test health endpoint
        response = requests.get("http://localhost:8000/api/health/", timeout=10)
        
        if response.status_code == 200:
            health_data = response.json()
            print("✅ BetSightly API is running")
            print(f"📊 Status: {health_data.get('status', 'unknown')}")
            
            # Test detailed health
            response = requests.get("http://localhost:8000/api/health/detailed", timeout=10)
            if response.status_code == 200:
                detailed_health = response.json()
                api_keys_status = detailed_health.get("api_keys", {})
                print(f"🔑 API Keys Status: {api_keys_status.get('status', 'unknown')}")
            
            return True
        else:
            print(f"❌ BetSightly API error: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Error testing BetSightly API: {str(e)}")
        print("💡 Make sure the server is running: py -m uvicorn main:app --reload")
        return False

def main():
    """Main test function."""
    print("🔍 TESTING API KEYS AND CONNECTIONS")
    print("=" * 50)
    
    # Test both APIs
    football_data_ok = test_football_data_org()
    api_football_ok = test_api_football()
    betsightly_ok = test_betsightly_api()
    
    print("\n" + "=" * 50)
    print("📊 TEST RESULTS SUMMARY")
    print("=" * 50)
    
    print(f"Football-Data.org: {'✅ WORKING' if football_data_ok else '❌ FAILED'}")
    print(f"API-Football:      {'✅ WORKING' if api_football_ok else '❌ FAILED'}")
    print(f"BetSightly API:    {'✅ WORKING' if betsightly_ok else '❌ FAILED'}")
    
    if football_data_ok or api_football_ok:
        print("\n🎉 At least one data source is working!")
        print("🚀 You can now proceed with model training")
        
        if football_data_ok and api_football_ok:
            print("💪 Both APIs working - excellent redundancy!")
        elif football_data_ok:
            print("📊 Using Football-Data.org as primary source")
        else:
            print("📊 Using API-Football as primary source")
    else:
        print("\n⚠️  No data sources working")
        print("🔧 Please check your API keys and try again")
    
    print("\n📝 Next Steps:")
    if football_data_ok or api_football_ok:
        print("1. ✅ API keys configured correctly")
        print("2. 🤖 Run model training: py ml_pipeline_streamlined.py")
        print("3. 🎯 Test predictions: curl http://localhost:8000/api/predictions/")
    else:
        print("1. 🔑 Fix API key configuration")
        print("2. 🔄 Run this test again")

if __name__ == "__main__":
    main()
