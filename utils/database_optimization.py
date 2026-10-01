"""
Database Optimization Utilities

This module provides utilities for optimizing database queries and preventing N+1 problems.
"""

import logging
import time
import hashlib
import json
from typing import List, Dict, Any, Optional, Callable
from functools import wraps
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import and_, or_, desc, asc, event, Engine, inspect, text
from datetime import datetime, timedelta

# Set up logging
logger = logging.getLogger(__name__)


class OptimizedQueryBuilder:
    """Builder for creating optimized database queries."""
    
    def __init__(self, session: Session):
        self.session = session
        
    def get_predictions_with_fixtures(
        self,
        date: Optional[datetime] = None,
        category: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Any]:
        """
        Get predictions with their associated fixtures in a single query.
        
        Args:
            date: Filter by date
            category: Filter by category
            limit: Limit number of results
            
        Returns:
            List of predictions with fixtures loaded
        """
        from prediction import Prediction
        from fixture import Fixture
        
        query = self.session.query(Prediction).options(
            joinedload(Prediction.fixture)
        )
        
        if date:
            start_of_day = datetime.combine(date.date(), datetime.min.time())
            end_of_day = datetime.combine(date.date(), datetime.max.time())
            query = query.join(Fixture).filter(
                and_(
                    Fixture.date >= start_of_day,
                    Fixture.date <= end_of_day
                )
            )
        
        if category:
            query = query.filter(Prediction.category == category)
            
        if limit:
            query = query.limit(limit)
            
        return query.all()
    
    def get_betting_codes_with_relations(
        self,
        skip: int = 0,
        limit: int = 100,
        punter_id: Optional[int] = None,
        bookmaker_id: Optional[int] = None,
        featured: Optional[bool] = None
    ) -> List[Any]:
        """
        Get betting codes with punter and bookmaker data in a single query.
        
        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            punter_id: Filter by punter ID
            bookmaker_id: Filter by bookmaker ID
            featured: Filter by featured status
            
        Returns:
            List of betting codes with relations loaded
        """
        from betting_code import BettingCode
        from punter import Punter
        from bookmaker import Bookmaker
        
        query = self.session.query(BettingCode).options(
            joinedload(BettingCode.punter),
            joinedload(BettingCode.bookmaker)
        )
        
        if punter_id:
            query = query.filter(BettingCode.punter_id == punter_id)
            
        if bookmaker_id:
            query = query.filter(BettingCode.bookmaker_id == bookmaker_id)
            
        if featured is not None:
            query = query.filter(BettingCode.featured == featured)
            
        return query.offset(skip).limit(limit).all()
    
    def get_prediction_combinations_optimized(
        self,
        category: str,
        date: Optional[datetime] = None,
        limit: int = 10
    ) -> List[Any]:
        """
        Get prediction combinations with all related data in optimized queries.
        
        Args:
            category: Category to filter by
            date: Date to filter by
            limit: Maximum number of combinations to return
            
        Returns:
            List of prediction combinations with relations loaded
        """
        from prediction_combination import PredictionCombination
        
        query = self.session.query(PredictionCombination).options(
            selectinload(PredictionCombination.items)
        ).filter(PredictionCombination.category == category)
        
        if date:
            start_of_day = datetime.combine(date.date(), datetime.min.time())
            end_of_day = datetime.combine(date.date(), datetime.max.time())
            query = query.filter(
                and_(
                    PredictionCombination.created_at >= start_of_day,
                    PredictionCombination.created_at <= end_of_day
                )
            )
        
        return query.order_by(
            desc(PredictionCombination.combined_confidence)
        ).limit(limit).all()


class AdvancedDatabaseCache:
    """Advanced in-memory cache with LRU eviction, statistics, and query optimization."""

    def __init__(self, ttl_seconds: int = 300, max_size: int = 1000):
        self.cache = {}
        self.access_times = {}
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self.stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'sets': 0,
            'total_queries': 0
        }

    def _generate_key(self, query: str, params: Dict = None) -> str:
        """Generate a cache key from query and parameters."""
        key_data = {'query': query, 'params': params or {}}
        key_string = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_string.encode()).hexdigest()

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache with LRU tracking."""
        self.stats['total_queries'] += 1

        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl_seconds:
                self.access_times[key] = time.time()
                self.stats['hits'] += 1
                return value
            else:
                # Remove expired entry
                del self.cache[key]
                if key in self.access_times:
                    del self.access_times[key]

        self.stats['misses'] += 1
        return None

    def set(self, key: str, value: Any) -> None:
        """Set value in cache with LRU eviction."""
        # Check if we need to evict items
        if len(self.cache) >= self.max_size and key not in self.cache:
            self._evict_lru()

        self.cache[key] = (value, time.time())
        self.access_times[key] = time.time()
        self.stats['sets'] += 1

    def _evict_lru(self) -> None:
        """Evict the least recently used item."""
        if not self.access_times:
            return

        lru_key = min(self.access_times.keys(), key=lambda k: self.access_times[k])
        del self.cache[lru_key]
        del self.access_times[lru_key]
        self.stats['evictions'] += 1

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        hit_rate = (self.stats['hits'] / self.stats['total_queries'] * 100) if self.stats['total_queries'] > 0 else 0

        return {
            **self.stats,
            'size': len(self.cache),
            'hit_rate': round(hit_rate, 2),
            'memory_usage_mb': self._estimate_memory_usage()
        }

    def _estimate_memory_usage(self) -> float:
        """Estimate memory usage in MB."""
        import sys
        total_size = 0
        for key, (value, _) in self.cache.items():
            total_size += sys.getsizeof(key) + sys.getsizeof(value)
        return round(total_size / (1024 * 1024), 2)

    def clear(self) -> None:
        """Clear all cached values."""
        self.cache.clear()
        self.access_times.clear()

    def remove(self, key: str) -> None:
        """Remove specific key from cache."""
        if key in self.cache:
            del self.cache[key]
        if key in self.access_times:
            del self.access_times[key]


class DatabaseCache:
    """Simple in-memory cache for frequently accessed database queries (backward compatibility)."""

    def __init__(self, ttl_seconds: int = 300):  # 5 minutes default TTL
        self.cache = {}
        self.ttl_seconds = ttl_seconds

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired."""
        if key in self.cache:
            value, timestamp = self.cache[key]
            if datetime.now().timestamp() - timestamp < self.ttl_seconds:
                return value
            else:
                # Remove expired entry
                del self.cache[key]
        return None

    def set(self, key: str, value: Any) -> None:
        """Set value in cache with current timestamp."""
        self.cache[key] = (value, datetime.now().timestamp())

    def clear(self) -> None:
        """Clear all cached values."""
        self.cache.clear()

    def remove(self, key: str) -> None:
        """Remove specific key from cache."""
        if key in self.cache:
            del self.cache[key]


# Global cache instances
db_cache = DatabaseCache()
advanced_cache = AdvancedDatabaseCache(ttl_seconds=300, max_size=1000)


def query_performance_monitor(func: Callable) -> Callable:
    """Decorator to monitor database query performance."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time

            if execution_time > 1.0:  # Log slow queries (>1 second)
                logger.warning(f"Slow query detected: {func.__name__} took {execution_time:.2f}s")
            else:
                logger.debug(f"Query {func.__name__} executed in {execution_time:.3f}s")

            return result
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Query {func.__name__} failed after {execution_time:.3f}s: {str(e)}")
            raise
    return wrapper


def cached_query(cache_key_prefix: str = None, ttl_seconds: int = 300):
    """Decorator to automatically cache query results."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key
            key_prefix = cache_key_prefix or func.__name__
            key_data = {
                'function': func.__name__,
                'args': str(args),
                'kwargs': str(sorted(kwargs.items()))
            }
            cache_key = advanced_cache._generate_key(str(key_data))

            # Try to get from cache
            cached_result = advanced_cache.get(cache_key)
            if cached_result is not None:
                return cached_result

            # Execute query and cache result
            result = func(*args, **kwargs)
            advanced_cache.set(cache_key, result)

            return result
        return wrapper
    return decorator


def get_cached_or_query(
    cache_key: str,
    query_func,
    *args,
    **kwargs
) -> Any:
    """
    Get data from cache or execute query and cache the result.
    
    Args:
        cache_key: Unique key for caching
        query_func: Function to execute if cache miss
        *args: Arguments for query function
        **kwargs: Keyword arguments for query function
        
    Returns:
        Query result (from cache or fresh query)
    """
    # Try to get from cache first
    cached_result = db_cache.get(cache_key)
    if cached_result is not None:
        logger.debug(f"Cache hit for key: {cache_key}")
        return cached_result
    
    # Cache miss - execute query
    logger.debug(f"Cache miss for key: {cache_key}")
    result = query_func(*args, **kwargs)
    
    # Cache the result
    db_cache.set(cache_key, result)
    
    return result


def create_database_indexes():
    """Create only indexes supported by the live schema.

    Older BetSightly deployments do not all contain the same legacy tables or
    columns.  Startup should not issue knowingly invalid DDL and then log
    UndefinedColumn/UndefinedTable warnings.  Missing legacy schema is skipped
    explicitly; this function never invents tables or columns.
    """

    from database import engine

    index_specs = [
        (
            "idx_predictions_fixture_id",
            "predictions",
            (
                "fixture_id",
            ),
        ),
        (
            "idx_predictions_category",
            "predictions",
            (
                "category",
            ),
        ),
        (
            "idx_predictions_created_at",
            "predictions",
            (
                "created_at",
            ),
        ),
        (
            "idx_fixtures_date",
            "fixtures",
            (
                "date",
            ),
        ),
        (
            "idx_fixtures_league_id",
            "fixtures",
            (
                "league_id",
            ),
        ),
        (
            "idx_fixtures_status",
            "fixtures",
            (
                "status",
            ),
        ),
        (
            "idx_betting_codes_punter_id",
            "betting_codes",
            (
                "punter_id",
            ),
        ),
        (
            "idx_betting_codes_bookmaker_id",
            "betting_codes",
            (
                "bookmaker_id",
            ),
        ),
        (
            "idx_betting_codes_featured",
            "betting_codes",
            (
                "featured",
            ),
        ),
        (
            "idx_betting_codes_created_at",
            "betting_codes",
            (
                "created_at",
            ),
        ),
        (
            "idx_prediction_combinations_category",
            "prediction_combinations",
            (
                "category",
            ),
        ),
        (
            "idx_prediction_combinations_confidence",
            "prediction_combinations",
            (
                "combined_confidence",
            ),
        ),
        (
            "idx_prediction_combinations_created_at",
            "prediction_combinations",
            (
                "created_at",
            ),
        ),
        (
            "idx_predictions_fixture_category",
            "predictions",
            (
                "fixture_id",
                "category",
            ),
        ),
        (
            "idx_fixtures_date_league",
            "fixtures",
            (
                "date",
                "league_id",
            ),
        ),
        (
            "idx_betting_codes_punter_featured",
            "betting_codes",
            (
                "punter_id",
                "featured",
            ),
        ),
    ]

    try:
        inspector = inspect(
            engine
        )

        tables = set(
            inspector.get_table_names()
        )

        columns_by_table = {}

        created = 0
        skipped = 0

        for (
            index_name,
            table_name,
            columns,
        ) in index_specs:

            if (
                table_name
                not in tables
            ):
                skipped += 1

                logger.info(
                    "Skipping unavailable index %s: table %s does not exist",
                    index_name,
                    table_name,
                )

                continue

            if (
                table_name
                not in columns_by_table
            ):
                columns_by_table[
                    table_name
                ] = {
                    column[
                        "name"
                    ]
                    for column
                    in inspector.get_columns(
                        table_name
                    )
                }

            available_columns = (
                columns_by_table[
                    table_name
                ]
            )

            missing_columns = [
                column
                for column
                in columns
                if column
                not in available_columns
            ]

            if missing_columns:
                skipped += 1

                logger.info(
                    "Skipping unavailable index %s: %s missing columns %s",
                    index_name,
                    table_name,
                    ",".join(
                        missing_columns
                    ),
                )

                continue

            column_sql = (
                ", ".join(
                    columns
                )
            )

            index_sql = (
                f"CREATE INDEX IF NOT EXISTS "
                f"{index_name} "
                f"ON {table_name} "
                f"({column_sql});"
            )

            try:
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            index_sql
                        )
                    )

                created += 1

                logger.info(
                    "Created index: %s",
                    index_name,
                )

            except Exception as exc:
                logger.warning(
                    "Index creation failed for %s: %s",
                    index_name,
                    str(
                        exc
                    ).split(
                        chr(
                            10
                        )
                    )[0],
                )

        logger.info(
            "Database index reconciliation complete: "
            "created_or_existing=%s skipped_unavailable=%s",
            created,
            skipped,
        )

    except Exception as exc:
        logger.error(
            "Error reconciling database indexes: %s",
            exc,
        )


def optimize_query_performance():
    """
    Apply database-specific optimizations.
    PRAGMA commands are SQLite-only — skip on PostgreSQL.
    """
    from database import engine, DATABASE_URL

    # PRAGMAs only work on SQLite
    if not DATABASE_URL.startswith("sqlite"):
        logger.info("PostgreSQL detected — skipping SQLite PRAGMA optimizations")
        return

    optimizations = [
        "PRAGMA journal_mode = WAL;",
        "PRAGMA synchronous = NORMAL;",
        "PRAGMA cache_size = 10000;",
        "PRAGMA temp_store = MEMORY;",
        "PRAGMA mmap_size = 268435456;",
    ]

    try:
        with engine.connect() as conn:
            for pragma in optimizations:
                conn.execute(text(pragma))
                logger.info(f"Applied optimization: {pragma}")
            logger.info("Database optimizations applied successfully")
    except Exception as e:
        logger.error(f"Error applying database optimizations: {str(e)}")
