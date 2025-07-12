#!/usr/bin/env python3
"""
Quick Verification Script for BetSightly Improvements
"""

import os
import sys
from pathlib import Path

def main():
    print("VERIFYING BETSIGHTLY IMPROVEMENTS")
    print("=" * 40)
    
    # Test 1: Configuration
    print("\n1. Testing Configuration...")
    try:
        from utils.config import settings
        print(f"   [PASS] Main config loaded: {settings.APP_NAME}")
        
        try:
            from app.utils.config import settings as old_settings
            print("   [FAIL] Old config should be blocked!")
        except ImportError:
            print("   [PASS] Old config correctly blocked")
    except Exception as e:
        print(f"   [FAIL] Config test failed: {e}")
    
    # Test 2: Dependencies
    print("\n2. Testing Dependencies...")
    if Path("ml_requirements.txt").exists():
        print("   [FAIL] ml_requirements.txt should be removed")
    else:
        print("   [PASS] ml_requirements.txt correctly removed")
    
    if Path("requirements.txt").exists():
        print("   [PASS] requirements.txt exists")
    else:
        print("   [FAIL] requirements.txt missing")
    
    # Test 3: Services
    print("\n3. Testing Services...")
    try:
        from services.enhanced_prediction_service import enhanced_prediction_service
        print("   [PASS] Enhanced prediction service available")
    except Exception as e:
        print(f"   [FAIL] Enhanced service failed: {e}")
    
    # Test 4: Training Scripts
    print("\n4. Testing Training Scripts...")
    redundant_scripts = [
        "train_advanced_ml_models.py",
        "train_advanced_models.py", 
        "train_enhanced_github_models.py",
        "train_github_models.py",
        "train_xgboost_models.py"
    ]
    
    removed_count = 0
    for script in redundant_scripts:
        if not Path(script).exists():
            removed_count += 1
    
    print(f"   [INFO] {removed_count}/{len(redundant_scripts)} redundant scripts removed")
    
    if Path("ml_pipeline_streamlined.py").exists():
        print("   [PASS] Main ML pipeline exists")
    else:
        print("   [FAIL] ml_pipeline_streamlined.py missing")
    
    # Test 5: Cache Management
    print("\n5. Testing Cache Management...")
    try:
        from utils.cache_manager import cache_manager
        stats = cache_manager.get_cache_stats()
        print(f"   [PASS] Cache manager working: {stats['total_files']} files")
    except Exception as e:
        print(f"   [FAIL] Cache management failed: {e}")
    
    # Test 6: Documentation
    print("\n6. Testing Documentation...")
    docs = [
        "docs/API_DOCUMENTATION.md",
        "docs/DEPLOYMENT_GUIDE.md"
    ]
    
    for doc in docs:
        if Path(doc).exists():
            print(f"   [PASS] {doc} exists")
        else:
            print(f"   [FAIL] {doc} missing")
    
    # Test 7: Test Suite
    print("\n7. Testing Test Suite...")
    test_files = [
        "tests/unit/services/test_enhanced_prediction_service.py",
        "tests/integration/test_api_endpoints.py",
        "tests/e2e/test_prediction_pipeline.py"
    ]
    
    for test_file in test_files:
        if Path(test_file).exists():
            print(f"   [PASS] {test_file} exists")
        else:
            print(f"   [FAIL] {test_file} missing")
    
    print("\n" + "=" * 40)
    print("VERIFICATION COMPLETE")
    print("\nNext steps:")
    print("1. Run: python -m pytest tests/ (to run tests)")
    print("2. Run: uvicorn main:app --reload (to start server)")
    print("3. Visit: http://localhost:8000/docs (to see API docs)")

if __name__ == "__main__":
    main()
