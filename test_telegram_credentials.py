#!/usr/bin/env python3
"""
Test Telegram Credentials

This script tests if the Telegram bot credentials are working correctly.
"""

import os
import asyncio
import httpx
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

async def test_telegram_credentials():
    """Test Telegram bot credentials and send a test message."""
    
    print("🧪 **Testing Telegram Credentials**")
    print("=" * 50)
    
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not found in .env file")
        return False
    
    if not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID not found in .env file")
        return False
    
    print(f"🤖 Bot Token: {TELEGRAM_BOT_TOKEN[:10]}...")
    print(f"📱 Chat ID: {TELEGRAM_CHAT_ID}")
    
    # Test bot info
    print("\n🔍 Testing bot information...")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe")
            
            if response.status_code == 200:
                bot_info = response.json()
                if bot_info.get("ok"):
                    bot_data = bot_info.get("result", {})
                    print(f"   ✅ Bot Name: {bot_data.get('first_name', 'Unknown')}")
                    print(f"   ✅ Username: @{bot_data.get('username', 'Unknown')}")
                    print(f"   ✅ Bot ID: {bot_data.get('id', 'Unknown')}")
                else:
                    print(f"   ❌ Bot API Error: {bot_info.get('description', 'Unknown error')}")
                    return False
            else:
                print(f"   ❌ HTTP Error: {response.status_code}")
                return False
                
    except Exception as e:
        print(f"   ❌ Network Error: {str(e)}")
        return False
    
    # Test sending message
    print("\n📱 Testing message sending...")
    try:
        message = f"""🧪 **N8N Credential Test**

✅ **Telegram Credentials Working!**

🤖 **Bot**: Connected and verified
📱 **Chat ID**: {TELEGRAM_CHAT_ID}
⏰ **Time**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🔧 **Next Steps:**
1. ✅ Telegram credentials configured
2. 🔄 Assign credentials to N8N workflows
3. ✅ Activate workflows
4. 🎉 Start receiving alerts!

Your N8N integration is ready! 🚀"""

        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json=payload
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    print("   ✅ Test message sent successfully!")
                    print("   📱 Check your Telegram for the test message")
                    return True
                else:
                    print(f"   ❌ Message API Error: {result.get('description', 'Unknown error')}")
                    return False
            else:
                print(f"   ❌ HTTP Error: {response.status_code}")
                print(f"   📄 Response: {response.text}")
                return False
                
    except Exception as e:
        print(f"   ❌ Send Error: {str(e)}")
        return False

async def main():
    success = await test_telegram_credentials()
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 **TELEGRAM CREDENTIALS WORKING!**")
        print("\n✅ **What this means:**")
        print("• Your bot token is valid")
        print("• Your chat ID is correct") 
        print("• Messages can be sent successfully")
        print("• N8N workflows will work with these credentials")
        
        print("\n🔄 **Next Steps:**")
        print("1. In N8N: Credentials → Add Credential → Telegram")
        print("2. Use the bot token shown above")
        print("3. Assign credential to Telegram nodes in workflows")
        print("4. Activate all workflows")
        
    else:
        print("❌ **TELEGRAM CREDENTIALS FAILED**")
        print("\n🔧 **Troubleshooting:**")
        print("• Check your internet connection")
        print("• Verify bot token in .env file")
        print("• Verify chat ID in .env file")
        print("• Make sure bot is not blocked")

if __name__ == "__main__":
    asyncio.run(main())
