"""
Test Configuration Module

This module contains tests for the configuration module.
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

# Add the parent directory to the path so we can import the app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from app.utils.config import Settings, APIFootballSettings, DatabaseSettings, MLSettings, OddsCategories

class TestConfig:
    """Tests for the configuration module."""
    
    def test_api_football_settings(self):
        """Test APIFootballSettings."""
        settings = APIFootballSettings(
            API_KEY="test_key",
            API_HOST="test_host",
            BASE_URL="test_url",
            DAILY_LIMIT=200
        )
        
        assert settings.API_KEY == "test_key"
        assert settings.API_HOST == "test_host"
        assert settings.BASE_URL == "test_url"
        assert settings.DAILY_LIMIT == 200
    
    def test_database_settings(self):
        """Test DatabaseSettings."""
        settings = DatabaseSettings(
            URL="test_url",
            ECHO=True,
            POOL_SIZE=10,
            MAX_OVERFLOW=20
        )
        
        assert settings.URL == "test_url"
        assert settings.ECHO is True
        assert settings.POOL_SIZE == 10
        assert settings.MAX_OVERFLOW == 20
    
    def test_ml_settings(self):
        """Test MLSettings."""
        settings = MLSettings(
            MODEL_DIR="test_model_dir",
            DATA_DIR="test_data_dir",
            CACHE_DIR="test_cache_dir",
            FEATURE_CACHE_EXPIRY=48
        )
        
        assert settings.MODEL_DIR == "test_model_dir"
        assert settings.DATA_DIR == "test_data_dir"
        assert settings.CACHE_DIR == "test_cache_dir"
        assert settings.FEATURE_CACHE_EXPIRY == 48
    
    def test_odds_categories(self):
        """Test OddsCategories."""
        settings = OddsCategories(
            TWO_ODDS_MIN=1.0,
            TWO_ODDS_MAX=2.0,
            TWO_ODDS_MIN_CONFIDENCE=50.0,
            TWO_ODDS_LIMIT=10,
            FIVE_ODDS_MIN=2.0,
            FIVE_ODDS_MAX=5.0,
            FIVE_ODDS_MIN_CONFIDENCE=40.0,
            FIVE_ODDS_LIMIT=5,
            TEN_ODDS_MIN=5.0,
            TEN_ODDS_MAX=10.0,
            TEN_ODDS_MIN_CONFIDENCE=30.0,
            TEN_ODDS_LIMIT=3,
            ROLLOVER_MIN=1.0,
            ROLLOVER_MAX=1.5,
            ROLLOVER_MIN_CONFIDENCE=60.0,
            ROLLOVER_TARGET=10.0
        )
        
        assert settings.TWO_ODDS_MIN == 1.0
        assert settings.TWO_ODDS_MAX == 2.0
        assert settings.TWO_ODDS_MIN_CONFIDENCE == 50.0
        assert settings.TWO_ODDS_LIMIT == 10
        assert settings.FIVE_ODDS_MIN == 2.0
        assert settings.FIVE_ODDS_MAX == 5.0
        assert settings.FIVE_ODDS_MIN_CONFIDENCE == 40.0
        assert settings.FIVE_ODDS_LIMIT == 5
        assert settings.TEN_ODDS_MIN == 5.0
        assert settings.TEN_ODDS_MAX == 10.0
        assert settings.TEN_ODDS_MIN_CONFIDENCE == 30.0
        assert settings.TEN_ODDS_LIMIT == 3
        assert settings.ROLLOVER_MIN == 1.0
        assert settings.ROLLOVER_MAX == 1.5
        assert settings.ROLLOVER_MIN_CONFIDENCE == 60.0
        assert settings.ROLLOVER_TARGET == 10.0
    
    @patch("os.path.dirname")
    @patch("os.makedirs")
    def test_settings_init(self, mock_makedirs, mock_dirname):
        """Test Settings initialization."""
        # Mock dirname to return a fixed path
        mock_dirname.return_value = "/test/path"
        
        # Create settings
        settings = Settings(
            APP_NAME="TestApp",
            APP_VERSION="1.0.0",
            DEBUG=True,
            ENVIRONMENT="test"
        )
        
        # Check settings
        assert settings.APP_NAME == "TestApp"
        assert settings.APP_VERSION == "1.0.0"
        assert settings.DEBUG is True
        assert settings.ENVIRONMENT == "test"
        
        # Check component settings
        assert isinstance(settings.api_football, APIFootballSettings)
        assert isinstance(settings.database, DatabaseSettings)
        assert isinstance(settings.ml, MLSettings)
        assert isinstance(settings.odds_categories, OddsCategories)
        
        # Check ODDS_CATEGORIES dictionary
        assert "2_odds" in settings.ODDS_CATEGORIES
        assert "5_odds" in settings.ODDS_CATEGORIES
        assert "10_odds" in settings.ODDS_CATEGORIES
        assert "rollover" in settings.ODDS_CATEGORIES
        
        # Check directories were created
        assert mock_makedirs.call_count == 3
