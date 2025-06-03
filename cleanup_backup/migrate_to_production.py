#!/usr/bin/env python3
"""
Database Migration Script for Production

This script handles database migrations and schema updates for production deployment.
"""

import os
import sys
import logging
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

# Add project root to path
sys.path.append('.')

from database import get_db, init_db
from utils.config import settings

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DatabaseMigrator:
    """Handles database migrations for production."""
    
    def __init__(self):
        self.migrations_applied = []
        self.migration_errors = []
    
    def get_database_path(self) -> str:
        """Get the database path from settings."""
        db_url = settings.database.URL
        if db_url.startswith('sqlite:///'):
            return db_url.replace('sqlite:///', '')
        return 'football.db'  # fallback
    
    def backup_database(self) -> str:
        """Create a backup of the current database."""
        db_path = self.get_database_path()
        if not os.path.exists(db_path):
            logger.info("No existing database to backup")
            return ""
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = f"{db_path}.backup_{timestamp}"
        
        try:
            import shutil
            shutil.copy2(db_path, backup_path)
            logger.info(f"✅ Database backed up to: {backup_path}")
            return backup_path
        except Exception as e:
            logger.error(f"❌ Failed to backup database: {e}")
            return ""
    
    def check_table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database."""
        from sqlalchemy import text
        db = next(get_db())
        try:
            result = db.execute(text(f"""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='{table_name}'
            """)).fetchone()
            return result is not None
        finally:
            db.close()
    
    def get_table_columns(self, table_name: str) -> List[str]:
        """Get column names for a table."""
        from sqlalchemy import text
        db = next(get_db())
        try:
            result = db.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            return [row[1] for row in result]  # Column name is at index 1
        finally:
            db.close()
    
    def add_column_if_not_exists(self, table_name: str, column_name: str, column_type: str) -> bool:
        """Add a column to a table if it doesn't exist."""
        columns = self.get_table_columns(table_name)
        if column_name in columns:
            logger.info(f"Column {column_name} already exists in {table_name}")
            return True
        
        from sqlalchemy import text
        db = next(get_db())
        try:
            db.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))
            db.commit()
            logger.info(f"✅ Added column {column_name} to {table_name}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to add column {column_name} to {table_name}: {e}")
            return False
        finally:
            db.close()
    
    def migration_001_add_prediction_categories(self) -> bool:
        """Migration 001: Add prediction category fields."""
        logger.info("Running migration 001: Add prediction categories")
        
        if not self.check_table_exists('predictions'):
            logger.info("Predictions table doesn't exist, skipping migration")
            return True
        
        migrations = [
            ('predictions', 'prediction_type', 'VARCHAR(20)'),
            ('predictions', 'combined_odds', 'FLOAT DEFAULT 0'),
            ('predictions', 'combined_confidence', 'FLOAT DEFAULT 0'),
            ('predictions', 'combo_id', 'VARCHAR(50)'),
            ('predictions', 'rollover_day', 'INTEGER'),
            ('predictions', 'updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
        ]
        
        success = True
        for table, column, column_type in migrations:
            if not self.add_column_if_not_exists(table, column, column_type):
                success = False
        
        return success
    
    def migration_002_add_betting_code_fields(self) -> bool:
        """Migration 002: Add additional betting code fields."""
        logger.info("Running migration 002: Add betting code fields")
        
        if not self.check_table_exists('betting_codes'):
            logger.info("Betting codes table doesn't exist, skipping migration")
            return True
        
        migrations = [
            ('betting_codes', 'expiry_date', 'DATETIME'),
            ('betting_codes', 'featured', 'BOOLEAN DEFAULT FALSE'),
            ('betting_codes', 'confidence', 'INTEGER'),
            ('betting_codes', 'notes', 'TEXT')
        ]
        
        success = True
        for table, column, column_type in migrations:
            if not self.add_column_if_not_exists(table, column, column_type):
                success = False
        
        return success
    
    def migration_003_create_indexes(self) -> bool:
        """Migration 003: Create database indexes for performance."""
        logger.info("Running migration 003: Create indexes")
        
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_predictions_fixture_id ON predictions (fixture_id)",
            "CREATE INDEX IF NOT EXISTS idx_predictions_type ON predictions (prediction_type)",
            "CREATE INDEX IF NOT EXISTS idx_predictions_created_at ON predictions (created_at)",
            "CREATE INDEX IF NOT EXISTS idx_fixtures_date ON fixtures (date)",
            "CREATE INDEX IF NOT EXISTS idx_fixtures_league_id ON fixtures (league_id)",
            "CREATE INDEX IF NOT EXISTS idx_betting_codes_punter_id ON betting_codes (punter_id)",
            "CREATE INDEX IF NOT EXISTS idx_betting_codes_featured ON betting_codes (featured)",
            "CREATE INDEX IF NOT EXISTS idx_betting_codes_created_at ON betting_codes (created_at)"
        ]
        
        from sqlalchemy import text
        db = next(get_db())
        try:
            for index_sql in indexes:
                try:
                    db.execute(text(index_sql))
                    logger.info(f"✅ Created index: {index_sql.split('idx_')[1].split(' ')[0]}")
                except Exception as e:
                    logger.warning(f"⚠️  Index creation failed: {e}")

            db.commit()
            return True
        except Exception as e:
            logger.error(f"❌ Failed to create indexes: {e}")
            return False
        finally:
            db.close()
    
    def migration_004_optimize_database(self) -> bool:
        """Migration 004: Apply database optimizations."""
        logger.info("Running migration 004: Database optimizations")
        
        optimizations = [
            "PRAGMA journal_mode = WAL",
            "PRAGMA synchronous = NORMAL",
            "PRAGMA cache_size = 10000",
            "PRAGMA temp_store = MEMORY",
            "PRAGMA mmap_size = 268435456"  # 256MB
        ]
        
        from sqlalchemy import text
        db = next(get_db())
        try:
            for optimization in optimizations:
                db.execute(text(optimization))
                logger.info(f"✅ Applied: {optimization}")

            return True
        except Exception as e:
            logger.error(f"❌ Failed to apply optimizations: {e}")
            return False
        finally:
            db.close()
    
    def run_all_migrations(self) -> bool:
        """Run all database migrations."""
        logger.info("🔄 Starting database migrations...")
        
        # Create backup first
        backup_path = self.backup_database()
        if not backup_path and os.path.exists(self.get_database_path()):
            logger.error("Failed to create database backup. Aborting migrations.")
            return False
        
        # Initialize database if it doesn't exist
        init_db()
        
        # Run migrations in order
        migrations = [
            ("001_add_prediction_categories", self.migration_001_add_prediction_categories),
            ("002_add_betting_code_fields", self.migration_002_add_betting_code_fields),
            ("003_create_indexes", self.migration_003_create_indexes),
            ("004_optimize_database", self.migration_004_optimize_database)
        ]
        
        success = True
        for migration_name, migration_func in migrations:
            try:
                if migration_func():
                    self.migrations_applied.append(migration_name)
                    logger.info(f"✅ Migration {migration_name} completed")
                else:
                    self.migration_errors.append(migration_name)
                    logger.error(f"❌ Migration {migration_name} failed")
                    success = False
            except Exception as e:
                self.migration_errors.append(f"{migration_name}: {str(e)}")
                logger.error(f"❌ Migration {migration_name} failed with exception: {e}")
                success = False
        
        # Summary
        logger.info(f"\n{'='*50}")
        logger.info("MIGRATION SUMMARY")
        logger.info(f"{'='*50}")
        logger.info(f"Applied: {len(self.migrations_applied)}")
        logger.info(f"Failed: {len(self.migration_errors)}")
        
        if self.migrations_applied:
            logger.info("✅ Successfully applied:")
            for migration in self.migrations_applied:
                logger.info(f"  - {migration}")
        
        if self.migration_errors:
            logger.info("❌ Failed migrations:")
            for error in self.migration_errors:
                logger.info(f"  - {error}")
        
        if success:
            logger.info("🎉 All migrations completed successfully!")
        else:
            logger.error("💥 Some migrations failed. Check logs for details.")
            if backup_path:
                logger.info(f"Database backup available at: {backup_path}")
        
        return success

def main():
    """Main migration function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Run database migrations for production")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be migrated without applying changes")
    parser.add_argument("--backup-only", action="store_true", help="Only create a backup")
    
    args = parser.parse_args()
    
    migrator = DatabaseMigrator()
    
    if args.backup_only:
        backup_path = migrator.backup_database()
        if backup_path:
            logger.info(f"✅ Backup created: {backup_path}")
            sys.exit(0)
        else:
            logger.error("❌ Backup failed")
            sys.exit(1)
    
    if args.dry_run:
        logger.info("🔍 DRY RUN MODE - No changes will be applied")
        # In a real implementation, you'd show what would be changed
        logger.info("Would run migrations: 001, 002, 003, 004")
        sys.exit(0)
    
    success = migrator.run_all_migrations()
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
