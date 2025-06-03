#!/usr/bin/env python3
"""
BetSightly Hybrid ML Pipeline

Optimized pipeline implementing the hybrid data approach:
1. Training Data: GitHub football dataset (cached locally)
2. Live Data: API keys for current fixtures
3. Smart Caching: Database + file system with expiry
4. No Duplication: Single source of truth for each data type

This replaces all redundant ML scripts with a unified, production-ready solution.
"""

import os
import sys
import logging
import pandas as pd
import numpy as np
import requests
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
import joblib
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.append(str(project_root))

from utils.config import settings
from utils.common import setup_logging, ensure_directory_exists
from services.api_client import FootballDataClient, APIClient
from utils.cache_manager import cache_manager
from database import get_db, engine

# Set up logging
logger = setup_logging("ml_hybrid_pipeline")

class HybridMLPipeline:
    """
    Unified ML pipeline with hybrid data approach.
    
    Features:
    - GitHub dataset for training (cached in database)
    - API data for live fixtures (cached with expiry)
    - Smart cache management
    - No data duplication
    """
    
    def __init__(self):
        """Initialize the hybrid pipeline."""
        self.models = {}
        self.api_client = None
        self.db_connection = None
        
        # Ensure directories exist
        ensure_directory_exists(settings.ml.MODEL_DIR)
        ensure_directory_exists(settings.ml.DATA_DIR)
        ensure_directory_exists(settings.ml.CACHE_DIR)
        
        # Initialize database connection
        self._init_database()
        
        # Setup API client
        self._setup_api_client()
        
        logger.info("Hybrid ML Pipeline initialized")
    
    def _init_database(self):
        """Initialize database connection and tables."""
        try:
            # Create connection
            db_path = settings.database.URL.replace("sqlite:///", "")
            self.db_connection = sqlite3.connect(db_path)
            
            # Create training data table if not exists
            self.db_connection.execute("""
                CREATE TABLE IF NOT EXISTS training_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dataset_name TEXT NOT NULL,
                    data_hash TEXT NOT NULL,
                    download_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    file_path TEXT NOT NULL,
                    record_count INTEGER,
                    UNIQUE(dataset_name, data_hash)
                )
            """)
            
            # Create fixture cache table if not exists
            self.db_connection.execute("""
                CREATE TABLE IF NOT EXISTS fixture_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cache_key TEXT UNIQUE NOT NULL,
                    data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    source TEXT NOT NULL
                )
            """)
            
            self.db_connection.commit()
            logger.info("Database tables initialized")
            
        except Exception as e:
            logger.error(f"Database initialization failed: {str(e)}")
            raise
    
    def _setup_api_client(self):
        """Setup API client for live fixture data."""
        # Try Football-Data.org first (primary)
        if settings.football_data.API_KEY and settings.football_data.API_KEY != "dummy_key_for_testing_basketball_pipeline":
            try:
                self.api_client = FootballDataClient()
                logger.info("✅ Football-Data.org API client configured")
                return
            except Exception as e:
                logger.error(f"Football-Data.org setup failed: {str(e)}")
        
        # Try API-Football as fallback
        if settings.api_football.API_KEY and settings.api_football.API_KEY != "dummy_key_for_testing_basketball_pipeline":
            try:
                headers = {
                    "x-rapidapi-key": settings.api_football.API_KEY,
                    "x-rapidapi-host": "v3.football.api-sports.io"
                }
                self.api_client = APIClient(
                    base_url="https://v3.football.api-sports.io",
                    headers=headers
                )
                logger.info("✅ API-Football client configured")
                return
            except Exception as e:
                logger.error(f"API-Football setup failed: {str(e)}")
        
        logger.warning("⚠️  No API client configured - live data unavailable")
    
    def get_training_data(self, force_download: bool = False) -> pd.DataFrame:
        """
        Get training data using hybrid approach.
        
        Args:
            force_download: Force download even if cached
            
        Returns:
            DataFrame with training data
        """
        dataset_name = "github_football_matches"
        
        # Check database cache first
        if not force_download:
            cached_data = self._get_cached_training_data(dataset_name)
            if cached_data is not None:
                logger.info(f"✅ Using cached training data: {len(cached_data)} records")
                return cached_data
        
        # Download and cache new data
        logger.info("📥 Downloading GitHub training dataset...")
        try:
            # Download from GitHub
            response = requests.get(settings.data_source.GITHUB_DATASET_URL, timeout=120)
            response.raise_for_status()
            
            # Parse CSV
            df = pd.read_csv(response.content.decode('utf-8'))
            
            # Cache in database and file system
            self._cache_training_data(dataset_name, df)
            
            logger.info(f"✅ Downloaded and cached {len(df)} training records")
            return df
            
        except Exception as e:
            logger.error(f"❌ Failed to download training data: {str(e)}")
            raise
    
    def _get_cached_training_data(self, dataset_name: str) -> Optional[pd.DataFrame]:
        """Get cached training data from database."""
        try:
            # Check if we have recent cached data (within 7 days)
            cursor = self.db_connection.execute("""
                SELECT file_path, record_count, download_date 
                FROM training_data 
                WHERE dataset_name = ? 
                AND download_date > datetime('now', '-7 days')
                ORDER BY download_date DESC 
                LIMIT 1
            """, (dataset_name,))
            
            result = cursor.fetchone()
            if result:
                file_path, record_count, download_date = result
                
                # Check if file still exists
                if os.path.exists(file_path):
                    logger.info(f"📂 Loading cached data from {download_date}")
                    return pd.read_parquet(file_path)
                else:
                    # Clean up stale database entry
                    self.db_connection.execute(
                        "DELETE FROM training_data WHERE dataset_name = ? AND file_path = ?",
                        (dataset_name, file_path)
                    )
                    self.db_connection.commit()
            
            return None
            
        except Exception as e:
            logger.error(f"Error checking cached training data: {str(e)}")
            return None
    
    def _cache_training_data(self, dataset_name: str, df: pd.DataFrame):
        """Cache training data in database and file system."""
        try:
            # Generate file path
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_path = os.path.join(settings.ml.DATA_DIR, f"{dataset_name}_{timestamp}.parquet")
            
            # Save to file system
            ensure_directory_exists(os.path.dirname(file_path))
            df.to_parquet(file_path)
            
            # Calculate data hash for deduplication
            data_hash = str(hash(str(df.values.tobytes())))
            
            # Save metadata to database
            self.db_connection.execute("""
                INSERT OR REPLACE INTO training_data 
                (dataset_name, data_hash, file_path, record_count)
                VALUES (?, ?, ?, ?)
            """, (dataset_name, data_hash, file_path, len(df)))
            
            self.db_connection.commit()
            
            # Clean up old cached files (keep only latest 3)
            self._cleanup_old_training_cache(dataset_name)
            
            logger.info(f"💾 Cached training data: {file_path}")
            
        except Exception as e:
            logger.error(f"Error caching training data: {str(e)}")
    
    def _cleanup_old_training_cache(self, dataset_name: str):
        """Clean up old training cache files."""
        try:
            # Get old files to delete (keep only latest 3)
            cursor = self.db_connection.execute("""
                SELECT file_path FROM training_data 
                WHERE dataset_name = ? 
                ORDER BY download_date DESC 
                OFFSET 3
            """, (dataset_name,))
            
            old_files = cursor.fetchall()
            
            for (file_path,) in old_files:
                # Delete file if exists
                if os.path.exists(file_path):
                    os.remove(file_path)
                
                # Delete database record
                self.db_connection.execute(
                    "DELETE FROM training_data WHERE file_path = ?",
                    (file_path,)
                )
            
            if old_files:
                self.db_connection.commit()
                logger.info(f"🧹 Cleaned up {len(old_files)} old training cache files")
                
        except Exception as e:
            logger.error(f"Error cleaning up training cache: {str(e)}")
    
    def get_live_fixtures(self, date: str = None, use_cache: bool = True) -> List[Dict]:
        """
        Get live fixtures using API with smart caching.
        
        Args:
            date: Date in YYYY-MM-DD format (default: today)
            use_cache: Whether to use cached data
            
        Returns:
            List of fixture dictionaries
        """
        if not self.api_client:
            logger.error("❌ No API client configured")
            return []
        
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        
        cache_key = f"fixtures_{date}"
        
        # Check cache first
        if use_cache:
            cached_fixtures = self._get_cached_fixtures(cache_key)
            if cached_fixtures:
                logger.info(f"📂 Using cached fixtures for {date}: {len(cached_fixtures)} fixtures")
                return cached_fixtures
        
        # Fetch from API
        logger.info(f"🌐 Fetching live fixtures for {date}")
        try:
            # Use appropriate API method based on client type
            if isinstance(self.api_client, FootballDataClient):
                # Football-Data.org API
                response = self.api_client.get("matches", params={
                    "dateFrom": date,
                    "dateTo": date
                })
                fixtures = response.get("matches", [])
                source = "football-data.org"
            else:
                # API-Football
                response = self.api_client.get("fixtures", params={"date": date})
                fixtures = response.get("response", [])
                source = "api-football"
            
            # Cache the fixtures
            self._cache_fixtures(cache_key, fixtures, source)
            
            logger.info(f"✅ Fetched {len(fixtures)} fixtures from {source}")
            return fixtures
            
        except Exception as e:
            logger.error(f"❌ Failed to fetch fixtures: {str(e)}")
            return []
    
    def _get_cached_fixtures(self, cache_key: str) -> Optional[List[Dict]]:
        """Get cached fixtures from database."""
        try:
            cursor = self.db_connection.execute("""
                SELECT data, source, created_at 
                FROM fixture_cache 
                WHERE cache_key = ? AND expires_at > datetime('now')
            """, (cache_key,))
            
            result = cursor.fetchone()
            if result:
                data_json, source, created_at = result
                fixtures = eval(data_json)  # Safe since we control the data
                logger.info(f"📂 Cache hit for {cache_key} from {source} ({created_at})")
                return fixtures
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting cached fixtures: {str(e)}")
            return None
    
    def _cache_fixtures(self, cache_key: str, fixtures: List[Dict], source: str):
        """Cache fixtures in database with expiry."""
        try:
            # Set expiry time (24 hours for fixtures)
            expires_at = datetime.now() + timedelta(hours=24)
            
            # Store in database
            self.db_connection.execute("""
                INSERT OR REPLACE INTO fixture_cache 
                (cache_key, data, expires_at, source)
                VALUES (?, ?, ?, ?)
            """, (cache_key, str(fixtures), expires_at, source))
            
            self.db_connection.commit()
            logger.info(f"💾 Cached {len(fixtures)} fixtures with key: {cache_key}")
            
        except Exception as e:
            logger.error(f"Error caching fixtures: {str(e)}")
    
    def cleanup_expired_cache(self):
        """Clean up expired cache entries."""
        try:
            # Clean up expired fixture cache
            cursor = self.db_connection.execute("""
                DELETE FROM fixture_cache 
                WHERE expires_at < datetime('now')
            """)
            
            deleted_count = cursor.rowcount
            self.db_connection.commit()
            
            if deleted_count > 0:
                logger.info(f"🧹 Cleaned up {deleted_count} expired cache entries")
            
            # Also clean up file system cache
            cache_manager.cleanup_expired_cache()
            
        except Exception as e:
            logger.error(f"Error cleaning up cache: {str(e)}")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        try:
            # Database cache stats
            cursor = self.db_connection.execute("""
                SELECT 
                    COUNT(*) as total_training_cache,
                    COUNT(CASE WHEN download_date > datetime('now', '-7 days') THEN 1 END) as recent_training_cache
                FROM training_data
            """)
            training_stats = cursor.fetchone()
            
            cursor = self.db_connection.execute("""
                SELECT 
                    COUNT(*) as total_fixture_cache,
                    COUNT(CASE WHEN expires_at > datetime('now') THEN 1 END) as valid_fixture_cache
                FROM fixture_cache
            """)
            fixture_stats = cursor.fetchone()
            
            # File system cache stats
            fs_stats = cache_manager.get_cache_stats()
            
            return {
                "database_cache": {
                    "training_data": {
                        "total": training_stats[0],
                        "recent": training_stats[1]
                    },
                    "fixtures": {
                        "total": fixture_stats[0],
                        "valid": fixture_stats[1]
                    }
                },
                "file_system_cache": fs_stats
            }
            
        except Exception as e:
            logger.error(f"Error getting cache stats: {str(e)}")
            return {}
    
    def __del__(self):
        """Clean up database connection."""
        if self.db_connection:
            self.db_connection.close()


# Global pipeline instance
hybrid_pipeline = HybridMLPipeline()


def get_training_data(force_download: bool = False) -> pd.DataFrame:
    """Convenience function to get training data."""
    return hybrid_pipeline.get_training_data(force_download)


def get_live_fixtures(date: str = None) -> List[Dict]:
    """Convenience function to get live fixtures."""
    return hybrid_pipeline.get_live_fixtures(date)


def cleanup_cache():
    """Convenience function to clean up cache."""
    return hybrid_pipeline.cleanup_expired_cache()


if __name__ == "__main__":
    # Test the hybrid pipeline
    print("🔄 Testing Hybrid ML Pipeline")
    print("=" * 50)
    
    # Test training data
    print("\n1. Testing training data...")
    try:
        df = get_training_data()
        print(f"✅ Training data: {len(df)} records")
        print(f"📊 Columns: {list(df.columns)[:5]}...")
    except Exception as e:
        print(f"❌ Training data failed: {str(e)}")
    
    # Test live fixtures
    print("\n2. Testing live fixtures...")
    try:
        fixtures = get_live_fixtures()
        print(f"✅ Live fixtures: {len(fixtures)} fixtures")
    except Exception as e:
        print(f"❌ Live fixtures failed: {str(e)}")
    
    # Test cache stats
    print("\n3. Cache statistics...")
    try:
        stats = hybrid_pipeline.get_cache_stats()
        print(f"📊 Cache stats: {stats}")
    except Exception as e:
        print(f"❌ Cache stats failed: {str(e)}")
    
    print("\n✅ Hybrid pipeline test completed!")
