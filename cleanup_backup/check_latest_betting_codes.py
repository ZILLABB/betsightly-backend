"""
Check Latest Betting Codes

This script checks the latest betting codes in the database.
"""

import sqlite3
import logging
import json
from datetime import datetime

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def check_latest_betting_codes():
    """Check the latest betting codes in the database."""
    try:
        # Connect to the database
        conn = sqlite3.connect('real_predictions.db')
        cursor = conn.cursor()
        
        # Get the number of betting codes
        cursor.execute("SELECT COUNT(*) FROM betting_codes")
        count = cursor.fetchone()[0]
        logger.info(f"Total betting codes in the database: {count}")
        
        if count == 0:
            logger.warning("No betting codes found in the database")
            return
        
        # Get the latest betting codes
        cursor.execute("""
            SELECT 
                bc.id, bc.code, bc.punter_id, bc.bookmaker_id, bc.odds, bc.event_date, 
                bc.status, bc.confidence, bc.featured, bc.notes, bc.created_at, bc.updated_at,
                p.name as punter_name, p.nickname as punter_nickname,
                b.name as bookmaker_name
            FROM betting_codes bc
            LEFT JOIN punters p ON bc.punter_id = p.id
            LEFT JOIN bookmakers b ON bc.bookmaker_id = b.id
            ORDER BY bc.created_at DESC
            LIMIT 5
        """)
        
        codes = cursor.fetchall()
        
        # Define column names
        columns = [
            'id', 'code', 'punter_id', 'bookmaker_id', 'odds', 'event_date', 
            'status', 'confidence', 'featured', 'notes', 'created_at', 'updated_at',
            'punter_name', 'punter_nickname', 'bookmaker_name'
        ]
        
        # Convert to dictionaries
        codes_dict = []
        for code in codes:
            code_dict = dict(zip(columns, code))
            codes_dict.append(code_dict)
        
        # Log the latest betting codes
        logger.info(f"Latest {len(codes_dict)} betting codes:")
        
        for i, code_dict in enumerate(codes_dict):
            logger.info(f"Betting code {i+1}:")
            logger.info(f"  ID: {code_dict['id']}")
            logger.info(f"  Code: {code_dict['code']}")
            logger.info(f"  Punter: {code_dict['punter_name']} (ID: {code_dict['punter_id']})")
            logger.info(f"  Bookmaker: {code_dict['bookmaker_name']} (ID: {code_dict['bookmaker_id']})")
            logger.info(f"  Odds: {code_dict['odds']}")
            logger.info(f"  Event Date: {code_dict['event_date']}")
            logger.info(f"  Status: {code_dict['status']}")
            logger.info(f"  Created At: {code_dict['created_at']}")
            logger.info(f"  Updated At: {code_dict['updated_at']}")
            logger.info(f"  Notes: {code_dict['notes']}")
            logger.info("")
        
        # Close the connection
        conn.close()
        
        logger.info("Database check completed")
    
    except Exception as e:
        logger.error(f"Error checking database: {str(e)}")

if __name__ == "__main__":
    check_latest_betting_codes()
