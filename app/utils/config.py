"""
Configuration

This module contains the configuration settings for the application.
"""

import os
import sys
import logging
from typing import Dict, List, Any, Union
from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict
from datetime import datetime

# Set up logging
logger = logging.getLogger(__name__)

class APIFootballSettings(BaseSettings):
    """API Football settings."""
    
    model_config = SettingsConfigDict(
        env_prefix="API_FOOTBALL_",
        case_sensitive=False
    )

    API_KEY: str = Field(default="")
    API_HOST: str = Field(default="api-football-v1.p.rapidapi.com")
    BASE_URL: str = Field(default="https://api-football-v1.p.rapidapi.com/v3")
    DAILY_LIMIT: int = Field(default=100)

class DatabaseSettings(BaseSettings):
    """Database settings."""
    
    model_config = SettingsConfigDict(
        env_prefix="DATABASE_",
        case_sensitive=False
    )

    URL: str = Field(default="sqlite:///data/database.db")
    ECHO: bool = Field(default=False)
    POOL_SIZE: int = Field(default=5)
    MAX_OVERFLOW: int = Field(default=10)

class MLSettings(BaseSettings):
    """Machine learning settings."""
    
    model_config = SettingsConfigDict(
        env_prefix="ML_",
        case_sensitive=False
    )

    MODEL_DIR: str = Field(default="models")
    DATA_DIR: str = Field(default="data")
    CACHE_DIR: str = Field(default="app/ml/cache")
    FEATURE_CACHE_EXPIRY: int = Field(default=24)  # Hours

class OddsCategories(BaseSettings):
    """Odds categories settings."""
    
    model_config = SettingsConfigDict(
        env_prefix="ODDS_",
        case_sensitive=False
    )

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
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

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
    ODDS_CATEGORIES: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    def model_post_init(self, __context) -> None:
        """Initialize derived settings after model creation."""
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
settings = Settings()
