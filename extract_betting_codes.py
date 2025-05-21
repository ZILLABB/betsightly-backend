#!/usr/bin/env python3
"""
Extract Betting Codes Script

This script extracts betting/booking codes and punter names from Telegram groups.
It's designed to be run as a background service to continuously collect betting codes.
"""

import os
import sys
import argparse
import logging
import json
import requests
import time
import re
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union, Tuple

# Add the parent directory to the path so we can import from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.common import setup_logging
from app.utils.config import settings
from app.database import init_db, get_db
from sqlalchemy.orm import Session
from sqlalchemy import Column, String, DateTime, Text, Integer, Float, Boolean, ForeignKey, func, desc
from app.database import Base

# Set up logging
logger = setup_logging(__name__)

class BettingCode(Base):
    """
    Model for storing betting codes.
    
    Attributes:
        id: Unique identifier
        code: Betting/booking code
        punter_name: Name of the punter who provided the code
        source: Source of the code (e.g., telegram)
        source_id: ID of the source message/post
        source_text: Original text of the message
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """
    
    __tablename__ = "betting_codes"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(100), nullable=False)
    punter_name = Column(String(100), nullable=False)
    source = Column(String(50), nullable=True)
    source_id = Column(String(100), nullable=True)
    source_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert betting code to dictionary.
        
        Returns:
            Dictionary representation of betting code
        """
        return {
            "id": self.id,
            "code": self.code,
            "punter_name": self.punter_name,
            "source": self.source,
            "source_id": self.source_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

class BettingCodeService:
    """
    Service for managing betting codes.
    
    Features:
    - Create and retrieve betting codes
    - Check for duplicate codes
    """
    
    def __init__(self, db: Session):
        """
        Initialize the betting code service.
        
        Args:
            db: Database session
        """
        self.db = db
    
    def get_all_betting_codes(self, limit: int = 100, skip: int = 0) -> List[Dict[str, Any]]:
        """
        Get all betting codes.
        
        Args:
            limit: Maximum number of codes to return
            skip: Number of codes to skip
            
        Returns:
            List of betting codes
        """
        try:
            codes = (
                self.db.query(BettingCode)
                .order_by(desc(BettingCode.created_at))
                .offset(skip)
                .limit(limit)
                .all()
            )
            
            return [code.to_dict() for code in codes]
            
        except Exception as e:
            logger.error(f"Error getting all betting codes: {str(e)}")
            return []
    
    def get_betting_code_by_id(self, code_id: int) -> Optional[Dict[str, Any]]:
        """
        Get betting code by ID.
        
        Args:
            code_id: Betting code ID
            
        Returns:
            Betting code data or None if not found
        """
        try:
            code = self.db.query(BettingCode).filter(BettingCode.id == code_id).first()
            
            if not code:
                return None
            
            return code.to_dict()
            
        except Exception as e:
            logger.error(f"Error getting betting code by ID {code_id}: {str(e)}")
            return None
    
    def get_betting_code_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        """
        Get betting code by code value.
        
        Args:
            code: Betting code value
            
        Returns:
            Betting code data or None if not found
        """
        try:
            code_obj = self.db.query(BettingCode).filter(BettingCode.code == code).first()
            
            if not code_obj:
                return None
            
            return code_obj.to_dict()
            
        except Exception as e:
            logger.error(f"Error getting betting code by code {code}: {str(e)}")
            return None
    
    def create_betting_code(self, code_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Create a new betting code.
        
        Args:
            code_data: Betting code data
            
        Returns:
            Created betting code data or None if creation failed
        """
        try:
            # Check if code already exists
            existing_code = self.get_betting_code_by_code(code_data["code"])
            
            if existing_code:
                logger.info(f"Betting code {code_data['code']} already exists")
                return existing_code
            
            # Create new betting code
            code = BettingCode(
                code=code_data["code"],
                punter_name=code_data["punter_name"],
                source=code_data.get("source"),
                source_id=code_data.get("source_id"),
                source_text=code_data.get("source_text"),
                created_at=datetime.now()
            )
            
            # Add to database
            self.db.add(code)
            self.db.commit()
            self.db.refresh(code)
            
            logger.info(f"Created betting code: {code.code} from {code.punter_name}")
            
            return code.to_dict()
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error creating betting code: {str(e)}")
            return None

class TelegramCodeExtractor:
    """
    Extractor for betting codes from Telegram groups.
    
    Features:
    - Connect to Telegram Bot API
    - Monitor groups for betting codes
    - Extract codes and punter names
    - Save codes to the database
    """
    
    def __init__(self, db: Session):
        """
        Initialize the Telegram code extractor.
        
        Args:
            db: Database session
        """
        self.bot_token = settings.telegram.BOT_TOKEN
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.last_update_id = 0
        self.running = False
        self.groups_to_monitor = []
        self.betting_code_service = BettingCodeService(db)
        
        # Cache directory for extracted messages
        self.cache_dir = os.path.join(settings.telegram.CACHE_DIR, "betting_codes")
        os.makedirs(self.cache_dir, exist_ok=True)
    
    def get_me(self) -> Dict[str, Any]:
        """
        Get information about the bot.
        
        Returns:
            Dictionary with bot information
        """
        try:
            response = requests.get(f"{self.base_url}/getMe")
            data = response.json()
            
            if data.get("ok"):
                return data.get("result", {})
            else:
                logger.error(f"Error getting bot info: {data.get('description')}")
                return {}
                
        except Exception as e:
            logger.error(f"Error getting bot info: {str(e)}")
            return {}
    
    def get_updates(self, offset: int = 0, timeout: int = 30) -> List[Dict[str, Any]]:
        """
        Get updates from Telegram.
        
        Args:
            offset: Identifier of the first update to be returned
            timeout: Timeout in seconds for long polling
            
        Returns:
            List of updates
        """
        try:
            params = {
                "offset": offset,
                "timeout": timeout,
                "allowed_updates": ["message", "channel_post"]
            }
            
            response = requests.get(f"{self.base_url}/getUpdates", params=params)
            data = response.json()
            
            if data.get("ok"):
                return data.get("result", [])
            else:
                logger.error(f"Error getting updates: {data.get('description')}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting updates: {str(e)}")
            return []
    
    def extract_betting_code(self, text: str) -> Optional[str]:
        """
        Extract betting code from text.
        
        Args:
            text: Text to extract code from
            
        Returns:
            Betting code or None if not found
        """
        try:
            # Common patterns for betting codes
            patterns = [
                r'(?:code|booking code|bet code|booking|code:)\s*([A-Za-z0-9]{5,20})',  # Code: ABC123
                r'(?:code|booking code|bet code|booking|code)[\s:]*([A-Za-z0-9]{5,20})',  # Code ABC123
                r'([A-Za-z0-9]{5,20})\s*(?:is the code|is the booking code)',  # ABC123 is the code
                r'#([A-Za-z0-9]{5,20})',  # #ABC123
                r'[^\w]([A-Za-z0-9]{8,12})[^\w]'  # Standalone alphanumeric code
            ]
            
            # Try each pattern
            for pattern in patterns:
                matches = re.search(pattern, text, re.IGNORECASE)
                if matches:
                    return matches.group(1).strip()
            
            return None
            
        except Exception as e:
            logger.error(f"Error extracting betting code: {str(e)}")
            return None
    
    def extract_punter_name(self, message: Dict[str, Any]) -> str:
        """
        Extract punter name from message.
        
        Args:
            message: Message data
            
        Returns:
            Punter name
        """
        try:
            # Try to get name from message text
            text = message.get("text", "")
            
            # Look for patterns like "Punter: John Doe" or "From: John Doe"
            name_patterns = [
                r'(?:punter|tipster|from|by|source|name)[\s:]+([A-Za-z0-9\s]{3,30}?)(?:\n|$|,|\.|!)',
                r'([A-Za-z0-9\s]{3,30}?)[\s:](?:tips|predictions|forecast)'
            ]
            
            for pattern in name_patterns:
                matches = re.search(pattern, text, re.IGNORECASE)
                if matches:
                    return matches.group(1).strip()
            
            # If no name found in text, use sender name
            from_user = message.get("from", {})
            if from_user:
                first_name = from_user.get("first_name", "")
                last_name = from_user.get("last_name", "")
                
                if first_name and last_name:
                    return f"{first_name} {last_name}"
                elif first_name:
                    return first_name
                elif last_name:
                    return last_name
            
            # If no sender name, use chat title
            chat = message.get("chat", {})
            if chat:
                title = chat.get("title")
                if title:
                    return title
            
            # Default name
            return "Unknown Punter"
            
        except Exception as e:
            logger.error(f"Error extracting punter name: {str(e)}")
            return "Unknown Punter"
    
    def process_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Process a message from a group.
        
        Args:
            message: Message data
            
        Returns:
            Processed betting code or None if not a valid code
        """
        try:
            # Skip messages without text
            if not message.get("text"):
                return None
            
            # Extract message text
            text = message.get("text", "")
            
            # Extract betting code
            code = self.extract_betting_code(text)
            
            if not code:
                return None
            
            # Extract punter name
            punter_name = self.extract_punter_name(message)
            
            # Create betting code data
            code_data = {
                "code": code,
                "punter_name": punter_name,
                "source": "telegram",
                "source_id": str(message.get("message_id")),
                "source_text": text
            }
            
            # Save betting code
            saved_code = self.betting_code_service.create_betting_code(code_data)
            
            if not saved_code:
                logger.error(f"Failed to save betting code: {code}")
                return None
            
            logger.info(f"Saved betting code: {code} from {punter_name}")
            
            return saved_code
            
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
            return None
    
    def add_group_to_monitor(self, group_id: Union[int, str]) -> bool:
        """
        Add a group to monitor.
        
        Args:
            group_id: Group ID or username
            
        Returns:
            True if added successfully, False otherwise
        """
        try:
            # Add to list of groups to monitor
            if group_id not in self.groups_to_monitor:
                self.groups_to_monitor.append(group_id)
                logger.info(f"Added group to monitor: {group_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error adding group to monitor: {str(e)}")
            return False
    
    def run(self, groups: List[Union[int, str]] = None):
        """
        Run the code extractor.
        
        Args:
            groups: List of group IDs or usernames to monitor
        """
        try:
            # Get bot info
            bot_info = self.get_me()
            
            if not bot_info:
                logger.error("Failed to get bot info. Check your bot token.")
                return
            
            logger.info(f"Bot started: @{bot_info.get('username')} ({bot_info.get('first_name')})")
            
            # Add groups to monitor
            if groups:
                for group in groups:
                    self.add_group_to_monitor(group)
            
            # Set running flag
            self.running = True
            
            # Main loop
            while self.running:
                try:
                    # Get updates
                    updates = self.get_updates(offset=self.last_update_id + 1)
                    
                    # Process updates
                    for update in updates:
                        # Update last update ID
                        self.last_update_id = max(self.last_update_id, update.get("update_id", 0))
                        
                        # Get message or channel post
                        message = update.get("message") or update.get("channel_post")
                        
                        if not message:
                            continue
                        
                        # Get chat ID
                        chat_id = message.get("chat", {}).get("id")
                        
                        # Process message if it's from a monitored group or if we're not monitoring specific groups
                        if not self.groups_to_monitor or chat_id in self.groups_to_monitor or str(chat_id) in self.groups_to_monitor:
                            self.process_message(message)
                    
                    # Sleep to avoid excessive API calls
                    time.sleep(1)
                    
                except Exception as e:
                    logger.error(f"Error in main loop: {str(e)}")
                    time.sleep(5)
            
        except KeyboardInterrupt:
            logger.info("Extractor stopped by user")
            self.running = False
            
        except Exception as e:
            logger.error(f"Error running extractor: {str(e)}")
            self.running = False

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Extract betting codes from Telegram groups")
    
    parser.add_argument(
        "--groups",
        type=str,
        help="Comma-separated list of group IDs or usernames to monitor"
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    return parser.parse_args()

def main():
    """Main function."""
    # Parse arguments
    args = parse_arguments()
    
    # Set log level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Initialize database
    init_db()
    
    # Get database session
    db = next(get_db())
    
    # Parse groups
    groups = args.groups.split(",") if args.groups else None
    
    # Create and run extractor
    extractor = TelegramCodeExtractor(db)
    extractor.run(groups)

if __name__ == "__main__":
    main()
