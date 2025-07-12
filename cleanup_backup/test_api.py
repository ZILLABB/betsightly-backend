#!/usr/bin/env python3
"""Test Enhanced API"""

import requests
import json

def test_api():
    print("🧪 Testing Enhanced Predictions API...")
    
    try:
        # Test basic health check first
        response = requests.get("http://localhost:8000/api/health/")
        if response.status_code == 200:
            print("✅ Basic API is working")
        else:
            print("❌ Basic API not responding")
            return
        
        # Test enhanced predictions
        response = requests.get("http://localhost:8000/api/predictions/enhanced/", params={
            "include_explanations": True,
            "explanation_detail": "human"
        })
        
        if response.status_code == 200:
            data = response.json()
            print("✅ Enhanced predictions API is working!")
            print(f"Response keys: {list(data.keys())}")
        else:
            print(f"❌ Enhanced API error: {response.status_code}")
            print(f"Response: {response.text}")
            
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to API. Start server with:")
        print("   py -m uvicorn main:app --reload")
    except Exception as e:
        print(f"❌ Test error: {e}")

if __name__ == "__main__":
    test_api()
