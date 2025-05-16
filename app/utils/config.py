"""
Configuration

This module contains the configuration settings for the application.
"""

import os
import sys
import logging
from typing import Dict, List, Any, Union
from pydantic import Field
from pydantic_settings import BaseSettings
from datetime import datetime

# Set up logging
logger = logging.getLogger(__name__)

class APIFootballSettings(BaseSettings):
    """API Football settings."""

    API_KEY: str = Field(default="")
    API_HOST: str = Field(default="api-football-v1.p.rapidapi.com")
    BASE_URL: str = Field(default="https://api-football-v1.p.rapidapi.com/v3")
    DAILY_LIMIT: int = Field(default=100)

class DatabaseSettings(BaseSettings):
    """Database settings."""

    URL: str = Field(default="sqlite:///data/database.db")
    ECHO: bool = Field(default=False)
    POOL_SIZE: int = Field(default=5)
    MAX_OVERFLOW: int = Field(default=10)

class MLSettings(BaseSettings):
    """Machine learning settings."""

    MODEL_DIR: str = Field(default="models")
    DATA_DIR: str = Field(default="data")
    CACHE_DIR: str = Field(default="app/ml/cache")
    FEATURE_CACHE_EXPIRY: int = Field(default=24)  # Hours

class OddsCategories(BaseSettings):
    """Odds categories settings."""

    TWO_ODDS_MIN: float = Field(default=1.0)
    TWO_ODDS_MAX: float = Field(default=2.0)
    TWO_ODDS_MIN_CONFIDENCE: float = Field(default=50.0)
    TWO_ODDS_LIMIT: int = Field(default=10)

    FIVE_ODDS_MIN: float = Field(default=2.0)
    FIVE_ODDS_MAX: float = Field(default=5.0)
    FIVE_ODDS_MIN_CONFIDENCE: float = Field(default=40.0)
    FIVE_ODDS_LIMIT: int = Field(default=5)

    TEN_ODDS_MIN: float = Field(default=5.0)
    TEN_ODDS_MAX: float = Field(default=10.0)
    TEN_ODDS_MIN_CONFIDENCE: float = Field(default=30.0)
    TEN_ODDS_LIMIT: int = Field(default=3)

    ROLLOVER_MIN: float = Field(default=1.0)
    ROLLOVER_MAX: float = Field(default=1.5)
    ROLLOVER_MIN_CONFIDENCE: float = Field(default=60.0)
    ROLLOVER_TARGET: float = Field(default=10.0)

class Settings(BaseSettings):
    """Application settings."""

    APP_NAME: str = Field(default="BetSightly")
    APP_VERSION: str = Field(default="1.0.0")
    DEBUG: bool = Field(default=False)
    ENVIRONMENT: str = Field(default="development")

    # Component settings
    api_football: APIFootballSettings = Field(default_factory=APIFootballSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    ml: MLSettings = Field(default_factory=MLSettings)
    odds_categories: OddsCategories = Field(default_factory=OddsCategories)

    # Derived settings
    ODDS_CATEGORIES: Dict[str, Dict[str, Any]] = {}

    def __init__(self, **kwargs):
        """Initialize settings."""
        super().__init__(**kwargs)

        # Create derived settings
        self.ODDS_CATEGORIES = {
            "2_odds": {
                "min": self.odds_categories.TWO_ODDS_MIN,
                "max": self.odds_categories.TWO_ODDS_MAX,
                "min_confidence": self.odds_categories.TWO_ODDS_MIN_CONFIDENCE,
                "limit": self.odds_categories.TWO_ODDS_LIMIT
            },
            "5_odds": {
                "min": self.odds_categories.FIVE_ODDS_MIN,
                "max": self.odds_categories.FIVE_ODDS_MAX,
                "min_confidence": self.odds_categories.FIVE_ODDS_MIN_CONFIDENCE,
                "limit": self.odds_categories.FIVE_ODDS_LIMIT
            },
            "10_odds": {
                "min": self.odds_categories.TEN_ODDS_MIN,
                "max": self.odds_categories.TEN_ODDS_MAX,
                "min_confidence": self.odds_categories.TEN_ODDS_MIN_CONFIDENCE,
                "limit": self.odds_categories.TEN_ODDS_LIMIT
            },
            "rollover": {
                "min": self.odds_categories.ROLLOVER_MIN,
                "max": self.odds_categories.ROLLOVER_MAX,
                "min_confidence": self.odds_categories.ROLLOVER_MIN_CONFIDENCE,
                "target": self.odds_categories.ROLLOVER_TARGET
            }
        }

        # Create directories
        os.makedirs(self.ml.MODEL_DIR, exist_ok=True)
        os.makedirs(self.ml.DATA_DIR, exist_ok=True)
        os.makedirs(self.ml.CACHE_DIR, exist_ok=True)

# Create settings instance
settings = Settings(
    APP_NAME="BetSightly",
    APP_VERSION="1.0.0",
    DEBUG=True,
    ENVIRONMENT="development",
    api_football=APIFootballSettings(
        API_KEY=os.environ.get("API_FOOTBALL_KEY", ""),
        API_HOST=os.environ.get("API_FOOTBALL_HOST", "api-football-v1.p.rapidapi.com")
    ),
    database=DatabaseSettings(
        URL=os.environ.get("DATABASE_URL", "sqlite:///data/database.db")
    ),
    ml=MLSettings(
        MODEL_DIR=os.environ.get("MODEL_DIR", "models"),
        DATA_DIR=os.environ.get("DATA_DIR", "data"),
        CACHE_DIR=os.environ.get("CACHE_DIR", "app/ml/cache")
    )
)
