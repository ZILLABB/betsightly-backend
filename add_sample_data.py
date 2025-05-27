"""
Add Sample Data to Betting Codes Database

This script adds sample data to the betting_codes, punters, and bookmakers tables.
"""

import logging
from datetime import datetime, timedelta
from init_betting_codes_db import SessionLocal, Punter, Bookmaker, BettingCode

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def add_sample_data():
    """Add sample data to the database."""
    try:
        # Create database session
        db = SessionLocal()
        
        # Add sample punters
        punters = [
            {
                "name": "John Doe",
                "nickname": "JD",
                "telegram_username": "12345678",
                "country": "United States",
                "specialty": "match_result",
                "verified": True
            },
            {
                "name": "Jane Smith",
                "nickname": "JS",
                "telegram_username": "87654321",
                "country": "United Kingdom",
                "specialty": "over_under",
                "verified": True
            },
            {
                "name": "Bob Johnson",
                "nickname": "BJ",
                "telegram_username": "11223344",
                "country": "Canada",
                "specialty": "btts",
                "verified": False
            }
        ]
        
        for punter_data in punters:
            # Check if punter already exists
            existing_punter = db.query(Punter).filter(Punter.name == punter_data["name"]).first()
            
            if not existing_punter:
                # Create new punter
                punter = Punter(**punter_data)
                db.add(punter)
                logger.info(f"Added punter: {punter_data['name']}")
            else:
                logger.info(f"Punter already exists: {punter_data['name']}")
        
        # Commit changes to get punter IDs
        db.commit()
        
        # Add sample bookmakers
        bookmakers = [
            {"name": "Bet365"},
            {"name": "Betway"},
            {"name": "1xBet"},
            {"name": "SportyBet"}
        ]
        
        for bookmaker_data in bookmakers:
            # Check if bookmaker already exists
            existing_bookmaker = db.query(Bookmaker).filter(Bookmaker.name == bookmaker_data["name"]).first()
            
            if not existing_bookmaker:
                # Create new bookmaker
                bookmaker = Bookmaker(**bookmaker_data)
                db.add(bookmaker)
                logger.info(f"Added bookmaker: {bookmaker_data['name']}")
            else:
                logger.info(f"Bookmaker already exists: {bookmaker_data['name']}")
        
        # Commit changes to get bookmaker IDs
        db.commit()
        
        # Get punters and bookmakers
        punters = db.query(Punter).all()
        bookmakers = db.query(Bookmaker).all()
        
        # Add sample betting codes
        betting_codes = [
            {
                "code": "ABC123",
                "punter_id": punters[0].id,
                "bookmaker_id": bookmakers[0].id,
                "odds": 1.85,
                "event_date": datetime.now() + timedelta(days=1),
                "status": "pending",
                "confidence": 8,
                "featured": True,
                "notes": "Sample betting code 1"
            },
            {
                "code": "DEF456",
                "punter_id": punters[1].id,
                "bookmaker_id": bookmakers[1].id,
                "odds": 2.5,
                "event_date": datetime.now() + timedelta(days=2),
                "status": "pending",
                "confidence": 7,
                "featured": False,
                "notes": "Sample betting code 2"
            },
            {
                "code": "GHI789",
                "punter_id": punters[2].id,
                "bookmaker_id": bookmakers[2].id,
                "odds": 3.0,
                "event_date": datetime.now() + timedelta(days=3),
                "status": "pending",
                "confidence": 6,
                "featured": False,
                "notes": "Sample betting code 3"
            },
            {
                "code": "JKL012",
                "punter_id": punters[0].id,
                "bookmaker_id": bookmakers[3].id,
                "odds": 1.5,
                "event_date": datetime.now() + timedelta(days=4),
                "status": "pending",
                "confidence": 9,
                "featured": True,
                "notes": "Sample betting code 4"
            },
            {
                "code": "MNO345",
                "punter_id": punters[1].id,
                "bookmaker_id": bookmakers[0].id,
                "odds": 2.0,
                "event_date": datetime.now() + timedelta(days=5),
                "status": "pending",
                "confidence": 8,
                "featured": False,
                "notes": "Sample betting code 5"
            }
        ]
        
        for betting_code_data in betting_codes:
            # Check if betting code already exists
            existing_code = db.query(BettingCode).filter(BettingCode.code == betting_code_data["code"]).first()
            
            if not existing_code:
                # Create new betting code
                betting_code = BettingCode(**betting_code_data)
                db.add(betting_code)
                logger.info(f"Added betting code: {betting_code_data['code']}")
            else:
                logger.info(f"Betting code already exists: {betting_code_data['code']}")
        
        # Commit changes
        db.commit()
        
        # Close session
        db.close()
        
        logger.info("Sample data added successfully.")
        return True
    except Exception as e:
        logger.error(f"Error adding sample data: {str(e)}")
        return False

if __name__ == "__main__":
    add_sample_data()
