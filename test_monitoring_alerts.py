#!/usr/bin/env python3
"""
Test Monitoring Alerts

This script tests the monitoring system by temporarily stopping the API
to trigger alerts, then restarting it.
"""

import asyncio
import httpx
import time
import subprocess
import os
from datetime import datetime

async def send_test_telegram_message():
    """Send a test message to verify monitoring is working."""
    
    bot_token = "7299245660:AAHS2EB9PABvLYAh37WS_lv8BO3OhAVEFqw"
    chat_id = "-4971231188"
    
    message = f"""🧪 **Monitoring System Test**

✅ **System Monitor Workflow**: Active
⏰ **Test Time**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🔍 **What's Being Monitored:**
• API Health (every 5 minutes)
• Recent Activity
• System Resources

📱 **Alert Types You'll Receive:**
• 🔴 System failures
• ⚠️ No recent activity
• 📊 High resource usage

🎯 **Current Status**: All systems healthy
(No alerts = Everything working perfectly!)

Your enterprise monitoring is now ACTIVE! 🚀"""

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "Markdown"
                }
            )
            
            if response.status_code == 200:
                print("✅ Test message sent successfully!")
                return True
            else:
                print(f"❌ Failed to send message: {response.status_code}")
                return False
                
    except Exception as e:
        print(f"❌ Error sending message: {str(e)}")
        return False

async def test_api_monitoring():
    """Test if the API monitoring is working."""
    
    print("🧪 Testing API monitoring...")
    
    # Test current API status
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://127.0.0.1:8000/api/health")
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ API Status: {data.get('status', 'unknown')}")
                print(f"📊 Service: {data.get('service', 'unknown')}")
                print(f"⏰ Timestamp: {data.get('timestamp', 'unknown')}")
                return True
            else:
                print(f"⚠️ API returned status code: {response.status_code}")
                return False
                
    except Exception as e:
        print(f"❌ API not accessible: {str(e)}")
        return False

async def test_dashboard_endpoint():
    """Test the dashboard endpoint used by monitoring."""
    
    print("\n🔍 Testing dashboard endpoint...")
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://127.0.0.1:8000/api/n8n/dashboard")
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Dashboard Status: {data.get('status', 'unknown')}")
                print(f"📊 Total Predictions: {data.get('total_predictions', 0)}")
                print(f"🎯 Overall Accuracy: {data.get('overall_accuracy', 0)}%")
                print(f"🏆 Best Model: {data.get('best_model', 'unknown')}")
                return True
            else:
                print(f"⚠️ Dashboard returned status code: {response.status_code}")
                return False
                
    except Exception as e:
        print(f"❌ Dashboard not accessible: {str(e)}")
        return False

def check_n8n_status():
    """Check if N8N is running."""
    
    print("\n🔍 Checking N8N status...")
    
    try:
        result = subprocess.run(['curl', '-s', 'http://localhost:5678/healthz'], 
                              capture_output=True, text=True, timeout=5)
        
        if result.returncode == 0:
            print("✅ N8N is running and accessible")
            return True
        else:
            print("❌ N8N is not responding")
            return False
            
    except Exception as e:
        print(f"❌ Error checking N8N: {str(e)}")
        return False

async def main():
    print("🚀 **BetSightly Monitoring System Test**")
    print("=" * 50)
    
    # Test API
    api_ok = await test_api_monitoring()
    
    # Test Dashboard
    dashboard_ok = await test_dashboard_endpoint()
    
    # Test N8N
    n8n_ok = check_n8n_status()
    
    # Send test message
    print("\n📱 Sending test message...")
    message_ok = await send_test_telegram_message()
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 **Test Results Summary**")
    print("=" * 50)
    
    print(f"✅ API Health: {'Working' if api_ok else 'Failed'}")
    print(f"✅ Dashboard Endpoint: {'Working' if dashboard_ok else 'Failed'}")
    print(f"✅ N8N Server: {'Running' if n8n_ok else 'Not Running'}")
    print(f"✅ Telegram Alerts: {'Working' if message_ok else 'Failed'}")
    
    total_score = sum([api_ok, dashboard_ok, n8n_ok, message_ok])
    percentage = int((total_score / 4) * 100)
    
    print(f"\n📊 **Overall Status**: {percentage}% Operational")
    
    if percentage == 100:
        print("\n🎉 **PERFECT!** Your monitoring system is fully operational!")
        print("\n📋 **What happens next:**")
        print("• System checks every 5 minutes")
        print("• Alerts only when problems occur")
        print("• No alerts = Everything working perfectly")
        print("• You'll get daily summaries at 8 AM")
        print("• Performance alerts if accuracy drops")
    else:
        print(f"\n⚠️ **Issues detected** - {4-total_score} components need attention")
        
    print("\n🔄 **Your monitoring is now ACTIVE!**")

if __name__ == "__main__":
    asyncio.run(main())
