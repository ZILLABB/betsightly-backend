"""
Punter Model

This module defines the Punter model for storing information about prediction providers.
"""

from datetime import datetime
from typing import Dict, List, Any, Optional

from sqlalchemy import Column, String, DateTime, Integer, Float, Boolean, Text, JSON
from sqlalchemy.orm import relationship

from app.database import Base

class Punter(Base):
    """
    Punter model for storing information about prediction providers.

    Attributes:
        id: Unique identifier
        name: Punter name
        nickname: Punter nickname
        country: Punter's country
        popularity: Popularity rating (1-100)
        specialty: Prediction specialty
        success_rate: Success rate percentage
        image_url: URL to punter image
        social_media: JSON object with social media links
        bio: Punter biography
        verified: Whether the punter is verified
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    __tablename__ = "punters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    nickname = Column(String(100), nullable=True)
    country = Column(String(100), default="Nigeria")
    popularity = Column(Integer, default=0)  # 1-100 scale
    specialty = Column(String(100), nullable=True)
    success_rate = Column(Float, nullable=True)  # Percentage
    image_url = Column(String(255), nullable=True)
    social_media = Column(JSON, nullable=True)  # Store social media links
    bio = Column(Text, nullable=True)
    verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # Relationships will be set up after all models are defined

    def __init__(
        self,
        name: str,
        nickname: Optional[str] = None,
        country: str = "Nigeria",
        popularity: int = 0,
        specialty: Optional[str] = None,
        success_rate: Optional[float] = None,
        image_url: Optional[str] = None,
        social_media: Optional[Dict[str, str]] = None,
        bio: Optional[str] = None,
        verified: bool = False,
        created_at: Optional[datetime] = None
    ):
        """
        Initialize a punter.

        Args:
            name: Punter name
            nickname: Punter nickname
            country: Punter's country
            popularity: Popularity rating (1-100)
            specialty: Prediction specialty
            success_rate: Success rate percentage
            image_url: URL to punter image
            social_media: Dictionary with social media links
            bio: Punter biography
            verified: Whether the punter is verified
            created_at: Creation timestamp
        """
        self.name = name
        self.nickname = nickname
        self.country = country
        self.popularity = popularity
        self.specialty = specialty
        self.success_rate = success_rate
        self.image_url = image_url
        self.social_media = social_media
        self.bio = bio
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
            "country": self.country,
            "popularity": self.popularity,
            "specialty": self.specialty,
            "success_rate": self.success_rate,
            "image_url": self.image_url,
            "social_media": self.social_media,
            "bio": self.bio,
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
