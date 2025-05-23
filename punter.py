"""
Punter Model

This module defines the Punter model for storing information about prediction providers.
"""

from datetime import datetime
from typing import Dict, Any, Optional

from sqlalchemy import Column, String, DateTime, Integer, Boolean
from sqlalchemy.orm import relationship

from database import Base

class Punter(Base):
    """
    Punter model for storing information about prediction providers.

    Attributes:
        id: Unique identifier
        name: Punter name
        nickname: Punter nickname
        telegram_username: Telegram username
        country: Punter's country
        specialty: Prediction specialty
        verified: Whether the punter is verified
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    __tablename__ = "punters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    nickname = Column(String(100), nullable=True)
    telegram_username = Column(String(100), nullable=True)
    country = Column(String(100), default="Nigeria")
    specialty = Column(String(100), nullable=True)
    verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # Relationships
    betting_codes = relationship("BettingCode", lazy="select", overlaps="punter")

    def __init__(
        self,
        name: str,
        nickname: Optional[str] = None,
        telegram_username: Optional[str] = None,
        country: str = "Nigeria",
        specialty: Optional[str] = None,
        verified: bool = False,
        created_at: Optional[datetime] = None
    ):
        """
        Initialize a punter.

        Args:
            name: Punter name
            nickname: Punter nickname
            telegram_username: Telegram username
            country: Punter's country
            specialty: Prediction specialty
            verified: Whether the punter is verified
            created_at: Creation timestamp
        """
        self.name = name
        self.nickname = nickname
        self.telegram_username = telegram_username
        self.country = country
        self.specialty = specialty
        self.verified = verified
        self.created_at = created_at or datetime.now()
        self.updated_at = self.created_at

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert punter to dictionary.

        Returns:
            Dictionary representation of punter
        """
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

    def __repr__(self) -> str:
        """
        Get string representation of punter.

        Returns:
            String representation
        """
        return f"<Punter(id={self.id}, name='{self.name}', specialty='{self.specialty}')>"
