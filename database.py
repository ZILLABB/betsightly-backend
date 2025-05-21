"""
Database configuration for the application.
"""

import os
import sqlite3
import logging
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Import settings
from app.utils.config import settings

# Get database URL from settings
DATABASE_URL = settings.database.URL
DB_FILE = DATABASE_URL.replace("sqlite:///", "")

# Create engine
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create base class for models
Base = declarative_base()

def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Initialize database with the correct schema."""
    # SQL to create fixtures table
    CREATE_FIXTURES_TABLE = """
    CREATE TABLE IF NOT EXISTS fixtures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fixture_id INTEGER UNIQUE,
        date TIMESTAMP,
        league_id INTEGER,
        league_name TEXT,
        home_team_id INTEGER,
        home_team TEXT,
        away_team_id INTEGER,
        away_team TEXT,
        home_odds REAL DEFAULT 0,
        draw_odds REAL DEFAULT 0,
        away_odds REAL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    # SQL to create predictions table
    CREATE_PREDICTIONS_TABLE = """
    CREATE TABLE IF NOT EXISTS predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fixture_id INTEGER,
        match_result_pred TEXT,
        home_win_pred REAL,
        draw_pred REAL,
        away_win_pred REAL,
        over_under_pred TEXT,
        over_2_5_pred REAL,
        under_2_5_pred REAL,
        btts_pred TEXT,
        btts_yes_pred REAL,
        btts_no_pred REAL,
        prediction_type TEXT,
        odds REAL DEFAULT 0,
        confidence REAL DEFAULT 0,
        combined_odds REAL DEFAULT 0,
        combined_confidence REAL DEFAULT 0,
        combo_id TEXT,
        rollover_day INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (fixture_id) REFERENCES fixtures (fixture_id)
    );
    """

    # SQL to create indexes
    CREATE_INDEXES = [
        "CREATE INDEX IF NOT EXISTS idx_fixtures_fixture_id ON fixtures (fixture_id);",
        "CREATE INDEX IF NOT EXISTS idx_fixtures_date ON fixtures (date);",
        "CREATE INDEX IF NOT EXISTS idx_fixtures_league_id ON fixtures (league_id);",
        "CREATE INDEX IF NOT EXISTS idx_predictions_fixture_id ON predictions (fixture_id);",
        "CREATE INDEX IF NOT EXISTS idx_predictions_prediction_type ON predictions (prediction_type);"
    ]

    try:
        # Connect to database
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Create tables
        logger.info("Creating fixtures table...")
        cursor.execute(CREATE_FIXTURES_TABLE)

        logger.info("Creating predictions table...")
        cursor.execute(CREATE_PREDICTIONS_TABLE)

        # Create indexes
        logger.info("Creating indexes...")
        for index_sql in CREATE_INDEXES:
            cursor.execute(index_sql)

        # Commit changes
        conn.commit()

        # Verify tables were created
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        logger.info(f"Tables created: {[table[0] for table in tables]}")

        # Verify columns in predictions table
        cursor.execute("PRAGMA table_info(predictions);")
        columns = cursor.fetchall()
        logger.info("Prediction table columns:")
        for column in columns:
            logger.info(f"- {column[1]} ({column[2]})")

        # Close connection
        conn.close()

        logger.info("Database initialized successfully.")

        # Import models to register them with the Base
        from app.models.fixture import Fixture
        from app.models.prediction import Prediction
        from app.models.punter import Punter
        from app.models.bookmaker import Bookmaker
        from app.models.betting_code import BettingCode

        # Also create tables using SQLAlchemy
        Base.metadata.create_all(bind=engine)
        logger.info("SQLAlchemy tables created.")

        return True

    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        return False
