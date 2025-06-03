#!/usr/bin/env python3
"""
Deploy Telegram Bot for Punter Predictions

This script deploys the Telegram bot to run alongside the main application.
"""

import os
import sys
import logging
import subprocess
import time
from pathlib import Path

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def check_environment():
    """Check if all required environment variables are set."""
    required_vars = [
        "TELEGRAM_BOT_TOKEN",
        "DATABASE_URL"
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {missing_vars}")
        return False
    
    logger.info("✅ All required environment variables are set")
    return True

def install_telegram_dependencies():
    """Install Telegram bot dependencies."""
    try:
        logger.info("📦 Installing Telegram bot dependencies...")
        
        # Install python-telegram-bot
        subprocess.run([
            sys.executable, "-m", "pip", "install", 
            "python-telegram-bot==20.7"
        ], check=True)
        
        logger.info("✅ Telegram dependencies installed successfully")
        return True
        
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Failed to install dependencies: {e}")
        return False

def test_bot_connection():
    """Test if the bot can connect to Telegram."""
    try:
        logger.info("🔗 Testing bot connection...")
        
        # Import and test bot
        from telegram import Bot
        
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        bot = Bot(token=bot_token)
        
        # Test connection
        bot_info = bot.get_me()
        logger.info(f"✅ Bot connected successfully: @{bot_info.username}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Bot connection failed: {e}")
        return False

def deploy_bot():
    """Deploy the Telegram bot."""
    try:
        logger.info("🚀 Deploying Telegram bot...")
        
        # Check if bot file exists
        bot_file = Path("telegram_bot.py")
        if not bot_file.exists():
            logger.error("❌ telegram_bot.py not found")
            return False
        
        # Run bot in background
        logger.info("🤖 Starting Telegram bot...")
        
        # For production, you would use a process manager like systemd or supervisor
        # For now, we'll provide instructions for manual deployment
        
        logger.info("✅ Bot deployment ready")
        logger.info("📋 To start the bot manually, run: python telegram_bot.py")
        logger.info("📋 For production, use a process manager like systemd or supervisor")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Bot deployment failed: {e}")
        return False

def create_systemd_service():
    """Create a systemd service file for the bot."""
    service_content = f"""[Unit]
Description=BetSightly Telegram Bot
After=network.target

[Service]
Type=simple
User=render
WorkingDirectory={os.getcwd()}
Environment=PATH={os.environ.get('PATH')}
Environment=DATABASE_URL={os.getenv('DATABASE_URL', '')}
Environment=TELEGRAM_BOT_TOKEN={os.getenv('TELEGRAM_BOT_TOKEN', '')}
Environment=TELEGRAM_GROUP_ID={os.getenv('TELEGRAM_GROUP_ID', '')}
ExecStart={sys.executable} telegram_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
    
    try:
        with open("betsightly-telegram-bot.service", "w") as f:
            f.write(service_content)
        
        logger.info("✅ Systemd service file created: betsightly-telegram-bot.service")
        logger.info("📋 To install: sudo cp betsightly-telegram-bot.service /etc/systemd/system/")
        logger.info("📋 To enable: sudo systemctl enable betsightly-telegram-bot")
        logger.info("📋 To start: sudo systemctl start betsightly-telegram-bot")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to create systemd service: {e}")
        return False

def main():
    """Main deployment function."""
    logger.info("🚀 Starting Telegram Bot Deployment")
    
    # Step 1: Check environment
    if not check_environment():
        logger.error("❌ Environment check failed")
        return False
    
    # Step 2: Install dependencies
    if not install_telegram_dependencies():
        logger.error("❌ Dependency installation failed")
        return False
    
    # Step 3: Test bot connection
    if not test_bot_connection():
        logger.error("❌ Bot connection test failed")
        return False
    
    # Step 4: Deploy bot
    if not deploy_bot():
        logger.error("❌ Bot deployment failed")
        return False
    
    # Step 5: Create systemd service
    create_systemd_service()
    
    logger.info("🎉 Telegram Bot Deployment Complete!")
    logger.info("")
    logger.info("📋 NEXT STEPS:")
    logger.info("1. Set TELEGRAM_BOT_TOKEN in your environment")
    logger.info("2. Set TELEGRAM_GROUP_ID (optional, for specific group monitoring)")
    logger.info("3. Run: python telegram_bot.py")
    logger.info("4. Add bot to your Telegram group")
    logger.info("5. Test with a message like:")
    logger.info("   Code: ABC123")
    logger.info("   Odds: 1.85")
    logger.info("   Bookmaker: Bet365")
    logger.info("")
    logger.info("🌐 API Endpoints Available:")
    logger.info("   GET  /api/betting-codes/")
    logger.info("   GET  /api/punters/")
    logger.info("   GET  /api/bookmakers/")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
