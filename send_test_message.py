"""
Send Test Message to Telegram Bot

This script sends a test message to the Telegram bot.
"""

import os
import sys
import logging
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def main():
    """Send a test message to the Telegram bot."""
    # Get bot token
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set.")
        sys.exit(1)
    
    # Get chat ID (you need to get this from the bot)
    chat_id = input("Enter the chat ID: ")
    
    if not chat_id:
        logger.error("Chat ID not provided.")
        sys.exit(1)
    
    # Test message
    test_message = """
Code: TEST123
Match: Manchester United vs Liverpool
Prediction: Manchester United to win
Odds: 2.5
Bookmaker: Bet365
Date: 23/05/2023
Time: 19:30
"""
    
    # Send message
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": test_message
    }
    
    try:
        response = requests.post(url, data=data)
        response_json = response.json()
        
        if response.status_code == 200 and response_json.get("ok"):
            logger.info("Message sent successfully!")
            logger.info(f"Response: {response_json}")
        else:
            logger.error(f"Failed to send message: {response_json}")
    except Exception as e:
        logger.error(f"Error sending message: {str(e)}")

if __name__ == "__main__":
    main()
