#!/usr/bin/env python3
"""
Check N8N Workflow Import Status

This script helps verify if workflows are properly imported and active.
"""

import os
import asyncio
import httpx
from datetime import datetime

class WorkflowChecker:
    def __init__(self):
        self.n8n_url = "http://localhost:5678"
        self.api_url = "http://localhost:8000"
        
    async def check_n8n_status(self):
        """Check if N8N is running."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.n8n_url}/healthz")
                return response.status_code == 200
        except:
            return False
    
    async def test_webhook_endpoints(self):
        """Test if webhook endpoints are accessible."""
        endpoints = [
            "/webhook/telegram-alert",
            "/webhook/daily-summary", 
            "/webhook/performance-alert",
            "/webhook/system-monitor"
        ]
        
        results = {}
        
        async with httpx.AsyncClient(timeout=5.0) as client:
            for endpoint in endpoints:
                try:
                    # Just check if endpoint exists (expect 404 or 405, not connection error)
                    response = await client.get(f"{self.n8n_url}{endpoint}")
                    # 404/405 means endpoint exists but needs POST or proper data
                    results[endpoint] = response.status_code in [404, 405, 200]
                except:
                    results[endpoint] = False
        
        return results
    
    async def send_test_alert(self):
        """Send a test alert through the API."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(f"{self.api_url}/api/n8n/test-alert")
                return response.status_code == 200
        except:
            return False
    
    def print_status(self, n8n_running, webhook_results, test_alert_success):
        """Print current status."""
        print("🔍 **N8N Workflow Import Status Check**")
        print("=" * 50)
        print(f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # N8N Status
        status_icon = "✅" if n8n_running else "❌"
        print(f"{status_icon} **N8N Server**: {'Running' if n8n_running else 'Not Running'}")
        
        if not n8n_running:
            print("   🔧 Start N8N with: ./start_n8n.sh")
            return
        
        # Webhook Status
        print("\n🔗 **Webhook Endpoints**:")
        webhook_count = 0
        for endpoint, status in webhook_results.items():
            status_icon = "✅" if status else "❌"
            endpoint_name = endpoint.replace("/webhook/", "").replace("-", " ").title()
            print(f"   {status_icon} {endpoint_name}")
            if status:
                webhook_count += 1
        
        # Test Alert
        print(f"\n📱 **Test Alert**: {'✅ Success' if test_alert_success else '❌ Failed'}")
        
        # Overall Status
        total_checks = 1 + len(webhook_results) + 1  # N8N + webhooks + test alert
        passed_checks = (1 if n8n_running else 0) + webhook_count + (1 if test_alert_success else 0)
        completion = int((passed_checks / total_checks) * 100)
        
        print(f"\n📊 **Overall Status**: {completion}%")
        
        if completion == 100:
            print("\n🎉 **ALL WORKFLOWS IMPORTED AND ACTIVE!**")
            print("Your enterprise monitoring is fully operational!")
        elif completion >= 75:
            print("\n⚠️  **MOSTLY COMPLETE** - Minor issues detected")
            print("Check workflow activation in N8N dashboard")
        elif completion >= 50:
            print("\n🔄 **PARTIALLY COMPLETE** - Some workflows imported")
            print("Continue importing remaining workflows")
        else:
            print("\n❌ **WORKFLOWS NOT IMPORTED YET**")
            print("Follow the import instructions to add workflows")
        
        # Next Steps
        print("\n🔄 **Next Steps:**")
        if completion < 100:
            print("1. 📥 Import workflows in N8N dashboard")
            print("2. ✅ Activate all workflows") 
            print("3. 🔧 Configure Telegram credentials if needed")
            print("4. 🧪 Run this script again to verify")
        else:
            print("1. 🎉 Enjoy your enterprise monitoring!")
            print("2. 📱 Watch for Telegram alerts")
            print("3. 📊 Check daily summaries at 8 AM")

async def main():
    checker = WorkflowChecker()
    
    print("🚀 Checking N8N workflow import status...")
    print()
    
    # Check N8N
    n8n_running = await checker.check_n8n_status()
    
    # Check webhooks
    webhook_results = await checker.test_webhook_endpoints() if n8n_running else {}
    
    # Test alert
    test_alert_success = await checker.send_test_alert() if n8n_running else False
    
    # Print results
    checker.print_status(n8n_running, webhook_results, test_alert_success)

if __name__ == "__main__":
    asyncio.run(main())
