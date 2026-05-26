"""
Telegram Bot Database Connection

Uses the SAME database and models as the main API so that punters
created via Telegram appear in the frontend automatically.
"""

import logging
from datetime import datetime
from typing import Optional

from database import SessionLocal
from punter import Punter
from bookmaker import Bookmaker
from betting_code import BettingCode

logger = logging.getLogger(__name__)


def get_db():
    """Get database session (same DB as main API)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Database is initialized by the main app — nothing to do here."""
    logger.info("Telegram DB: using main application database")
    return True


def get_or_create_punter(db, name, telegram_username=None, nickname=None):
    """Get or create a punter in the MAIN punters table."""
    try:
        # Look up by telegram username first
        if telegram_username:
            punter = db.query(Punter).filter(
                Punter.telegram_username == telegram_username
            ).first()
            if punter:
                return punter

        # Fall back to name lookup
        punter = db.query(Punter).filter(Punter.name == name).first()
        if punter:
            # Update telegram_username if we didn't have it
            if telegram_username and not punter.telegram_username:
                punter.telegram_username = telegram_username
                db.commit()
            return punter

        # Create new punter with all fields the frontend needs
        punter = Punter(
            name=name,
            nickname=nickname,
            telegram_username=telegram_username,
            country="Nigeria",
            specialty="betting_codes",
            verified=False,
        )

        db.add(punter)
        db.commit()
        db.refresh(punter)

        logger.info(f"Created punter: {name} (ID: {punter.id}, telegram: {telegram_username})")
        return punter

    except Exception as e:
        db.rollback()
        logger.error(f"Error getting or creating punter: {str(e)}")
        return None


def get_or_create_bookmaker(db, name):
    """Get or create a bookmaker."""
    try:
        bookmaker = db.query(Bookmaker).filter(Bookmaker.name == name).first()
        if bookmaker:
            return bookmaker

        bookmaker = Bookmaker(name=name)
        db.add(bookmaker)
        db.commit()
        db.refresh(bookmaker)

        logger.info(f"Created bookmaker: {name} (ID: {bookmaker.id})")
        return bookmaker

    except Exception as e:
        db.rollback()
        logger.error(f"Error getting or creating bookmaker: {str(e)}")
        return None


def save_betting_code(db, code, punter_id, bookmaker_id=None, odds=None,
                      event_date=None, notes=None):
    """Save a betting code and update the punter's popularity."""
    try:
        existing = db.query(BettingCode).filter(BettingCode.code == code).first()
        if existing:
            logger.info(f"Betting code already exists: {code}")
            return existing

        betting_code = BettingCode(
            code=code,
            punter_id=punter_id,
            bookmaker_id=bookmaker_id,
            odds=odds,
            event_date=event_date,
            status="pending",
            confidence=8,
            featured=False,
            notes=notes,
        )

        db.add(betting_code)

        # Update punter popularity (total codes submitted)
        punter = db.query(Punter).get(punter_id)
        if punter:
            punter.popularity = (punter.popularity or 0) + 1
            punter.updated_at = datetime.now()

        db.commit()
        db.refresh(betting_code)

        logger.info(f"Saved betting code: {code} (ID: {betting_code.id})")
        return betting_code

    except Exception as e:
        db.rollback()
        logger.error(f"Error saving betting code: {str(e)}")
        return None
