"""
Configuration Module

This module provides centralized configuration management for the application.
It loads configuration from environment variables and configuration files.
"""

import os
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import logging

# Set up logging
logger = logging.getLogger(__name__)

class FootballDataSettings(BaseSettings):
    """Football-Data.org configuration settings."""

    API_KEY: str = Field("f9ed94ba8dde4a57b742ce7075057310")
    BASE_URL: str = Field("https://api.football-data.org/v4")
    DAILY_LIMIT: int = Field(100)
    DEFAULT_COMPETITIONS: str = Field("PL,PD,SA,BL1,FL1")

    model_config = SettingsConfigDict(env_prefix="FOOTBALL_DATA_", case_sensitive=True)

class APIFootballSettings(BaseSettings):
    """API Football configuration settings."""

    API_KEY: str = Field("")
    API_HOST: str = Field("api-football-v1.p.rapidapi.com")
    BASE_URL: str = Field("https://api-football-v1.p.rapidapi.com/v3")
    DAILY_LIMIT: int = Field(100)

    model_config = SettingsConfigDict(env_prefix="API_FOOTBALL_", case_sensitive=True)

class DatabaseSettings(BaseSettings):
    """Database configuration settings."""

    URL: str = Field("sqlite:///./football.db")
    ECHO: bool = Field(False)
    POOL_SIZE: int = Field(5)
    MAX_OVERFLOW: int = Field(10)

    model_config = SettingsConfigDict(env_prefix="DATABASE_", case_sensitive=True)

class MLSettings(BaseSettings):
    """Machine learning configuration settings."""

    MODEL_DIR: str = Field("models")
    DATA_DIR: str = Field("data")
    CACHE_DIR: str = Field("cache")
    FEATURE_CACHE_EXPIRY: int = Field(24)  # hours

    model_config = SettingsConfigDict(env_prefix="ML_", case_sensitive=True)

class TelegramSettings(BaseSettings):
    """Telegram bot configuration settings."""

    BOT_TOKEN: str = Field("")
    CHAT_ID: str = Field("")
    WEBHOOK_URL: str = Field("")
    WEBHOOK_SECRET: str = Field("")

    model_config = SettingsConfigDict(env_prefix="TELEGRAM_", case_sensitive=True)

class PunterSettings(BaseSettings):
    """Punter configuration settings."""

    CACHE_DIR: str = Field("punter_cache")
    MIN_PREDICTIONS: int = Field(10)
    DEFAULT_CONFIDENCE: float = Field(0.5)

    model_config = SettingsConfigDict(env_prefix="PUNTER_", case_sensitive=True)

class OddsCategories(BaseSettings):
    """Odds categories configuration."""

    TWO_ODDS_MIN: float = Field(1.5)
    TWO_ODDS_MAX: float = Field(2.5)
    TWO_ODDS_MIN_CONFIDENCE: float = Field(70.0)
    TWO_ODDS_LIMIT: int = Field(5)
    TWO_ODDS_TARGET: float = Field(2.0)

    FIVE_ODDS_MIN: float = Field(2.5)
    FIVE_ODDS_MAX: float = Field(5.0)
    FIVE_ODDS_MIN_CONFIDENCE: float = Field(70.0)
    FIVE_ODDS_LIMIT: int = Field(3)
    FIVE_ODDS_TARGET: float = Field(5.0)

    TEN_ODDS_MIN: float = Field(5.0)
    TEN_ODDS_MAX: float = Field(10.0)
    TEN_ODDS_MIN_CONFIDENCE: float = Field(70.0)
    TEN_ODDS_LIMIT: int = Field(2)
    TEN_ODDS_TARGET: float = Field(10.0)

    ROLLOVER_MIN: float = Field(1.2)
    ROLLOVER_MAX: float = Field(2.0)
    ROLLOVER_MIN_CONFIDENCE: float = Field(70.0)
    ROLLOVER_TARGET: float = Field(3.0)
    ROLLOVER_DAYS: int = Field(10)

    model_config = SettingsConfigDict(env_prefix="ODDS_", case_sensitive=True)

class Settings(BaseSettings):
    """Main application settings."""

    # Application settings
    APP_NAME: str = Field("BetSightly")
    APP_VERSION: str = Field("1.0.0")
    DEBUG: bool = Field(False)
    ENVIRONMENT: str = Field("development")

    # Path settings
    BASE_DIR: str = Field(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

    # Component settings
    football_data: FootballDataSettings = FootballDataSettings()  # Primary data source
    api_football: APIFootballSettings = APIFootballSettings()     # Fallback data source
    database: DatabaseSettings = DatabaseSettings()
    ml: MLSettings = MLSettings()
    telegram: TelegramSettings = TelegramSettings()
    punter: PunterSettings = PunterSettings()
    odds_categories: OddsCategories = OddsCategories()

    model_config = SettingsConfigDict(
        extra="allow",
        arbitrary_types_allowed=True,
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Set absolute paths based on BASE_DIR
        self.ml.MODEL_DIR = os.path.join(self.BASE_DIR, self.ml.MODEL_DIR)
        self.ml.DATA_DIR = os.path.join(self.BASE_DIR, self.ml.DATA_DIR)
        self.ml.CACHE_DIR = os.path.join(self.BASE_DIR, self.ml.CACHE_DIR)
        self.punter.CACHE_DIR = os.path.join(self.BASE_DIR, self.punter.CACHE_DIR)

        # Create directories if they don't exist
        os.makedirs(self.ml.MODEL_DIR, exist_ok=True)
        os.makedirs(self.ml.DATA_DIR, exist_ok=True)
        os.makedirs(self.ml.CACHE_DIR, exist_ok=True)
        os.makedirs(self.punter.CACHE_DIR, exist_ok=True)

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
