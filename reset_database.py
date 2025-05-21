#!/usr/bin/env python3
"""
Reset Database Script

This script drops all tables and recreates them.
"""

import os
import sys
import logging
import sqlite3
from sqlalchemy import inspect, MetaData, create_engine

# Add the parent directory to the path so we can import from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.common import setup_logging
from app.utils.config import settings
from app.database import Base, engine, init_db

# Set up logging
logger = setup_logging(__name__)

def reset_database():
    """Reset the database by dropping all tables and recreating them."""
    try:
        logger.info("Resetting database...")

        # Get database path
        db_path = settings.database.URL.replace("sqlite:///", "")

        # Check if database exists
        if not os.path.exists(db_path):
            logger.info(f"Database file {db_path} does not exist. Creating new database.")
            init_db()
            return

        # Get all table names
        inspector = inspect(engine)
        table_names = inspector.get_table_names()

        if not table_names:
            logger.info("No tables found in database. Creating new tables.")
            init_db()
            return

        # Drop all tables
        logger.info(f"Found tables: {table_names}")
        logger.info("Dropping all tables...")

        # Use SQLite directly to drop tables
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Disable foreign key constraints
        cursor.execute("PRAGMA foreign_keys = OFF")

        # Drop each table
        for table_name in table_names:
            cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
            logger.info(f"Dropped table: {table_name}")

        # Commit changes and close connection
        conn.commit()
        conn.close()

        # Recreate tables
        logger.info("Recreating tables...")
        init_db()

        logger.info("Database reset successfully.")

    except Exception as e:
        logger.error(f"Error resetting database: {str(e)}")
        raise

def main():
    """Main function."""
    try:
        reset_database()
    except Exception as e:
        logger.error(f"Error in main function: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
