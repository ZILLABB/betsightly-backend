#!/usr/bin/env python3
"""
Debug fixture fetching
"""

import os
import sys
import requests
from dotenv import load_dotenv

# Load environment
load_dotenv()

def test_football_data_direct():
    """Test Football-Data.org API directly."""
    print("Testing Football-Data.org API directly...")
    
    api_key = os.getenv("FOOTBALL_DATA_KEY", "")
    print(f"API Key: {api_key[:15]}...")
    
    headers = {"X-Auth-Token": api_key}
    url = "https://api.football-data.org/v4/matches"
    params = {"dateFrom": "2025-05-31", "dateTo": "2025-05-31"}
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            matches = data.get("matches", [])
            print(f"Found {len(matches)} matches")
            
            for i, match in enumerate(matches[:3]):
                home = match.get("homeTeam", {}).get("name", "Unknown")
                away = match.get("awayTeam", {}).get("name", "Unknown")
                print(f"  {i+1}. {home} vs {away}")
            
            return matches
        else:
            print(f"Error: {response.status_code} - {response.text}")
            return []
            
    except Exception as e:
        print(f"Exception: {str(e)}")
        return []

def test_prediction_service():
    """Test the prediction service fixture fetching."""
    print("\nTesting prediction service...")
    
    try:
        from services.quick_prediction_service import QuickPredictionService
        
        service = QuickPredictionService()
        fixtures = service._get_fixtures_football_data("2025-05-31")
        
        print(f"Service found {len(fixtures)} fixtures")
        for i, fixture in enumerate(fixtures[:3]):
            print(f"  {i+1}. {fixture}")
        
        return fixtures
        
    except Exception as e:
        print(f"Service error: {str(e)}")
        import traceback
        traceback.print_exc()
        return []

if __name__ == "__main__":
    print("DEBUGGING FIXTURE FETCHING")
    print("=" * 40)
    
    # Test direct API call
    direct_matches = test_football_data_direct()
    
    # Test through service
    service_fixtures = test_prediction_service()
    
    print("\n" + "=" * 40)
    print("COMPARISON")
    print("=" * 40)
    print(f"Direct API: {len(direct_matches)} matches")
    print(f"Service: {len(service_fixtures)} fixtures")
