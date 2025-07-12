#!/usr/bin/env python3
"""
Check Telegram Bot Information

This script helps you find information about your Telegram bot.
"""

import requests
import json
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

def get_bot_info():
    """Get information about the Telegram bot."""
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not found in .env file")
        return None
    
    print("🤖 Getting Telegram Bot Information...")
    print(f"📱 Bot Token: {TELEGRAM_BOT_TOKEN[:10]}...")
    
    # Get bot info from Telegram
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe"
    
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if not data.get("ok"):
            print(f"❌ Telegram API error: {data.get('description', 'Unknown error')}")
            return None
        
        bot_info = data.get("result", {})
        
        print("\n✅ **Bot Information Found:**")
        print("=" * 40)
        print(f"🤖 **Bot Name**: {bot_info.get('first_name', 'N/A')}")
        print(f"👤 **Username**: @{bot_info.get('username', 'N/A')}")
        print(f"🆔 **Bot ID**: {bot_info.get('id', 'N/A')}")
        print(f"🔗 **Can Join Groups**: {bot_info.get('can_join_groups', False)}")
        print(f"📝 **Can Read Messages**: {bot_info.get('can_read_all_group_messages', False)}")
        print(f"🎯 **Supports Inline**: {bot_info.get('supports_inline_queries', False)}")
        
        username = bot_info.get('username')
        if username:
            print(f"\n📱 **To message your bot:**")
            print(f"   1. Open Telegram")
            print(f"   2. Search for: @{username}")
            print(f"   3. Send any message like 'Hello'")
            print(f"   4. Run: python get_telegram_chat_id.py")
        else:
            print(f"\n⚠️  **No username set for this bot**")
            print(f"   You'll need to contact whoever created the bot")
            print(f"   Or create a new bot with @BotFather")
        
        return bot_info
        
    except requests.RequestException as e:
        print(f"❌ Network error: {str(e)}")
        return None
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return None

def main():
    print("🚀 **BetSightly Telegram Bot Information**")
    print("=" * 50)
    
    bot_info = get_bot_info()
    
    if bot_info:
        print("\n🎯 **Next Steps:**")
        print("1. ✅ Bot information retrieved")
        print("2. 📱 Message your bot using the username above")
        print("3. 🔄 Run: python get_telegram_chat_id.py")
        print("4. 🎉 Complete N8N integration!")
    else:
        print("\n❌ **Could not retrieve bot information**")
        print("🔧 **Troubleshooting:**")
        print("1. Check your internet connection")
        print("2. Verify the bot token in .env file")
        print("3. Contact the bot creator if needed")

if __name__ == "__main__":
    main()
