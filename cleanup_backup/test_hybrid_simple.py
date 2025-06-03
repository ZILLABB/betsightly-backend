#!/usr/bin/env python3
"""
Simple test for hybrid ML pipeline
"""

import os
import sys
import pandas as pd
import requests
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_github_data():
    """Test downloading GitHub dataset."""
    print("Testing GitHub dataset download...")
    
    try:
        url = "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data-2000-2025/main/data/Matches.csv"
        print(f"Downloading from: {url}")
        
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        # Parse CSV
        df = pd.read_csv(response.content.decode('utf-8'))
        
        print(f"SUCCESS: Downloaded {len(df)} matches")
        print(f"Columns: {list(df.columns)[:5]}...")
        
        return True
        
    except Exception as e:
        print(f"ERROR: {str(e)}")
        return False

def test_api_keys():
    """Test API key configuration."""
    print("\nTesting API key configuration...")
    
    try:
        from utils.config import settings
        
        football_key = settings.football_data.API_KEY
        api_football_key = settings.api_football.API_KEY
        
        print(f"Football-Data.org key: {'CONFIGURED' if football_key and 'dummy' not in football_key else 'MISSING'}")
        print(f"API-Football key: {'CONFIGURED' if api_football_key and 'dummy' not in api_football_key else 'MISSING'}")
        
        return True
        
    except Exception as e:
        print(f"ERROR: {str(e)}")
        return False

def test_database():
    """Test database connection."""
    print("\nTesting database connection...")
    
    try:
        from database import engine
        
        # Test connection
        with engine.connect() as conn:
            result = conn.execute("SELECT 1").fetchone()
            print("SUCCESS: Database connection working")
            return True
            
    except Exception as e:
        print(f"ERROR: {str(e)}")
        return False

def main():
    """Run all tests."""
    print("HYBRID ML PIPELINE - SIMPLE TEST")
    print("=" * 40)
    
    tests = [
        ("GitHub Data", test_github_data),
        ("API Keys", test_api_keys),
        ("Database", test_database)
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"ERROR in {test_name}: {str(e)}")
            results.append((test_name, False))
    
    print("\n" + "=" * 40)
    print("TEST RESULTS")
    print("=" * 40)
    
    for test_name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"{test_name:15} {status}")
    
    all_passed = all(result for _, result in results)
    print(f"\nOverall: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
    
    if all_passed:
        print("\nReady to proceed with full hybrid pipeline!")
    else:
        print("\nPlease fix failing tests before proceeding.")

if __name__ == "__main__":
    main()
