"""
Check Database

This script checks if the betting_codes table exists in the database.
"""

import sqlite3
import os
import logging

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def check_database():
    """Check if the betting_codes table exists in the database."""
    try:
        # Find the database file
        database_files = []
        for root, dirs, files in os.walk('.'):
            for file in files:
                if file.endswith('.db'):
                    database_files.append(os.path.join(root, file))
        
        logger.info(f"Found {len(database_files)} database files: {database_files}")
        
        # Check each database file
        for db_file in database_files:
            logger.info(f"Checking database file: {db_file}")
            
            # Connect to the database
            conn = sqlite3.connect(db_file)
            cursor = conn.cursor()
            
            # Get all tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            
            logger.info(f"Tables in the database: {[table[0] for table in tables]}")
            
            # Check if the betting_codes table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='betting_codes'")
            betting_codes_table = cursor.fetchone()
            
            if betting_codes_table:
                logger.info("The betting_codes table exists in the database.")
                
                # Get the schema of the betting_codes table
                cursor.execute("PRAGMA table_info(betting_codes)")
                schema = cursor.fetchall()
                logger.info(f"Schema of the betting_codes table: {schema}")
                
                # Get the number of rows in the betting_codes table
                cursor.execute("SELECT COUNT(*) FROM betting_codes")
                count = cursor.fetchone()[0]
                logger.info(f"Number of rows in the betting_codes table: {count}")
                
                # Get the first 5 rows of the betting_codes table
                cursor.execute("SELECT * FROM betting_codes LIMIT 5")
                rows = cursor.fetchall()
                logger.info(f"First 5 rows of the betting_codes table: {rows}")
            else:
                logger.warning("The betting_codes table does not exist in the database.")
            
            # Close the connection
            conn.close()
    
    except Exception as e:
        logger.error(f"Error checking database: {str(e)}")

if __name__ == "__main__":
    check_database()
