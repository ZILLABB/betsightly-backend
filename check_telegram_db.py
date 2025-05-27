"""
Check Telegram Database

This script checks the Telegram database to see if it has the correct tables and data.
"""

import sqlite3
import logging
from datetime import datetime

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def check_database():
    """Check the Telegram database."""
    try:
        # Connect to the database
        conn = sqlite3.connect('real_predictions.db')
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        logger.info(f"Tables in the database: {tables}")
        
        # Check if the required tables exist
        required_tables = ['punters', 'bookmakers', 'betting_codes']
        
        for table in required_tables:
            if (table,) not in tables:
                logger.warning(f"Table {table} does not exist in the database")
            else:
                logger.info(f"Table {table} exists in the database")
                
                # Get the number of rows in the table
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                logger.info(f"Table {table} has {count} rows")
                
                # Get the schema of the table
                cursor.execute(f"PRAGMA table_info({table})")
                schema = cursor.fetchall()
                logger.info(f"Schema of table {table}: {schema}")
                
                # Get the first 5 rows of the table
                cursor.execute(f"SELECT * FROM {table} LIMIT 5")
                rows = cursor.fetchall()
                logger.info(f"First 5 rows of table {table}: {rows}")
        
        # Close the connection
        conn.close()
        
        logger.info("Database check completed")
    
    except Exception as e:
        logger.error(f"Error checking database: {str(e)}")

if __name__ == "__main__":
    check_database()
