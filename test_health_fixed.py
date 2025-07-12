#!/usr/bin/env python3
"""
Test health endpoint after fixes
"""

from fastapi.testclient import TestClient

def test_health_endpoints():
    """Test health endpoints after fixes."""
    print("🔍 TESTING HEALTH ENDPOINTS AFTER FIXES")
    print("=" * 50)
    
    try:
        # Import fresh
        from main import app
        
        # Create test client
        client = TestClient(app)
        
        # Test basic health endpoint
        print("1. Testing basic health endpoint...")
        response = client.get("/api/health/")
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Basic health: {data['status']}")
        else:
            print(f"❌ Basic health failed: {response.text}")
        
        # Test detailed health endpoint
        print("\n2. Testing detailed health endpoint...")
        response = client.get("/api/health/detailed")
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Detailed health: {data['status']}")
            print(f"   Database: {data['checks']['database']['status']}")
            print(f"   API Keys: {data['checks']['api_keys']['status']}")
            print(f"   Models: {data['checks']['models']['status']}")
            print(f"   External APIs: {data['checks']['external_apis']['status']}")
            print(f"   Filesystem: {data['checks']['filesystem']['status']}")
        else:
            print(f"❌ Detailed health failed: {response.status_code}")
            # Try to parse error response
            try:
                error_data = response.json()
                if 'message' in error_data and isinstance(error_data['message'], dict):
                    checks = error_data['message'].get('checks', {})
                    print(f"   Database: {checks.get('database', {}).get('status', 'unknown')}")
                    print(f"   API Keys: {checks.get('api_keys', {}).get('status', 'unknown')}")
                    if 'api_keys' in checks and 'missing_keys' in checks['api_keys']:
                        print(f"   Missing keys: {checks['api_keys']['missing_keys']}")
                    print(f"   Models: {checks.get('models', {}).get('status', 'unknown')}")
                    print(f"   External APIs: {checks.get('external_apis', {}).get('status', 'unknown')}")
                    print(f"   Filesystem: {checks.get('filesystem', {}).get('status', 'unknown')}")
            except:
                print(f"   Raw response: {response.text[:200]}...")
        
        # Test readiness endpoint
        print("\n3. Testing readiness endpoint...")
        response = client.get("/api/health/ready")
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Readiness: {data['status']}")
        else:
            print(f"❌ Readiness failed: {response.text}")
        
        # Test liveness endpoint
        print("\n4. Testing liveness endpoint...")
        response = client.get("/api/health/live")
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Liveness: {data['status']}")
        else:
            print(f"❌ Liveness failed: {response.text}")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_health_endpoints()
