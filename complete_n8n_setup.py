#!/usr/bin/env python3
"""
Complete N8N Integration Setup for BetSightly
This script provides a comprehensive setup and testing of the N8N integration
"""

import os
import sys
import json
import asyncio
import httpx
import subprocess
import time
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class BetSightlyN8NSetup:
    def __init__(self):
        self.n8n_url = "http://localhost:5678"
        self.api_url = "http://localhost:8000"
        self.workflows_dir = Path("n8n_workflows")
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        
    def print_header(self):
        """Print setup header"""
        print("=" * 70)
        print("🚀 BetSightly N8N Integration Complete Setup")
        print("=" * 70)
        print(f"📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🌐 N8N URL: {self.n8n_url}")
        print(f"🔗 API URL: {self.api_url}")
        print("=" * 70)
    
    def check_prerequisites(self):
        """Check all prerequisites"""
        print("\n🔍 Checking Prerequisites...")
        
        issues = []
        
        # Check N8N installation
        try:
            result = subprocess.run(["n8n", "--version"], capture_output=True, text=True)
            if result.returncode == 0:
                version = result.stdout.strip()
                print(f"✅ N8N installed: {version}")
            else:
                issues.append("N8N not properly installed")
        except FileNotFoundError:
            issues.append("N8N not found - install with: npm install -g n8n")
        
        # Check Node.js
        try:
            result = subprocess.run(["node", "--version"], capture_output=True, text=True)
            if result.returncode == 0:
                version = result.stdout.strip()
                print(f"✅ Node.js: {version}")
            else:
                issues.append("Node.js not working properly")
        except FileNotFoundError:
            issues.append("Node.js not found")
        
        # Check Python dependencies
        try:
            import httpx
            import psutil
            print("✅ Python dependencies available")
        except ImportError as e:
            issues.append(f"Missing Python dependency: {e}")
        
        # Check Telegram credentials
        if self.telegram_bot_token:
            print("✅ Telegram bot token found")
        else:
            print("⚠️  TELEGRAM_BOT_TOKEN not set in environment")
            print("   You can still proceed, but Telegram alerts won't work")

        if self.telegram_chat_id:
            print("✅ Telegram chat ID found")
        else:
            print("⚠️  TELEGRAM_CHAT_ID not set (can be configured later)")
            if self.telegram_bot_token:
                print("   To get your chat ID:")
                print("   1. Send a message to your bot")
                print(f"   2. Visit: https://api.telegram.org/bot{self.telegram_bot_token}/getUpdates")
                print("   3. Look for 'chat':{'id':YOUR_CHAT_ID} in the response")
        
        # Check workflow files
        workflow_files = [
            "betsightly_daily_summary.json",
            "betsightly_performance_alerts.json", 
            "betsightly_system_monitor.json"
        ]
        
        missing_workflows = []
        for workflow in workflow_files:
            if (self.workflows_dir / workflow).exists():
                print(f"✅ Workflow found: {workflow}")
            else:
                missing_workflows.append(workflow)
        
        if missing_workflows:
            issues.append(f"Missing workflow files: {', '.join(missing_workflows)}")
        
        return issues
    
    def check_n8n_status(self):
        """Check if N8N is running"""
        try:
            response = httpx.get(f"{self.n8n_url}/healthz", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def start_n8n(self):
        """Start N8N if not running"""
        if self.check_n8n_status():
            print("✅ N8N is already running")
            return True
        
        print("🚀 Starting N8N...")
        try:
            # Start N8N in background
            process = subprocess.Popen(
                ["n8n", "start"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            # Wait for N8N to start
            for i in range(30):
                if self.check_n8n_status():
                    print("✅ N8N started successfully")
                    return True
                time.sleep(1)
                if i % 5 == 0:
                    print(f"⏳ Waiting for N8N... ({i+1}/30)")
            
            print("❌ N8N failed to start within 30 seconds")
            return False
            
        except Exception as e:
            print(f"❌ Error starting N8N: {str(e)}")
            return False
    
    async def test_api_endpoints(self):
        """Test BetSightly API endpoints"""
        print("\n🔍 Testing BetSightly API Endpoints...")
        
        endpoints = [
            "/api/health",
            "/api/n8n/health", 
            "/api/n8n/dashboard",
            "/api/n8n/performance-check"
        ]
        
        results = {}
        
        async with httpx.AsyncClient() as client:
            for endpoint in endpoints:
                try:
                    response = await client.get(f"{self.api_url}{endpoint}", timeout=10)
                    results[endpoint] = {
                        "status": response.status_code,
                        "success": response.status_code == 200,
                        "response": response.json() if response.status_code == 200 else response.text[:100]
                    }
                    status_icon = "✅" if response.status_code == 200 else "❌"
                    print(f"{status_icon} {endpoint}: {response.status_code}")
                    
                except Exception as e:
                    results[endpoint] = {
                        "status": "error",
                        "success": False,
                        "error": str(e)
                    }
                    print(f"❌ {endpoint}: {str(e)}")
        
        return results
    
    async def test_n8n_webhooks(self):
        """Test N8N webhook endpoints"""
        print("\n🔍 Testing N8N Webhook Endpoints...")
        
        test_data = {
            "message": "🧪 Test from BetSightly setup script",
            "alert_type": "test",
            "timestamp": datetime.now().isoformat()
        }
        
        webhooks = [
            "telegram-alert",
            "system-monitor",
            "performance-alert"
        ]
        
        results = {}
        
        async with httpx.AsyncClient() as client:
            for webhook in webhooks:
                try:
                    response = await client.post(
                        f"{self.n8n_url}/webhook/{webhook}",
                        json=test_data,
                        timeout=10
                    )
                    results[webhook] = {
                        "status": response.status_code,
                        "success": response.status_code == 200
                    }
                    status_icon = "✅" if response.status_code == 200 else "⚠️"
                    print(f"{status_icon} webhook/{webhook}: {response.status_code}")
                    
                except Exception as e:
                    results[webhook] = {
                        "status": "error", 
                        "success": False,
                        "error": str(e)
                    }
                    print(f"❌ webhook/{webhook}: {str(e)}")
        
        return results
    
    async def send_test_telegram_message(self):
        """Send a test message to Telegram"""
        print("\n📱 Testing Telegram Integration...")
        
        if not self.telegram_bot_token:
            print("⚠️  No Telegram bot token - skipping Telegram test")
            return False
        
        if not self.telegram_chat_id:
            print("⚠️  No Telegram chat ID - skipping Telegram test")
            return False
        
        test_message = f"""🧪 **BetSightly N8N Integration Test**

⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
🔧 **Type:** Setup Test
✅ **Status:** Integration Working

This is a test message to verify that the N8N and Telegram integration is working correctly.

🚀 **System Status:** All systems operational
📊 **Integration:** N8N ↔️ BetSightly ↔️ Telegram
"""
        
        try:
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            data = {
                "chat_id": self.telegram_chat_id,
                "text": test_message,
                "parse_mode": "Markdown"
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=data, timeout=10)
                
                if response.status_code == 200:
                    print("✅ Telegram test message sent successfully!")
                    print("📱 Check your Telegram for the test message")
                    return True
                else:
                    print(f"❌ Telegram test failed: {response.status_code}")
                    print(f"Response: {response.text}")
                    return False
                    
        except Exception as e:
            print(f"❌ Telegram test error: {str(e)}")
            return False
    
    def generate_setup_report(self, api_results, webhook_results, telegram_success):
        """Generate a comprehensive setup report"""
        print("\n" + "=" * 70)
        print("📊 SETUP REPORT")
        print("=" * 70)
        
        # API Endpoints Summary
        print("\n🔗 API Endpoints:")
        api_success = sum(1 for r in api_results.values() if r.get('success', False))
        print(f"   Working: {api_success}/{len(api_results)}")
        
        # N8N Webhooks Summary  
        print("\n🔗 N8N Webhooks:")
        webhook_success = sum(1 for r in webhook_results.values() if r.get('success', False))
        print(f"   Working: {webhook_success}/{len(webhook_results)}")
        
        # Telegram Integration
        print(f"\n📱 Telegram Integration: {'✅ Working' if telegram_success else '❌ Not Working'}")
        
        # Overall Status
        overall_success = (
            api_success > 0 and 
            self.check_n8n_status() and
            telegram_success
        )
        
        print(f"\n🎯 Overall Status: {'✅ SUCCESS' if overall_success else '⚠️  PARTIAL SUCCESS'}")
        
        return overall_success

async def main():
    """Main setup function"""
    setup = BetSightlyN8NSetup()
    setup.print_header()
    
    # Check prerequisites
    issues = setup.check_prerequisites()
    if issues:
        print("\n❌ Prerequisites Issues Found:")
        for issue in issues:
            print(f"   • {issue}")
        print("\nPlease resolve these issues before continuing.")
        return False
    
    print("\n✅ All prerequisites satisfied!")
    
    # Start N8N
    if not setup.start_n8n():
        print("\n❌ Failed to start N8N. Please start manually and run again.")
        return False
    
    # Wait a moment for N8N to fully initialize
    print("\n⏳ Waiting for N8N to fully initialize...")
    await asyncio.sleep(3)
    
    # Test API endpoints
    api_results = await setup.test_api_endpoints()
    
    # Test N8N webhooks
    webhook_results = await setup.test_n8n_webhooks()
    
    # Test Telegram integration
    telegram_success = await setup.send_test_telegram_message()
    
    # Generate report
    success = setup.generate_setup_report(api_results, webhook_results, telegram_success)
    
    if success:
        print("\n🎉 N8N Integration Setup Complete!")
        print("\n📋 Next Steps:")
        print("   1. Open N8N Dashboard: http://localhost:5678")
        print("   2. Activate the imported workflows")
        print("   3. Start BetSightly API: python -m uvicorn main:app --reload")
        print("   4. Monitor your system with automated alerts!")
    else:
        print("\n⚠️  Setup completed with some issues.")
        print("   Check the report above and resolve any problems.")
    
    return success

if __name__ == "__main__":
    asyncio.run(main())
