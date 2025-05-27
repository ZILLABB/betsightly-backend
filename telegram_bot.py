"""
Telegram Bot for Punter Predictions

This script sets up a Telegram bot that listens for messages in a group,
extracts betting information, and saves it to the database.
"""

import os
import re
import logging
from datetime import datetime
from typing import Dict, Any

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Import database module
try:
    from telegram_db import SessionLocal, init_db, get_or_create_punter, get_or_create_bookmaker, save_betting_code

    # Initialize database
    init_db()

    # Create database session
    db = SessionLocal()

    # Set mock mode to False
    MOCK_MODE = False
    logger.info("Database connection established. Running in REAL mode.")
except ImportError as e:
    logger.warning(f"Could not import database module: {str(e)}")
    logger.warning("Running in MOCK mode.")
    db = None
    MOCK_MODE = True

# Telegram bot token (should be in config)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_GROUP_ID = os.getenv("TELEGRAM_GROUP_ID", "")

# Regular expressions for parsing betting information
BET_CODE_PATTERN = r"Code:\s*([A-Za-z0-9]+)"
ODDS_PATTERN = r"Odds:\s*([\d.]+)(?:odds)?"
BOOKMAKER_PATTERN = r"(?:Bookmaker|Bookmarker):\s*([A-Za-z0-9\s]+)"
DATE_PATTERN = r"Date:\s*(\d{2}/\d{2}/\d{4})"
TIME_PATTERN = r"Time:\s*(\d{2}:\d{2})"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    await update.message.reply_text(
        "Hi! I'm the Punter Bot. I'll save betting information from this group."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    help_text = """
    I can save betting information from this group. Use the following format:

    Code: ABC123
    Odds: 1.85
    Bookmaker: Bet365
    Date: 23/05/2023 (optional)
    Time: 19:30 (optional)
    """
    await update.message.reply_text(help_text)

def parse_betting_info(message_text: str) -> Dict[str, Any]:
    """
    Parse betting information from a message.

    Args:
        message_text: Message text

    Returns:
        Dictionary with parsed betting information
    """
    # Extract information using regex
    bet_code_match = re.search(BET_CODE_PATTERN, message_text, re.IGNORECASE)
    odds_match = re.search(ODDS_PATTERN, message_text, re.IGNORECASE)
    bookmaker_match = re.search(BOOKMAKER_PATTERN, message_text, re.IGNORECASE)
    date_match = re.search(DATE_PATTERN, message_text, re.IGNORECASE)
    time_match = re.search(TIME_PATTERN, message_text, re.IGNORECASE)

    # Create result dictionary
    result = {
        "bet_code": bet_code_match.group(1) if bet_code_match else None,
        "odds": float(odds_match.group(1)) if odds_match else None,
        "bookmaker": bookmaker_match.group(1).strip() if bookmaker_match else None,
        "source": "telegram",
        "source_text": message_text,
    }

    # Parse date and time
    if date_match and time_match:
        date_str = date_match.group(1)
        time_str = time_match.group(1)

        try:
            event_datetime = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
            result["event_date"] = event_datetime
        except ValueError:
            logger.error(f"Error parsing date and time: {date_str} {time_str}")

    return result

async def save_betting_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Save betting information from a message.

    Args:
        update: Update object
        context: Context object
    """
    # Log all incoming messages with chat info
    chat_type = update.effective_chat.type
    chat_id = update.effective_chat.id
    chat_title = getattr(update.effective_chat, 'title', 'Private Chat')

    logger.info(f"Received message from {update.effective_user.full_name}: {update.message.text}")
    logger.info(f"Chat Info - Type: {chat_type}, ID: {chat_id}, Title: {chat_title}")

    # Check if message is in the target group
    if TELEGRAM_GROUP_ID and str(update.effective_chat.id) != TELEGRAM_GROUP_ID:
        logger.info(f"Message not in target group. Expected: {TELEGRAM_GROUP_ID}, Got: {update.effective_chat.id}")
        return

    # Get message text
    message_text = update.message.text

    # Parse betting information
    betting_info = parse_betting_info(message_text)
    logger.info(f"Parsed betting info: {betting_info}")

    # Check if we have enough information
    if not (betting_info["bet_code"] and betting_info["odds"] and betting_info["bookmaker"]):
        logger.info("Missing required information. Need code, odds, and bookmaker.")
        await update.message.reply_text(
            "❌ Missing required information. Please include:\n"
            "- Code\n"
            "- Odds\n"
            "- Bookmaker\n"
            "- Date (optional)\n"
            "- Time (optional)"
        )
        return

    try:
        # Get user information
        punter_name = update.effective_user.full_name
        punter_username = update.effective_user.username

        # Check if we're in mock mode
        if MOCK_MODE or db is None:
            # Mock mode - just log the information
            logger.info(f"[MOCK MODE] Would save betting information from {punter_name}:")
            logger.info(f"  Code: {betting_info['bet_code']}")
            logger.info(f"  Odds: {betting_info['odds']}")
            logger.info(f"  Bookmaker: {betting_info['bookmaker']}")

            if "event_date" in betting_info:
                logger.info(f"  Date/Time: {betting_info['event_date']}")

            # Send confirmation message
            confirmation_text = (
                f"✅ Betting information received (MOCK MODE)!\n"
                f"Code: {betting_info['bet_code']}\n"
                f"Odds: {betting_info['odds']}\n"
                f"Bookmaker: {betting_info['bookmaker']}"
            )

            if "event_date" in betting_info:
                confirmation_text += f"\nDate/Time: {betting_info['event_date'].strftime('%d/%m/%Y %H:%M')}"

            await update.message.reply_text(confirmation_text)
            return

        # Real mode - save to database
        # Get or create punter
        punter = get_or_create_punter(
            db=db,
            name=punter_name,
            telegram_username=str(update.effective_user.id),
            nickname=punter_username
        )

        if not punter:
            logger.error(f"Failed to get or create punter: {punter_name}")
            await update.message.reply_text("❌ Failed to save punter information. Please try again.")
            return

        # Get or create bookmaker
        bookmaker = get_or_create_bookmaker(
            db=db,
            name=betting_info["bookmaker"]
        )

        if not bookmaker:
            logger.error(f"Failed to get or create bookmaker: {betting_info['bookmaker']}")
            await update.message.reply_text("❌ Failed to save bookmaker information. Please try again.")
            return

        # Save betting code
        betting_code = save_betting_code(
            db=db,
            code=betting_info["bet_code"],
            punter_id=punter.id,
            bookmaker_id=bookmaker.id,
            odds=betting_info["odds"],
            event_date=betting_info.get("event_date"),
            notes=f"From Telegram: {message_text}"
        )

        if betting_code:
            logger.info(f"Saved betting code from {punter_name}: {betting_info['bet_code']}")

            # Send confirmation message
            confirmation_text = (
                f"✅ Betting information saved!\n"
                f"Code: {betting_info['bet_code']}\n"
                f"Odds: {betting_info['odds']}\n"
                f"Bookmaker: {betting_info['bookmaker']}"
            )

            if "event_date" in betting_info:
                confirmation_text += f"\nDate/Time: {betting_info['event_date'].strftime('%d/%m/%Y %H:%M')}"

            await update.message.reply_text(confirmation_text)
        else:
            logger.error(f"Failed to save betting code: {betting_info['bet_code']}")
            await update.message.reply_text("❌ Failed to save betting information. Please try again.")

    except Exception as e:
        logger.error(f"Error saving betting information: {str(e)}")

        # Send error message
        await update.message.reply_text(
            f"❌ Error saving betting information: {str(e)}\n"
            f"Please try again later or contact the administrator."
        )

def main() -> None:
    """Start the bot."""
    # Check if token is set
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Telegram bot token not set. Please set TELEGRAM_BOT_TOKEN environment variable.")
        return

    # Create the Application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_betting_info))

    # Start the Bot
    application.run_polling()

    logger.info("Bot started")

if __name__ == "__main__":
    main()
