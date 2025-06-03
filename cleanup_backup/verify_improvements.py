#!/usr/bin/env python3
"""
Verification Script for BetSightly Improvements

This script verifies that all the improvements from the audit are working correctly.
"""

import os
import sys
import importlib
from pathlib import Path

def test_configuration():
    """Test that configuration is working."""
    print("[CONFIG] Testing Configuration...")
    try:
        from utils.config import settings
        print(f"[PASS] Main config loaded: {settings.APP_NAME}")

        # Test that old config is blocked
        try:
            from app.utils.config import settings as old_settings
            print("[FAIL] Old config should be blocked!")
            return False
        except ImportError:
            print("[PASS] Old config correctly blocked")
            return True
    except Exception as e:
        print(f"[FAIL] Config test failed: {e}")
        return False

def test_dependencies():
    """Test that dependencies are consistent."""
    print("\n[DEPS] Testing Dependencies...")
    try:
        # Check that ml_requirements.txt is gone
        if Path("ml_requirements.txt").exists():
            print("[FAIL] ml_requirements.txt should be removed")
            return False

        # Check main requirements file exists
        if not Path("requirements.txt").exists():
            print("[FAIL] requirements.txt missing")
            return False

        print("[PASS] Dependencies consolidated correctly")
        return True
    except Exception as e:
        print(f"[FAIL] Dependencies test failed: {e}")
        return False

def test_services():
    """Test that services are consolidated."""
    print("\n🔄 Testing Services...")
    try:
        # Test enhanced service exists
        from services.enhanced_prediction_service import enhanced_prediction_service
        print("✅ Enhanced prediction service available")
        
        # Test old services are gone
        old_services = [
            "services.prediction_service_improved",
            "services.advanced_prediction_service"
        ]
        
        for service in old_services:
            try:
                importlib.import_module(service)
                print(f"❌ {service} should be removed")
                return False
            except ImportError:
                print(f"✅ {service} correctly removed")
        
        return True
    except Exception as e:
        print(f"❌ Services test failed: {e}")
        return False

def test_training_scripts():
    """Test that training scripts are consolidated."""
    print("\n🤖 Testing Training Scripts...")
    
    # Check that redundant scripts are gone
    redundant_scripts = [
        "train_advanced_ml_models.py",
        "train_advanced_models.py",
        "train_enhanced_github_models.py",
        "train_github_models.py",
        "train_xgboost_models.py"
    ]
    
    all_removed = True
    for script in redundant_scripts:
        if Path(script).exists():
            print(f"❌ {script} should be removed")
            all_removed = False
        else:
            print(f"✅ {script} correctly removed")
    
    # Check main pipeline exists
    if Path("ml_pipeline_streamlined.py").exists():
        print("✅ Main ML pipeline exists")
    else:
        print("❌ ml_pipeline_streamlined.py missing")
        all_removed = False
    
    return all_removed

def test_cache_management():
    """Test cache management utilities."""
    print("\n💾 Testing Cache Management...")
    try:
        from utils.cache_manager import cache_manager
        stats = cache_manager.get_cache_stats()
        print(f"✅ Cache manager working: {stats['total_files']} files, {stats['total_size_mb']:.2f} MB")
        return True
    except Exception as e:
        print(f"❌ Cache management test failed: {e}")
        return False

def test_documentation():
    """Test that documentation exists."""
    print("\n📚 Testing Documentation...")
    
    docs = [
        "docs/API_DOCUMENTATION.md",
        "docs/DEPLOYMENT_GUIDE.md"
    ]
    
    all_exist = True
    for doc in docs:
        if Path(doc).exists():
            print(f"✅ {doc} exists")
        else:
            print(f"❌ {doc} missing")
            all_exist = False
    
    return all_exist

def test_tests():
    """Test that test files exist."""
    print("\n🧪 Testing Test Suite...")
    
    test_files = [
        "tests/unit/services/test_enhanced_prediction_service.py",
        "tests/integration/test_api_endpoints.py",
        "tests/e2e/test_prediction_pipeline.py"
    ]
    
    all_exist = True
    for test_file in test_files:
        if Path(test_file).exists():
            print(f"✅ {test_file} exists")
        else:
            print(f"❌ {test_file} missing")
            all_exist = False
    
    return all_exist

def main():
    """Run all verification tests."""
    print("🔍 VERIFYING BETSIGHTLY IMPROVEMENTS")
    print("=" * 50)
    
    tests = [
        ("Configuration", test_configuration),
        ("Dependencies", test_dependencies),
        ("Services", test_services),
        ("Training Scripts", test_training_scripts),
        ("Cache Management", test_cache_management),
        ("Documentation", test_documentation),
        ("Test Suite", test_tests)
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} test crashed: {e}")
            results.append((test_name, False))
    
    print("\n" + "=" * 50)
    print("📊 VERIFICATION SUMMARY")
    print("=" * 50)
    
    passed = 0
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test_name:20} {status}")
        if result:
            passed += 1
    
    print(f"\nOverall: {passed}/{len(results)} tests passed")
    
    if passed == len(results):
        print("\n🎉 ALL IMPROVEMENTS VERIFIED SUCCESSFULLY!")
        print("\n🚀 Ready for next steps!")
        return True
    else:
        print(f"\n⚠️  {len(results) - passed} issues found. Please review the failures above.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
