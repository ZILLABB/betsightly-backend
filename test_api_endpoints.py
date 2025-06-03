#!/usr/bin/env python3
"""
Test API Endpoints

This script tests the BetSightly API endpoints to see what data is being returned.
"""

import requests
import json
import sys

# API base URL
BASE_URL = "http://localhost:8000"

def test_endpoint(endpoint, description):
    """Test an API endpoint and display results."""
    print(f"\n{'='*60}")
    print(f"Testing: {description}")
    print(f"URL: {BASE_URL}{endpoint}")
    print(f"{'='*60}")
    
    try:
        response = requests.get(f"{BASE_URL}{endpoint}", timeout=30)
        
        print(f"Status Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            try:
                data = response.json()
                print(f"Response Data:")
                print(json.dumps(data, indent=2, default=str))
            except json.JSONDecodeError:
                print(f"Response Text: {response.text}")
        else:
            print(f"Error Response: {response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {str(e)}")
    except Exception as e:
        print(f"Unexpected error: {str(e)}")

def main():
    """Test all punter-related endpoints."""
    print("🧪 Testing BetSightly API Endpoints")
    print("=" * 60)
    
    # Test health endpoint first
    test_endpoint("/api/health/", "Health Check")
    
    # Test punter endpoints
    test_endpoint("/api/punters/", "Get All Punters")
    test_endpoint("/api/punters/top", "Get Top Punters")
    test_endpoint("/api/punters/1", "Get Specific Punter (ID: 1)")
    
    # Test betting codes endpoints
    test_endpoint("/api/betting-codes/", "Get All Betting Codes")
    test_endpoint("/api/betting-codes/?punter_id=1", "Get Betting Codes for Punter 1")
    test_endpoint("/api/betting-codes/?featured=true", "Get Featured Betting Codes")
    
    # Test bookmakers endpoint
    test_endpoint("/api/bookmakers/", "Get All Bookmakers")
    
    # Test predictions endpoint
    test_endpoint("/api/predictions/", "Get Predictions")
    test_endpoint("/api/predictions/?category=2_odds", "Get 2 Odds Predictions")
    
    print(f"\n{'='*60}")
    print("✅ API Testing Complete!")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
