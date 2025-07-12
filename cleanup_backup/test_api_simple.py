#!/usr/bin/env python3
"""
Simple API Key Test - Get Today's Matches
"""

import os
import requests
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_football_data_org():
    """Test Football-Data.org API and get today's matches."""
    print("Testing Football-Data.org API...")
    
    api_key = os.getenv("FOOTBALL_DATA_KEY")
    print(f"API Key: {api_key[:10]}..." if api_key else "No API key found")
    
    if not api_key:
        print("ERROR: FOOTBALL_DATA_KEY not found")
        return False
    
    # Football-Data.org API endpoint
    base_url = "https://api.football-data.org/v4"
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    headers = {
        "X-Auth-Token": api_key
    }
    
    try:
        url = f"{base_url}/matches"
        params = {
            "dateFrom": today,
            "dateTo": tomorrow
        }
        
        print(f"Making request to: {url}")
        print(f"Date range: {today} to {tomorrow}")
        
        response = requests.get(url, headers=headers, params=params, timeout=30)
        print(f"Response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            matches = data.get("matches", [])
            
            print(f"SUCCESS: Found {len(matches)} matches")
            
            # Show first few matches
            for i, match in enumerate(matches[:5]):
                home_team = match.get("homeTeam", {}).get("name", "Unknown")
                away_team = match.get("awayTeam", {}).get("name", "Unknown")
                competition = match.get("competition", {}).get("name", "Unknown")
                match_date = match.get("utcDate", "Unknown")
                
                print(f"  {i+1}. {home_team} vs {away_team} ({competition})")
                print(f"      Date: {match_date}")
            
            return True
            
        elif response.status_code == 403:
            print("ERROR: API key invalid or quota exceeded")
            return False
        elif response.status_code == 429:
            print("ERROR: Rate limit exceeded (10 calls/minute, 100 calls/day)")
            return False
        else:
            print(f"ERROR: API returned {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"ERROR: {str(e)}")
        return False

def test_api_football():
    """Test API-Football and get today's matches."""
    print("\nTesting API-Football...")
    
    api_key = os.getenv("API_FOOTBALL_KEY")
    print(f"API Key: {api_key[:10]}..." if api_key else "No API key found")
    
    if not api_key:
        print("ERROR: API_FOOTBALL_KEY not found")
        return False
    
    # API-Football endpoint
    base_url = "https://v3.football.api-sports.io"
    today = datetime.now().strftime("%Y-%m-%d")
    
    headers = {
        "x-rapidapi-host": "v3.football.api-sports.io",
        "x-rapidapi-key": api_key
    }
    
    try:
        url = f"{base_url}/fixtures"
        params = {
            "date": today
        }
        
        print(f"Making request to: {url}")
        print(f"Date: {today}")
        
        response = requests.get(url, headers=headers, params=params, timeout=30)
        print(f"Response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            fixtures = data.get("response", [])
            
            print(f"SUCCESS: Found {len(fixtures)} fixtures")
            
            # Show first few fixtures
            for i, fixture in enumerate(fixtures[:5]):
                home_team = fixture.get("teams", {}).get("home", {}).get("name", "Unknown")
                away_team = fixture.get("teams", {}).get("away", {}).get("name", "Unknown")
                league = fixture.get("league", {}).get("name", "Unknown")
                fixture_date = fixture.get("fixture", {}).get("date", "Unknown")
                
                print(f"  {i+1}. {home_team} vs {away_team} ({league})")
                print(f"      Date: {fixture_date}")
            
            return True
            
        elif response.status_code == 403:
            print("ERROR: API key invalid or quota exceeded")
            return False
        elif response.status_code == 429:
            print("ERROR: Rate limit exceeded (100 calls/day)")
            return False
        else:
            print(f"ERROR: API returned {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"ERROR: {str(e)}")
        return False

def main():
    """Main test function."""
    print("TESTING API KEYS - GET TODAY'S MATCHES")
    print("=" * 50)
    
    # Test both APIs
    football_data_ok = test_football_data_org()
    api_football_ok = test_api_football()
    
    print("\n" + "=" * 50)
    print("RESULTS SUMMARY")
    print("=" * 50)
    
    print(f"Football-Data.org: {'WORKING' if football_data_ok else 'FAILED'}")
    print(f"API-Football:      {'WORKING' if api_football_ok else 'FAILED'}")
    
    if football_data_ok or api_football_ok:
        print("\nSUCCESS: At least one API is working!")
        print("You can now proceed with model training")
    else:
        print("\nERROR: No APIs working")
        print("Please check your API keys")
    
    print("\nNext steps:")
    print("1. If APIs work: py ml_pipeline_streamlined.py")
    print("2. Test predictions: curl http://localhost:8000/api/predictions/")

if __name__ == "__main__":
    main()
