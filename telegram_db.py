"""
Telegram Bot Database Connection

This module provides a simplified database connection for the Telegram bot.
"""

import os
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get database URL from environment variable or use default (same as main API)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./football.db")

# Create engine
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
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

    def to_dict(self) -> Dict[str, Any]:
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

    def to_dict(self) -> Dict[str, Any]:
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
    status = Column(String(20), default="pending")  # pending, won, lost
    confidence = Column(Integer, nullable=True)  # 1-10 scale
    featured = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # Relationships
    punter = relationship("Punter")
    bookmaker = relationship("Bookmaker")

    def to_dict(self) -> Dict[str, Any]:
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
            "status": self.status,
            "confidence": self.confidence,
            "featured": self.featured,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Initialize database with the correct schema."""
    try:
        # Create tables
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully.")

        # Check if tables were created
        import sqlite3
        conn = sqlite3.connect(DATABASE_URL.replace("sqlite:///", ""))
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

# Database service functions
def get_or_create_punter(db, name, telegram_username=None, nickname=None):
    """Get or create a punter."""
    try:
        # Check if punter exists by telegram username
        if telegram_username:
            punter = db.query(Punter).filter(Punter.telegram_username == telegram_username).first()
            if punter:
                return punter

        # Check if punter exists by name
        punter = db.query(Punter).filter(Punter.name == name).first()
        if punter:
            return punter

        # Create new punter
        punter = Punter(
            name=name,
            nickname=nickname,
            telegram_username=telegram_username,
            country="Unknown",
            specialty="betting_codes",
            verified=False,
            created_at=datetime.now()
        )

        # Add to database
        db.add(punter)
        db.commit()
        db.refresh(punter)

        logger.info(f"Created punter: {name} (ID: {punter.id})")

        return punter
    except Exception as e:
        db.rollback()
        logger.error(f"Error getting or creating punter: {str(e)}")
        return None

def get_or_create_bookmaker(db, name):
    """Get or create a bookmaker."""
    try:
        # Check if bookmaker exists
        bookmaker = db.query(Bookmaker).filter(Bookmaker.name == name).first()
        if bookmaker:
            return bookmaker

        # Create new bookmaker
        bookmaker = Bookmaker(
            name=name,
            created_at=datetime.now()
        )

        # Add to database
        db.add(bookmaker)
        db.commit()
        db.refresh(bookmaker)

        logger.info(f"Created bookmaker: {name} (ID: {bookmaker.id})")

        return bookmaker
    except Exception as e:
        db.rollback()
        logger.error(f"Error getting or creating bookmaker: {str(e)}")
        return None

def save_betting_code(db, code, punter_id, bookmaker_id=None, odds=None, event_date=None, notes=None):
    """Save a betting code."""
    try:
        # Check if betting code already exists
        existing_code = db.query(BettingCode).filter(BettingCode.code == code).first()
        if existing_code:
            logger.info(f"Betting code already exists: {code}")
            return existing_code

        # Create new betting code
        betting_code = BettingCode(
            code=code,
            punter_id=punter_id,
            bookmaker_id=bookmaker_id,
            odds=odds,
            event_date=event_date,
            status="pending",
            confidence=8,  # Default confidence
            featured=False,
            notes=notes,
            created_at=datetime.now()
        )

        # Add to database
        db.add(betting_code)
        db.commit()
        db.refresh(betting_code)

        logger.info(f"Saved betting code: {code} (ID: {betting_code.id})")

        return betting_code
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving betting code: {str(e)}")
        return None
