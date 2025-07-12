#!/usr/bin/env python3
"""
Cache Cleanup Script

This script can be run periodically to clean up expired cache files.
Can be scheduled as a cron job or Windows Task.
"""

import os
import sys
import logging
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.cache_manager import cache_manager

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('cache_cleanup.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


def main():
    """Main cleanup function."""
    logger.info("Starting cache cleanup process...")
    
    try:
        # Get cache stats before cleanup
        before_stats = cache_manager.get_cache_stats()
        logger.info(f"Before cleanup: {before_stats['total_files']} files, "
                   f"{before_stats['total_size_mb']:.2f} MB")
        
        # Run cleanup
        cleanup_stats = cache_manager.cleanup_expired_cache()
        
        # Log results
        logger.info(f"Cleanup completed:")
        logger.info(f"  - Total files processed: {cleanup_stats['total_files']}")
        logger.info(f"  - Expired files found: {cleanup_stats['expired_files']}")
        logger.info(f"  - Files deleted: {cleanup_stats['deleted_files']}")
        logger.info(f"  - Space freed: {cleanup_stats['space_freed_mb']:.2f} MB")
        logger.info(f"  - Errors: {cleanup_stats['errors']}")
        
        # Get cache stats after cleanup
        after_stats = cache_manager.get_cache_stats()
        logger.info(f"After cleanup: {after_stats['total_files']} files, "
                   f"{after_stats['total_size_mb']:.2f} MB")
        
        # Return success
        return 0
        
    except Exception as e:
        logger.error(f"Cache cleanup failed: {str(e)}")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
