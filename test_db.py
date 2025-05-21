#!/usr/bin/env python3
"""
Test Database Script

This script tests the database by querying punters and bookmakers.
"""

import os
import sys
import logging

# Add the parent directory to the path so we can import from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.common import setup_logging
from app.database import get_db
from app.models.punter import Punter
from app.models.bookmaker import Bookmaker
from app.models.betting_code import BettingCode

# Set up logging
logger = setup_logging(__name__)

def test_database():
    """Test the database by querying punters and bookmakers."""
    try:
        logger.info("Testing database...")
        
        # Get database session
        db = next(get_db())
        
        # Query punters
        punters = db.query(Punter).all()
        logger.info(f"Found {len(punters)} punters:")
        for punter in punters[:5]:  # Show first 5 punters
            logger.info(f"- {punter.name} ({punter.nickname}): {punter.specialty}")
        
        # Query bookmakers
        bookmakers = db.query(Bookmaker).all()
        logger.info(f"Found {len(bookmakers)} bookmakers:")
        for bookmaker in bookmakers[:5]:  # Show first 5 bookmakers
            logger.info(f"- {bookmaker.name} ({bookmaker.country})")
        
        # Create a test betting code
        if punters and bookmakers:
            logger.info("Creating test betting code...")
            
            # Check if test code already exists
            test_code = db.query(BettingCode).filter(BettingCode.code == "TEST123").first()
            
            if not test_code:
                # Create new test code
                test_code = BettingCode(
                    code="TEST123",
                    punter_id=punters[0].id,
                    bookmaker_id=bookmakers[0].id,
                    odds=2.0,
                    status="pending",
                    confidence=8,
                    featured=True,
                    notes="Test betting code"
                )
                
                # Add to database
                db.add(test_code)
                db.commit()
                db.refresh(test_code)
                
                logger.info(f"Created test betting code: {test_code.code}")
            else:
                logger.info(f"Test betting code already exists: {test_code.code}")
            
            # Query betting codes
            betting_codes = db.query(BettingCode).all()
            logger.info(f"Found {len(betting_codes)} betting codes:")
            for code in betting_codes[:5]:  # Show first 5 betting codes
                logger.info(f"- {code.code} (Punter: {code.punter.name}, Bookmaker: {code.bookmaker.name if code.bookmaker else 'None'})")
        
        logger.info("Database test completed successfully.")
        
    except Exception as e:
        logger.error(f"Error testing database: {str(e)}")
        raise

def main():
    """Main function."""
    try:
        test_database()
    except Exception as e:
        logger.error(f"Error in main function: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
