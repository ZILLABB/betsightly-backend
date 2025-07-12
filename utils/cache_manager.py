"""
Cache Manager Utility

This module provides utilities for managing cache files and cleanup.
"""

import os
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from utils.config import settings
except ImportError:
    # Fallback if config is not available
    settings = None

logger = logging.getLogger(__name__)


class CacheManager:
    """Manages cache files and cleanup operations."""
    
    def __init__(self, cache_dir: str = None):
        """Initialize cache manager."""
        self.cache_dir = Path(cache_dir or "cache")
        self.cache_dir.mkdir(exist_ok=True)
        
        # Cache expiry settings (in days)
        self.expiry_settings = {
            "fixtures": 7,      # Fixture data expires after 7 days
            "h2h": 30,          # Head-to-head data expires after 30 days
            "team_stats": 14,   # Team stats expire after 14 days
            "predictions": 1,   # Predictions expire after 1 day
            "default": 7        # Default expiry for other files
        }
    
    def cleanup_expired_cache(self) -> Dict[str, int]:
        """
        Clean up expired cache files.
        
        Returns:
            Dictionary with cleanup statistics
        """
        stats = {
            "total_files": 0,
            "expired_files": 0,
            "deleted_files": 0,
            "space_freed_mb": 0.0,
            "errors": 0
        }
        
        try:
            # Get all cache files
            cache_files = list(self.cache_dir.glob("*.json"))
            stats["total_files"] = len(cache_files)
            
            logger.info(f"Found {len(cache_files)} cache files")
            
            for cache_file in cache_files:
                try:
                    # Determine file type and expiry
                    file_type = self._get_file_type(cache_file.name)
                    expiry_days = self.expiry_settings.get(file_type, self.expiry_settings["default"])
                    
                    # Check if file is expired
                    if self._is_file_expired(cache_file, expiry_days):
                        stats["expired_files"] += 1
                        
                        # Get file size before deletion
                        file_size = cache_file.stat().st_size
                        
                        # Delete the file
                        cache_file.unlink()
                        stats["deleted_files"] += 1
                        stats["space_freed_mb"] += file_size / (1024 * 1024)
                        
                        logger.debug(f"Deleted expired cache file: {cache_file.name}")
                
                except Exception as e:
                    logger.error(f"Error processing cache file {cache_file.name}: {str(e)}")
                    stats["errors"] += 1
            
            logger.info(f"Cache cleanup completed: {stats['deleted_files']} files deleted, "
                       f"{stats['space_freed_mb']:.2f} MB freed")
            
        except Exception as e:
            logger.error(f"Error during cache cleanup: {str(e)}")
            stats["errors"] += 1
        
        return stats
    
    def _get_file_type(self, filename: str) -> str:
        """Determine the type of cache file based on filename."""
        if filename.startswith("fixtures_"):
            return "fixtures"
        elif filename.startswith("h2h_"):
            return "h2h"
        elif filename.startswith("team_stats_"):
            return "team_stats"
        elif filename.startswith("predictions_"):
            return "predictions"
        else:
            return "default"
    
    def _is_file_expired(self, file_path: Path, expiry_days: int) -> bool:
        """Check if a cache file is expired."""
        try:
            # Get file modification time
            mod_time = datetime.fromtimestamp(file_path.stat().st_mtime)
            expiry_time = datetime.now() - timedelta(days=expiry_days)
            
            return mod_time < expiry_time
        
        except Exception as e:
            logger.error(f"Error checking file expiry for {file_path}: {str(e)}")
            return False
    
    def get_cache_stats(self) -> Dict[str, any]:
        """Get statistics about cache usage."""
        stats = {
            "total_files": 0,
            "total_size_mb": 0.0,
            "file_types": {},
            "oldest_file": None,
            "newest_file": None
        }
        
        try:
            cache_files = list(self.cache_dir.glob("*.json"))
            stats["total_files"] = len(cache_files)
            
            oldest_time = None
            newest_time = None
            
            for cache_file in cache_files:
                try:
                    # File size
                    file_size = cache_file.stat().st_size
                    stats["total_size_mb"] += file_size / (1024 * 1024)
                    
                    # File type
                    file_type = self._get_file_type(cache_file.name)
                    if file_type not in stats["file_types"]:
                        stats["file_types"][file_type] = {"count": 0, "size_mb": 0.0}
                    
                    stats["file_types"][file_type]["count"] += 1
                    stats["file_types"][file_type]["size_mb"] += file_size / (1024 * 1024)
                    
                    # File age
                    mod_time = datetime.fromtimestamp(cache_file.stat().st_mtime)
                    if oldest_time is None or mod_time < oldest_time:
                        oldest_time = mod_time
                        stats["oldest_file"] = {
                            "name": cache_file.name,
                            "date": mod_time.isoformat()
                        }
                    
                    if newest_time is None or mod_time > newest_time:
                        newest_time = mod_time
                        stats["newest_file"] = {
                            "name": cache_file.name,
                            "date": mod_time.isoformat()
                        }
                
                except Exception as e:
                    logger.error(f"Error processing cache file {cache_file.name}: {str(e)}")
        
        except Exception as e:
            logger.error(f"Error getting cache stats: {str(e)}")
        
        return stats
    
    def clear_cache_by_type(self, file_type: str) -> int:
        """
        Clear all cache files of a specific type.
        
        Args:
            file_type: Type of cache files to clear
            
        Returns:
            Number of files deleted
        """
        deleted_count = 0
        
        try:
            cache_files = list(self.cache_dir.glob("*.json"))
            
            for cache_file in cache_files:
                if self._get_file_type(cache_file.name) == file_type:
                    try:
                        cache_file.unlink()
                        deleted_count += 1
                        logger.debug(f"Deleted cache file: {cache_file.name}")
                    except Exception as e:
                        logger.error(f"Error deleting cache file {cache_file.name}: {str(e)}")
            
            logger.info(f"Cleared {deleted_count} cache files of type '{file_type}'")
        
        except Exception as e:
            logger.error(f"Error clearing cache by type: {str(e)}")
        
        return deleted_count
    
    def clear_all_cache(self) -> int:
        """
        Clear all cache files.
        
        Returns:
            Number of files deleted
        """
        deleted_count = 0
        
        try:
            cache_files = list(self.cache_dir.glob("*.json"))
            
            for cache_file in cache_files:
                try:
                    cache_file.unlink()
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"Error deleting cache file {cache_file.name}: {str(e)}")
            
            logger.info(f"Cleared all cache: {deleted_count} files deleted")
        
        except Exception as e:
            logger.error(f"Error clearing all cache: {str(e)}")
        
        return deleted_count
    
    def optimize_cache(self) -> Dict[str, int]:
        """
        Optimize cache by removing duplicates and expired files.
        
        Returns:
            Optimization statistics
        """
        stats = {
            "expired_deleted": 0,
            "duplicates_deleted": 0,
            "total_deleted": 0
        }
        
        # Clean up expired files
        cleanup_stats = self.cleanup_expired_cache()
        stats["expired_deleted"] = cleanup_stats["deleted_files"]
        
        # TODO: Add duplicate detection and removal logic
        # This would involve comparing file contents and keeping the newest
        
        stats["total_deleted"] = stats["expired_deleted"] + stats["duplicates_deleted"]
        
        return stats


# Global cache manager instance
cache_manager = CacheManager()


def cleanup_cache():
    """Convenience function to clean up expired cache files."""
    return cache_manager.cleanup_expired_cache()


def get_cache_stats():
    """Convenience function to get cache statistics."""
    return cache_manager.get_cache_stats()


if __name__ == "__main__":
    # Run cache cleanup when script is executed directly
    print("Running cache cleanup...")
    stats = cleanup_cache()
    print(f"Cleanup completed: {stats}")
    
    print("\nCache statistics:")
    cache_stats = get_cache_stats()
    print(f"Total files: {cache_stats['total_files']}")
    print(f"Total size: {cache_stats['total_size_mb']:.2f} MB")
    print(f"File types: {cache_stats['file_types']}")
