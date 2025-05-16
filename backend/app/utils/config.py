"""
Configuration Module

This module provides centralized configuration management for the application.
It loads configuration from environment variables and configuration files.
"""

import os
import json
from typing import Dict, Any, Optional
from pydantic import Field
from pydantic_settings import BaseSettings
import logging

# Set up logging
logger = logging.getLogger(__name__)

class FootballDataSettings(BaseSettings):
    """Football-Data.org configuration settings."""

    API_KEY: str = Field("f9ed94ba8dde4a57b742ce7075057310", env="FOOTBALL_DATA_KEY")
    BASE_URL: str = Field("https://api.football-data.org/v4", env="FOOTBALL_DATA_BASE_URL")
    DAILY_LIMIT: int = Field(100, env="FOOTBALL_DATA_DAILY_LIMIT")
    DEFAULT_COMPETITIONS: str = Field("PL,PD,SA,BL1,FL1", env="FOOTBALL_DATA_DEFAULT_COMPETITIONS")

    class Config:
        env_prefix = "FOOTBALL_DATA_"
        case_sensitive = True

class APIFootballSettings(BaseSettings):
    """API Football configuration settings."""

    API_KEY: str = Field("", env="API_FOOTBALL_KEY")
    API_HOST: str = Field("api-football-v1.p.rapidapi.com", env="API_FOOTBALL_HOST")
    BASE_URL: str = Field("https://api-football-v1.p.rapidapi.com/v3", env="API_FOOTBALL_BASE_URL")
    DAILY_LIMIT: int = Field(100, env="API_FOOTBALL_DAILY_LIMIT")

    class Config:
        env_prefix = "API_FOOTBALL_"
        case_sensitive = True

class DatabaseSettings(BaseSettings):
    """Database configuration settings."""

    URL: str = Field("sqlite:///./football.db", env="DATABASE_URL")
    ECHO: bool = Field(False, env="DATABASE_ECHO")
    POOL_SIZE: int = Field(5, env="DATABASE_POOL_SIZE")
    MAX_OVERFLOW: int = Field(10, env="DATABASE_MAX_OVERFLOW")

    class Config:
        env_prefix = "DATABASE_"
        case_sensitive = True

class MLSettings(BaseSettings):
    """Machine learning configuration settings."""

    MODEL_DIR: str = Field("models", env="ML_MODEL_DIR")
    DATA_DIR: str = Field("data", env="ML_DATA_DIR")
    CACHE_DIR: str = Field("cache", env="ML_CACHE_DIR")
    FEATURE_CACHE_EXPIRY: int = Field(24, env="ML_FEATURE_CACHE_EXPIRY")  # hours

    class Config:
        env_prefix = "ML_"
        case_sensitive = True

class OddsCategories(BaseSettings):
    """Odds categories configuration."""

    TWO_ODDS_MIN: float = Field(1.5, env="ODDS_TWO_MIN")
    TWO_ODDS_MAX: float = Field(2.5, env="ODDS_TWO_MAX")
    TWO_ODDS_MIN_CONFIDENCE: float = Field(70.0, env="ODDS_TWO_MIN_CONFIDENCE")
    TWO_ODDS_LIMIT: int = Field(5, env="ODDS_TWO_LIMIT")
    TWO_ODDS_TARGET: float = Field(2.0, env="ODDS_TWO_TARGET")

    FIVE_ODDS_MIN: float = Field(2.5, env="ODDS_FIVE_MIN")
    FIVE_ODDS_MAX: float = Field(5.0, env="ODDS_FIVE_MAX")
    FIVE_ODDS_MIN_CONFIDENCE: float = Field(70.0, env="ODDS_FIVE_MIN_CONFIDENCE")
    FIVE_ODDS_LIMIT: int = Field(3, env="ODDS_FIVE_LIMIT")
    FIVE_ODDS_TARGET: float = Field(5.0, env="ODDS_FIVE_TARGET")

    TEN_ODDS_MIN: float = Field(5.0, env="ODDS_TEN_MIN")
    TEN_ODDS_MAX: float = Field(10.0, env="ODDS_TEN_MAX")
    TEN_ODDS_MIN_CONFIDENCE: float = Field(70.0, env="ODDS_TEN_MIN_CONFIDENCE")
    TEN_ODDS_LIMIT: int = Field(2, env="ODDS_TEN_LIMIT")
    TEN_ODDS_TARGET: float = Field(10.0, env="ODDS_TEN_TARGET")

    ROLLOVER_MIN: float = Field(1.2, env="ODDS_ROLLOVER_MIN")
    ROLLOVER_MAX: float = Field(2.0, env="ODDS_ROLLOVER_MAX")
    ROLLOVER_MIN_CONFIDENCE: float = Field(70.0, env="ODDS_ROLLOVER_MIN_CONFIDENCE")
    ROLLOVER_TARGET: float = Field(3.0, env="ODDS_ROLLOVER_TARGET")
    ROLLOVER_DAYS: int = Field(10, env="ODDS_ROLLOVER_DAYS")

    class Config:
        env_prefix = "ODDS_"
        case_sensitive = True

class Settings(BaseSettings):
    """Main application settings."""

    # Application settings
    APP_NAME: str = Field("BetSightly", env="APP_NAME")
    APP_VERSION: str = Field("1.0.0", env="APP_VERSION")
    DEBUG: bool = Field(False, env="DEBUG")
    ENVIRONMENT: str = Field("development", env="ENVIRONMENT")

    # Path settings
    BASE_DIR: str = Field(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), env="BASE_DIR")

    # Component settings
    football_data: FootballDataSettings = FootballDataSettings()  # Primary data source
    api_football: APIFootballSettings = APIFootballSettings()     # Fallback data source
    database: DatabaseSettings = DatabaseSettings()
    ml: MLSettings = MLSettings()
    odds_categories: OddsCategories = OddsCategories()

    model_config = {
        "extra": "allow",
        "arbitrary_types_allowed": True,
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Set absolute paths based on BASE_DIR
        self.ml.MODEL_DIR = os.path.join(self.BASE_DIR, self.ml.MODEL_DIR)
        self.ml.DATA_DIR = os.path.join(self.BASE_DIR, self.ml.DATA_DIR)
        self.ml.CACHE_DIR = os.path.join(self.BASE_DIR, self.ml.CACHE_DIR)

        # Create directories if they don't exist
        os.makedirs(self.ml.MODEL_DIR, exist_ok=True)
        os.makedirs(self.ml.DATA_DIR, exist_ok=True)
        os.makedirs(self.ml.CACHE_DIR, exist_ok=True)

        # Convert odds categories to dictionary format for backward compatibility
        self.ODDS_CATEGORIES = {
            "2_odds": {
                "min_odds": self.odds_categories.TWO_ODDS_MIN,
                "max_odds": self.odds_categories.TWO_ODDS_MAX,
                "min_confidence": self.odds_categories.TWO_ODDS_MIN_CONFIDENCE,
                "limit": self.odds_categories.TWO_ODDS_LIMIT,
                "target_combined_odds": self.odds_categories.TWO_ODDS_TARGET
            },
            "5_odds": {
                "min_odds": self.odds_categories.FIVE_ODDS_MIN,
                "max_odds": self.odds_categories.FIVE_ODDS_MAX,
                "min_confidence": self.odds_categories.FIVE_ODDS_MIN_CONFIDENCE,
                "limit": self.odds_categories.FIVE_ODDS_LIMIT,
                "target_combined_odds": self.odds_categories.FIVE_ODDS_TARGET
            },
            "10_odds": {
                "min_odds": self.odds_categories.TEN_ODDS_MIN,
                "max_odds": self.odds_categories.TEN_ODDS_MAX,
                "min_confidence": self.odds_categories.TEN_ODDS_MIN_CONFIDENCE,
                "limit": self.odds_categories.TEN_ODDS_LIMIT,
                "target_combined_odds": self.odds_categories.TEN_ODDS_TARGET
            },
            "rollover": {
                "min_odds": self.odds_categories.ROLLOVER_MIN,
                "max_odds": self.odds_categories.ROLLOVER_MAX,
                "min_confidence": self.odds_categories.ROLLOVER_MIN_CONFIDENCE,
                "target_combined_odds": self.odds_categories.ROLLOVER_TARGET,
                "days": self.odds_categories.ROLLOVER_DAYS
            }
        }



# Create a singleton instance
settings = Settings()

# For backward compatibility
FOOTBALL_DATA_KEY = settings.football_data.API_KEY
FOOTBALL_DATA_BASE_URL = settings.football_data.BASE_URL
FOOTBALL_DATA_DEFAULT_COMPETITIONS = settings.football_data.DEFAULT_COMPETITIONS

API_FOOTBALL_KEY = settings.api_football.API_KEY
API_FOOTBALL_HOST = settings.api_football.API_HOST
API_FOOTBALL_BASE_URL = settings.api_football.BASE_URL

MODEL_DIR = settings.ml.MODEL_DIR
DATA_DIR = settings.ml.DATA_DIR
CACHE_DIR = settings.ml.CACHE_DIR
