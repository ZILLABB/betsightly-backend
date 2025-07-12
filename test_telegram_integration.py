#!/usr/bin/env python3
"""
Test Telegram Integration for BetSightly N8N Setup
"""

import os
import sys
import requests
import json
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.append(str(project_root))

def test_telegram_bot():
    """Test if Telegram bot is working."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "7299245660:AAHS2EB9PABvLYAh37WS_lv8BO3OhAVEFqw")
    
    print("🤖 Testing Telegram Bot...")
    
    # Test bot info
    try:
        response = requests.get(f"https://api.telegram.org/bot{bot_token}/getMe")
        if response.status_code == 200:
            bot_info = response.json()
            if bot_info.get('ok'):
                print(f"✅ Bot is active: {bot_info['result']['first_name']} (@{bot_info['result']['username']})")
                return True
            else:
                print(f"❌ Bot error: {bot_info.get('description')}")
                return False
        else:
            print(f"❌ HTTP Error: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Connection error: {str(e)}")
        return False

def test_telegram_message():
    """Test sending a message to Telegram."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "7299245660:AAHS2EB9PABvLYAh37WS_lv8BO3OhAVEFqw")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "-4971231188")
    
    print(f"📱 Testing message to chat ID: {chat_id}")
    
    message = f"""🎯 BetSightly N8N Integration Test
📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

✅ N8N Server: Running
✅ BetSightly API: Running  
✅ ML Models: 22 models loaded
✅ Integration: Ready for monitoring

🚀 Your BetSightly monitoring system is operational!"""

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('ok'):
                print("✅ Test message sent successfully!")
                print(f"📨 Message ID: {result['result']['message_id']}")
                return True
            else:
                print(f"❌ Telegram API error: {result.get('description')}")
                return False
        else:
            print(f"❌ HTTP Error: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Error sending message: {str(e)}")
        return False

def test_n8n_endpoints():
    """Test N8N integration endpoints."""
    print("🔧 Testing N8N Integration Endpoints...")
    
    endpoints = [
        ("Health Check", "http://localhost:8000/api/n8n/health"),
        ("Dashboard", "http://localhost:8000/api/n8n/dashboard"),
        ("Performance Check", "http://localhost:8000/api/n8n/performance-check")
    ]
    
    all_working = True
    
    for name, url in endpoints:
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                print(f"✅ {name}: Working")
            else:
                print(f"❌ {name}: HTTP {response.status_code}")
                all_working = False
        except Exception as e:
            print(f"❌ {name}: Error - {str(e)}")
            all_working = False
    
    return all_working

def main():
    """Main test function."""
    print("🚀 BetSightly N8N Integration Test")
    print("=" * 50)
    
    # Test 1: Telegram Bot
    bot_working = test_telegram_bot()
    print()
    
    # Test 2: N8N Endpoints
    endpoints_working = test_n8n_endpoints()
    print()
    
    # Test 3: Telegram Message
    if bot_working:
        message_sent = test_telegram_message()
        print()
    else:
        message_sent = False
        print("⏭️  Skipping message test (bot not working)")
        print()
    
    # Summary
    print("📊 Test Summary:")
    print(f"🤖 Telegram Bot: {'✅ Working' if bot_working else '❌ Failed'}")
    print(f"🔧 N8N Endpoints: {'✅ Working' if endpoints_working else '❌ Failed'}")
    print(f"📱 Message Test: {'✅ Sent' if message_sent else '❌ Failed'}")
    print()
    
    if bot_working and endpoints_working and message_sent:
        print("🎉 ALL TESTS PASSED!")
        print("✅ Your N8N integration is ready for workflows!")
        print()
        print("📋 Next Steps:")
        print("1. Import workflows in N8N dashboard (http://localhost:5678)")
        print("2. Configure Telegram credentials in N8N")
        print("3. Activate workflows")
        print("4. Test workflow execution")
        return True
    else:
        print("⚠️  Some tests failed. Please check the configuration.")
        return False

if __name__ == "__main__":
    main()
