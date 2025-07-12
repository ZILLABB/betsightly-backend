#!/usr/bin/env python3
"""
Diagnose N8N Connection Issues

This script helps diagnose why N8N might not be able to connect to the BetSightly API.
"""

import asyncio
import httpx
import socket
import subprocess
import os

async def test_connections():
    """Test various connection methods."""
    
    print("🔍 **N8N Connection Diagnostics**")
    print("=" * 50)
    
    # Test 1: Direct API connection
    print("\n1️⃣ **Testing Direct API Connection**")
    endpoints = [
        "http://localhost:8000/api/health",
        "http://127.0.0.1:8000/api/health",
        "http://0.0.0.0:8000/api/health"
    ]
    
    for endpoint in endpoints:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(endpoint)
                if response.status_code == 200:
                    print(f"   ✅ {endpoint} - Working")
                else:
                    print(f"   ❌ {endpoint} - HTTP {response.status_code}")
        except Exception as e:
            print(f"   ❌ {endpoint} - {str(e)}")
    
    # Test 2: Port accessibility
    print("\n2️⃣ **Testing Port Accessibility**")
    ports = [8000, 5678]
    hosts = ['localhost', '127.0.0.1', '0.0.0.0']
    
    for port in ports:
        for host in hosts:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex((host, port))
                sock.close()
                
                if result == 0:
                    print(f"   ✅ {host}:{port} - Port open")
                else:
                    print(f"   ❌ {host}:{port} - Port closed/unreachable")
            except Exception as e:
                print(f"   ❌ {host}:{port} - {str(e)}")
    
    # Test 3: Process status
    print("\n3️⃣ **Testing Process Status**")
    try:
        # Check if processes are running
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        processes = result.stdout
        
        if 'uvicorn' in processes:
            print("   ✅ BetSightly API (uvicorn) - Running")
        else:
            print("   ❌ BetSightly API (uvicorn) - Not found")
            
        if 'n8n' in processes:
            print("   ✅ N8N - Running")
        else:
            print("   ❌ N8N - Not found")
            
    except Exception as e:
        print(f"   ❌ Process check failed: {str(e)}")
    
    # Test 4: Network configuration
    print("\n4️⃣ **Network Configuration**")
    try:
        # Check listening ports
        result = subprocess.run(['netstat', '-tlnp'], capture_output=True, text=True)
        netstat = result.stdout
        
        if ':8000' in netstat:
            print("   ✅ Port 8000 - Listening")
        else:
            print("   ❌ Port 8000 - Not listening")
            
        if ':5678' in netstat:
            print("   ✅ Port 5678 - Listening")
        else:
            print("   ❌ Port 5678 - Not listening")
            
    except Exception as e:
        print(f"   ❌ Network check failed: {str(e)}")
    
    # Test 5: Environment variables
    print("\n5️⃣ **Environment Check**")
    env_vars = ['TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID']
    for var in env_vars:
        value = os.getenv(var)
        if value:
            print(f"   ✅ {var} - Set")
        else:
            print(f"   ❌ {var} - Not set")

def provide_solutions():
    """Provide solutions based on common issues."""
    
    print("\n" + "=" * 50)
    print("🔧 **SOLUTIONS FOR COMMON ISSUES**")
    print("=" * 50)
    
    print("\n🚨 **If 'Connection Refused' in N8N:**")
    print("1. Use 127.0.0.1 instead of localhost in workflows")
    print("2. Increase timeout in HTTP Request nodes (15000ms)")
    print("3. Add retry logic (5 attempts)")
    print("4. Check firewall settings")
    
    print("\n🔄 **If API Not Responding:**")
    print("1. Restart BetSightly API:")
    print("   python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000")
    print("2. Check if port 8000 is available")
    print("3. Try different host binding (0.0.0.0 vs 127.0.0.1)")
    
    print("\n🌐 **If N8N Issues:**")
    print("1. Restart N8N: ./start_n8n.sh")
    print("2. Clear N8N cache: rm -rf ~/.n8n/cache")
    print("3. Check N8N logs for errors")
    
    print("\n✅ **Recommended Workflow Settings:**")
    print("• URL: http://127.0.0.1:8000/api/health")
    print("• Timeout: 15000ms")
    print("• Retry: 5 attempts")
    print("• Headers: User-Agent: N8N-BetSightly")

async def main():
    await test_connections()
    provide_solutions()
    
    print("\n🎯 **Next Steps:**")
    print("1. Import test_connection.json workflow")
    print("2. Execute it manually to test connection")
    print("3. If it works, import the main workflows")
    print("4. If it fails, try the solutions above")

if __name__ == "__main__":
    asyncio.run(main())
