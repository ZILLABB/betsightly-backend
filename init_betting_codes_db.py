"""
Initialize Betting Codes Database

This script initializes the database with the betting_codes, punters, and bookmakers tables.
"""

import logging
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Create engine
engine = create_engine(
    "sqlite:///data/database.db", connect_args={"check_same_thread": False}
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create base class for models
Base = declarative_base()

# Define models
class Punter(Base):
    """Punter model for storing information about prediction providers."""
    
    __tablename__ = "punters"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    nickname = Column(String(100), nullable=True)
    telegram_username = Column(String(100), nullable=True)
    country = Column(String(100), default="Unknown")
    specialty = Column(String(100), nullable=True)
    verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    def to_dict(self):
        """Convert punter to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "nickname": self.nickname,
            "telegram_username": self.telegram_username,
            "country": self.country,
            "specialty": self.specialty,
            "verified": self.verified,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

class Bookmaker(Base):
    """Bookmaker model for storing information about betting companies."""
    
    __tablename__ = "bookmakers"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    def to_dict(self):
        """Convert bookmaker to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

class BettingCode(Base):
    """BettingCode model for storing betting/booking codes."""
    
    __tablename__ = "betting_codes"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(100), nullable=False)
    punter_id = Column(Integer, ForeignKey("punters.id"), nullable=False)
    bookmaker_id = Column(Integer, ForeignKey("bookmakers.id"), nullable=True)
    odds = Column(Float, nullable=True)
    event_date = Column(DateTime, nullable=True)
    expiry_date = Column(DateTime, nullable=True)
    status = Column(String(20), default="pending")  # pending, won, lost, void
    confidence = Column(Integer, nullable=True)  # 1-10 scale
    featured = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    punter = relationship("Punter")
    bookmaker = relationship("Bookmaker")
    
    def to_dict(self):
        """Convert betting code to dictionary."""
        return {
            "id": self.id,
            "code": self.code,
            "punter_id": self.punter_id,
            "punter_name": self.punter.name if self.punter else None,
            "bookmaker_id": self.bookmaker_id,
            "bookmaker_name": self.bookmaker.name if self.bookmaker else None,
            "odds": self.odds,
            "event_date": self.event_date.isoformat() if self.event_date else None,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "status": self.status,
            "confidence": self.confidence,
            "featured": self.featured,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

def init_db():
    """Initialize database with the correct schema."""
    try:
        # Create tables
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully.")
        
        # Check if tables were created
        import sqlite3
        conn = sqlite3.connect("data/database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        logger.info(f"Tables in the database: {tables}")
        
        # Check if required tables exist
        required_tables = ['punters', 'bookmakers', 'betting_codes']
        for table in required_tables:
            if table in tables:
                logger.info(f"Table {table} exists in the database")
            else:
                logger.warning(f"Table {table} does not exist in the database")
        
        conn.close()
        
        return True
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        return False

if __name__ == "__main__":
    init_db()
