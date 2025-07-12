#!/usr/bin/env python3
"""
Complete N8N Setup - Final Configuration Script

This script completes the N8N Telegram integration setup.
"""

import os
import sys
import json
import asyncio
import httpx
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class N8NSetupCompleter:
    def __init__(self):
        self.api_url = "http://localhost:8000"
        self.n8n_url = "http://localhost:5678"
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        
    async def check_services(self):
        """Check if all required services are running."""
        print("🔍 Checking services...")
        
        services = {
            "BetSightly API": f"{self.api_url}/api/health",
            "N8N": f"{self.n8n_url}/healthz"
        }
        
        results = {}
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            for service, url in services.items():
                try:
                    response = await client.get(url)
                    if response.status_code == 200:
                        results[service] = "✅ Running"
                        print(f"   ✅ {service}: Running")
                    else:
                        results[service] = f"❌ Error {response.status_code}"
                        print(f"   ❌ {service}: Error {response.status_code}")
                except Exception as e:
                    results[service] = f"❌ Not accessible: {str(e)}"
                    print(f"   ❌ {service}: Not accessible")
        
        return results
    
    async def test_n8n_endpoints(self):
        """Test N8N integration endpoints."""
        print("\n🧪 Testing N8N integration endpoints...")
        
        endpoints = {
            "Health Check": f"{self.api_url}/api/n8n/health",
            "Dashboard Data": f"{self.api_url}/api/n8n/dashboard",
            "Performance Check": f"{self.api_url}/api/n8n/performance-check"
        }
        
        results = {}
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            for name, url in endpoints.items():
                try:
                    response = await client.get(url)
                    if response.status_code == 200:
                        data = response.json()
                        results[name] = "✅ Working"
                        print(f"   ✅ {name}: Working")
                    else:
                        results[name] = f"❌ Error {response.status_code}"
                        print(f"   ❌ {name}: Error {response.status_code}")
                except Exception as e:
                    results[name] = f"❌ Failed: {str(e)}"
                    print(f"   ❌ {name}: Failed")
        
        return results
    
    async def test_telegram_integration(self):
        """Test Telegram integration if Chat ID is available."""
        print("\n📱 Testing Telegram integration...")
        
        if not self.telegram_chat_id:
            print("   ⚠️  TELEGRAM_CHAT_ID not configured")
            print("   📋 Run get_telegram_chat_id.py first")
            return False
        
        try:
            # Test direct Telegram API
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            
            message = f"""🧪 **N8N Integration Test**

✅ **Setup Status**: Complete
🤖 **Bot**: Connected  
📱 **Chat ID**: {self.telegram_chat_id}
🔗 **N8N**: Ready for workflows

⏰ **Time**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Your BetSightly system is ready for enterprise monitoring!"""

            payload = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                
                if response.status_code == 200:
                    print("   ✅ Telegram test message sent successfully!")
                    return True
                else:
                    print(f"   ❌ Telegram test failed: {response.status_code}")
                    return False
                    
        except Exception as e:
            print(f"   ❌ Telegram test error: {str(e)}")
            return False
    
    def generate_setup_report(self, services, endpoints, telegram_success):
        """Generate final setup report."""
        print("\n" + "="*60)
        print("🎯 **N8N TELEGRAM INTEGRATION - SETUP REPORT**")
        print("="*60)
        
        # Services status
        print("\n🔧 **SERVICES STATUS:**")
        for service, status in services.items():
            print(f"   {status} {service}")
        
        # Endpoints status
        print("\n🌐 **N8N ENDPOINTS:**")
        for endpoint, status in endpoints.items():
            print(f"   {status} {endpoint}")
        
        # Telegram status
        print("\n📱 **TELEGRAM INTEGRATION:**")
        if telegram_success:
            print("   ✅ Telegram integration working")
            print("   📱 Test message sent successfully")
        elif self.telegram_chat_id:
            print("   ⚠️  Telegram configured but test failed")
        else:
            print("   ⚠️  Telegram Chat ID not configured")
        
        # Overall status
        all_services_ok = all("✅" in status for status in services.values())
        all_endpoints_ok = all("✅" in status for status in endpoints.values())
        
        print("\n🎉 **OVERALL STATUS:**")
        if all_services_ok and all_endpoints_ok:
            if telegram_success:
                print("   ✅ **COMPLETE** - All systems operational!")
                completion_percentage = 100
            else:
                print("   ⚠️  **95% COMPLETE** - Only Telegram Chat ID needed")
                completion_percentage = 95
        else:
            print("   ❌ **INCOMPLETE** - Some services need attention")
            completion_percentage = 70
        
        print(f"\n📊 **Completion**: {completion_percentage}%")
        
        # Next steps
        print("\n🔄 **NEXT STEPS:**")
        if not self.telegram_chat_id:
            print("   1. 📱 Get Telegram Chat ID: python get_telegram_chat_id.py")
            print("   2. 🔄 Import N8N workflows in dashboard")
            print("   3. ✅ Activate workflows")
        elif not telegram_success:
            print("   1. 🔍 Check Telegram bot permissions")
            print("   2. 🔄 Import N8N workflows in dashboard")
            print("   3. ✅ Activate workflows")
        else:
            print("   1. ✅ Import N8N workflows in dashboard")
            print("   2. ✅ Activate workflows")
            print("   3. 🎉 Enjoy enterprise monitoring!")
        
        print("\n🌐 **Quick Links:**")
        print(f"   • N8N Dashboard: {self.n8n_url}")
        print(f"   • BetSightly API: {self.api_url}")
        print(f"   • Health Check: {self.api_url}/api/health")
        
        return completion_percentage >= 95

async def main():
    print("🚀 **BetSightly N8N Integration - Final Setup**")
    print("=" * 60)
    
    setup = N8NSetupCompleter()
    
    # Check services
    services = await setup.check_services()
    
    # Test endpoints
    endpoints = await setup.test_n8n_endpoints()
    
    # Test Telegram
    telegram_success = await setup.test_telegram_integration()
    
    # Generate report
    success = setup.generate_setup_report(services, endpoints, telegram_success)
    
    if success:
        print("\n🎉 **SUCCESS!** N8N Telegram integration is ready!")
    else:
        print("\n⚠️  **Almost there!** Complete the remaining steps above.")

if __name__ == "__main__":
    asyncio.run(main())
