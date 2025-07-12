#!/usr/bin/env python3
"""
Test the live API endpoints
"""

import requests
import json
from datetime import datetime

def test_api_endpoint(url, description):
    """Test a single API endpoint."""
    try:
        print(f"\n🔍 Testing {description}")
        print(f"URL: {url}")
        
        response = requests.get(url, timeout=30)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Success!")
            return data
        else:
            print(f"❌ Error: {response.status_code}")
            print(f"Response: {response.text[:200]}...")
            return None
            
    except Exception as e:
        print(f"❌ Exception: {str(e)}")
        return None

def main():
    """Test all live API endpoints."""
    print("🚀 TESTING LIVE BETSIGHTLY API")
    print("=" * 60)
    print(f"📅 Test Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    base_url = "http://localhost:8000"
    
    # Test endpoints
    endpoints = [
        (f"{base_url}/api/health/", "Basic Health Check"),
        (f"{base_url}/api/health/detailed", "Detailed Health Check"),
        (f"{base_url}/api/predictions/", "Live Football Predictions"),
        (f"{base_url}/api/predictions/?category=2_odds", "Safe Bets (2_odds)"),
        (f"{base_url}/api/basketball-predictions/", "Basketball Predictions"),
        (f"{base_url}/api/basketball-predictions/models/status", "Basketball Models Status")
    ]
    
    results = {}
    
    for url, description in endpoints:
        data = test_api_endpoint(url, description)
        results[description] = data
        
        # Show key information for each endpoint
        if data:
            if "health" in description.lower():
                print(f"   Status: {data.get('status', 'unknown')}")
                if 'checks' in data:
                    checks = data['checks']
                    print(f"   Database: {checks.get('database', {}).get('status', 'unknown')}")
                    print(f"   Models: {checks.get('models', {}).get('status', 'unknown')}")
                    print(f"   API Keys: {checks.get('api_keys', {}).get('status', 'unknown')}")
            
            elif "predictions" in description.lower() and "basketball" not in description.lower():
                if isinstance(data, dict):
                    categories = data.keys()
                    total_predictions = sum(len(v) if isinstance(v, list) else 0 for v in data.values())
                    print(f"   Categories: {list(categories)}")
                    print(f"   Total Predictions: {total_predictions}")
                    
                    # Show sample prediction
                    for category, predictions in data.items():
                        if isinstance(predictions, list) and predictions:
                            sample = predictions[0]
                            if isinstance(sample, dict) and 'fixture' in sample:
                                fixture = sample['fixture']
                                print(f"   Sample: {fixture.get('home_team', 'Unknown')} vs {fixture.get('away_team', 'Unknown')}")
                                print(f"   Confidence: {sample.get('confidence', 0)}%")
                            break
            
            elif "basketball" in description.lower():
                print(f"   Status: {data.get('status', 'unknown')}")
                if 'models' in description.lower():
                    available = data.get('available_models', 0)
                    total = data.get('total_models', 0)
                    print(f"   Models: {available}/{total} available")
                else:
                    print(f"   Games: {data.get('total_games', 0)}")
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 API TEST SUMMARY")
    print("=" * 60)
    
    successful = sum(1 for data in results.values() if data is not None)
    total = len(results)
    
    for description, data in results.items():
        status = "✅ WORKING" if data else "❌ FAILED"
        print(f"{status} {description}")
    
    print(f"\n📊 Overall: {successful}/{total} endpoints working ({successful/total*100:.1f}%)")
    
    if successful == total:
        print("🎉 ALL API ENDPOINTS WORKING PERFECTLY!")
        print("\n🌐 You can now:")
        print(f"   • View API docs: {base_url}/docs")
        print(f"   • Get predictions: {base_url}/api/predictions/")
        print(f"   • Check health: {base_url}/api/health/")
    else:
        print("⚠️ Some endpoints need attention")
    
    return results

if __name__ == "__main__":
    results = main()
