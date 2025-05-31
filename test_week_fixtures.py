#!/usr/bin/env python3
"""
Test fixtures for the next week
"""

import os
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

def test_week_fixtures():
    """Test fixtures for the next week."""
    api_key = os.getenv("FOOTBALL_DATA_KEY")
    
    # Test next 7 days
    today = datetime.now()
    end_date = today + timedelta(days=7)
    
    headers = {"X-Auth-Token": api_key}
    url = "https://api.football-data.org/v4/matches"
    params = {
        "dateFrom": today.strftime("%Y-%m-%d"),
        "dateTo": end_date.strftime("%Y-%m-%d")
    }
    
    print(f"Testing fixtures from {params['dateFrom']} to {params['dateTo']}")
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            matches = data.get("matches", [])
            print(f"Found {len(matches)} matches in next week")
            
            for i, match in enumerate(matches[:10]):
                home = match.get("homeTeam", {}).get("name", "Unknown")
                away = match.get("awayTeam", {}).get("name", "Unknown")
                date = match.get("utcDate", "Unknown")
                competition = match.get("competition", {}).get("name", "Unknown")
                print(f"  {i+1}. {home} vs {away}")
                print(f"      Date: {date}")
                print(f"      Competition: {competition}")
                print()
            
            return matches
        else:
            print(f"Error: {response.status_code}")
            print(f"Response: {response.text}")
            return []
            
    except Exception as e:
        print(f"Exception: {str(e)}")
        return []

if __name__ == "__main__":
    matches = test_week_fixtures()
    
    if matches:
        print(f"\n🎉 SUCCESS: Found {len(matches)} real fixtures!")
        print("We can now test predictions with real data!")
    else:
        print("\n⚠️  No fixtures found in the next week")
        print("This might be an off-season period")
