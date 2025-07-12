#!/usr/bin/env python3
"""
Get Telegram Chat ID Helper Script

This script helps you get your Telegram Chat ID for N8N integration.
"""

import requests
import json
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

def get_chat_id():
    """Get chat ID from Telegram bot updates."""
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not found in .env file")
        return None
    
    print("🤖 Getting Telegram Chat ID...")
    print(f"📱 Bot Token: {TELEGRAM_BOT_TOKEN[:10]}...")
    
    # Get updates from Telegram
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if not data.get("ok"):
            print(f"❌ Telegram API error: {data.get('description', 'Unknown error')}")
            return None
        
        updates = data.get("result", [])
        
        if not updates:
            print("⚠️  No messages found. Please:")
            print("   1. Find your bot in Telegram")
            print("   2. Send a message like 'Hello'")
            print("   3. Run this script again")
            print("")
            print("🔍 You can also manually get your Chat ID:")
            print(f"   Visit: https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates")
            print("   Look for 'chat':{'id':YOUR_CHAT_ID}")
            return None
        
        # Get the most recent chat ID
        latest_update = updates[-1]
        chat_id = latest_update.get("message", {}).get("chat", {}).get("id")
        
        if chat_id:
            print(f"✅ Found Chat ID: {chat_id}")
            
            # Update .env file
            update_env_file(chat_id)
            
            # Test sending a message
            test_message(chat_id)
            
            return chat_id
        else:
            print("❌ Could not extract Chat ID from updates")
            print("📄 Raw response:")
            print(json.dumps(data, indent=2))
            return None
            
    except requests.RequestException as e:
        print(f"❌ Network error: {str(e)}")
        return None
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return None

def update_env_file(chat_id):
    """Update .env file with Chat ID."""
    try:
        # Read current .env file
        with open('.env', 'r') as f:
            lines = f.readlines()
        
        # Update or add TELEGRAM_CHAT_ID
        updated = False
        for i, line in enumerate(lines):
            if line.startswith('TELEGRAM_CHAT_ID='):
                lines[i] = f'TELEGRAM_CHAT_ID={chat_id}\n'
                updated = True
                break
        
        if not updated:
            lines.append(f'TELEGRAM_CHAT_ID={chat_id}\n')
        
        # Write back to .env file
        with open('.env', 'w') as f:
            f.writelines(lines)
        
        print(f"✅ Updated .env file with TELEGRAM_CHAT_ID={chat_id}")
        
    except Exception as e:
        print(f"⚠️  Could not update .env file: {str(e)}")
        print(f"📝 Please manually add this line to your .env file:")
        print(f"   TELEGRAM_CHAT_ID={chat_id}")

def test_message(chat_id):
    """Send a test message to verify the Chat ID works."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        
        message = """🎉 **BetSightly N8N Integration Test**

✅ **Chat ID Configuration Successful!**

🤖 **Bot**: Connected
📱 **Chat ID**: {chat_id}
🔗 **Integration**: Ready for N8N workflows

Your BetSightly system can now send you:
• Daily prediction summaries
• Performance alerts
• System health notifications
• Emergency alerts

🚀 **Next Step**: Activate N8N workflows in the dashboard!""".format(chat_id=chat_id)
        
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }
        
        response = requests.post(url, json=payload, timeout=10)
        
        if response.status_code == 200:
            print("✅ Test message sent successfully!")
            print("📱 Check your Telegram for the confirmation message")
        else:
            print(f"⚠️  Test message failed: {response.status_code}")
            print(f"   Response: {response.text}")
            
    except Exception as e:
        print(f"⚠️  Could not send test message: {str(e)}")

if __name__ == "__main__":
    print("🚀 BetSightly Telegram Chat ID Helper")
    print("=" * 50)
    
    chat_id = get_chat_id()
    
    if chat_id:
        print("")
        print("🎯 **SUCCESS!** Your Telegram integration is ready!")
        print(f"📱 Chat ID: {chat_id}")
        print("")
        print("🔄 **Next Steps:**")
        print("1. ✅ Chat ID configured")
        print("2. 🔄 Import N8N workflows")
        print("3. 🔄 Activate workflows")
        print("4. 🔄 Test end-to-end integration")
    else:
        print("")
        print("❌ **Chat ID not found**")
        print("")
        print("📋 **Manual Steps:**")
        print("1. Open Telegram")
        print("2. Search for your bot")
        print("3. Send any message")
        print("4. Run this script again")
