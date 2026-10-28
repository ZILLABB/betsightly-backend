"""
Database configuration for the application.
"""

import json
import logging
import os
from sqlalchemy import create_engine, event
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Import settings after loading environment
from utils.config import settings

# Get database URL from settings
DATABASE_URL = settings.database.URL

# Render gives postgres:// but SQLAlchemy 2.0 needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Private NBA database mode is stage-only. Never accept this config on
# football production, and never switch the connection globally for a shared
# PostgreSQL pool. Supabase's session pooler permits per-session search_path.
_NBA_PRIVATE = os.getenv("NBA_PRIVATE_DATABASE_ONLY") == "1"
if _NBA_PRIVATE and os.getenv("ENVIRONMENT") != "staging":
    raise RuntimeError("NBA_PRIVATE_DATABASE_REQUIRES_STAGING")
# Explicit, reversible cutover. Keep the original DATABASE_URL private and
# untouched for immediate rollback; ONLY isolated NBA staging can opt in.
if os.getenv("NBA_USE_RESTORE_TARGET_AS_PRIMARY") == "1":
    if not _NBA_PRIVATE:
        raise RuntimeError("NBA_PRIMARY_CUTOVER_REQUIRES_PRIVATE_MODE")
    candidate = os.getenv("NBA_RESTORE_TARGET_DATABASE_URL", "")
    if not candidate.startswith(("postgresql://", "postgres://")):
        raise RuntimeError("NBA_PRIMARY_CUTOVER_TARGET_UNCONFIGURED")
    from sqlalchemy.engine import make_url
    if make_url(candidate).host == make_url(DATABASE_URL).host:
        raise RuntimeError("NBA_PRIMARY_CUTOVER_REFUSES_SOURCE_HOST")
    DATABASE_URL = candidate
    logger.info("NBA staging using isolated recovered database")


# Determine if we're using SQLite or PostgreSQL
if DATABASE_URL.startswith("sqlite") and _NBA_PRIVATE:
    raise RuntimeError("NBA_PRIVATE_DATABASE_REQUIRES_POSTGRES")
if DATABASE_URL.startswith("sqlite"):
    DB_FILE = DATABASE_URL.replace("sqlite:///", "")
    logger.info(f"Using SQLite database: {DB_FILE}")
    engine = create_engine(
        DATABASE_URL, connect_args={"check_same_thread": False}
    )
else:
    logger.info("Using PostgreSQL database")
    engine = create_engine(
        DATABASE_URL,
        pool_size=2 if _NBA_PRIVATE else 5,
        max_overflow=2 if _NBA_PRIVATE else 10,
        pool_pre_ping=True,  # Auto-reconnect on stale connections
    )
    if _NBA_PRIVATE:
        @event.listens_for(engine, "connect")
        def _pin_nba_private_schema(dbapi_connection, connection_record):
            # Fixed, privately owned schema only. Executed on every new
            # Supavisor session-pool connection; no global role alteration.
            with dbapi_connection.cursor() as cursor:
                cursor.execute("SET search_path TO nba_research")
        logger.info("NBA staging database pool pinned to private schema")

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create base class for models
Base = declarative_base()


def pool_status() -> dict:
    """Return safe connection-pool counters without exposing the database URL."""
    pool = engine.pool
    state = {"pool_class": type(pool).__name__}
    for key, attribute in (
        ("size", "size"),
        ("checked_in", "checkedin"),
        ("checked_out", "checkedout"),
        ("overflow", "overflow"),
    ):
        value = getattr(pool, attribute, None)
        if value is None:
            continue
        try:
            state[key] = value() if callable(value) else value
        except Exception:
            continue
    try:
        state["status"] = pool.status()
    except Exception:
        pass
    return state


def log_pool_status(event: str, level: int = logging.INFO, **context) -> dict:
    """Emit one structured, credential-free snapshot of pool occupancy."""
    state = pool_status()
    payload = {"event": event, **context, "pool": state}
    logger.log(level, "db_pool %s", json.dumps(payload, sort_keys=True, default=str))
    return state


def log_pool_exception(event: str, exc: Exception, **context) -> bool:
    """Log pool counters when SQLAlchemy reports a checkout timeout."""
    if not isinstance(exc, SQLAlchemyTimeoutError):
        return False
    log_pool_status(
        event,
        level=logging.ERROR,
        error_type=type(exc).__name__,
        **context,
    )
    return True

def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Initialize database with the correct schema."""
    try:
        # Import models in correct order to avoid circular dependencies
        from punter import Punter  # noqa: F401
        from bookmaker import Bookmaker  # noqa: F401
        from betting_code import BettingCode  # noqa: F401
        from fixture import Fixture  # noqa: F401
        from prediction import Prediction  # noqa: F401
        from services.push_notification_service import PushSubscription, TelegramDMSubscription  # noqa: F401
        from services.api_football_gateway import APIFootballQuota  # noqa: F401

        # Create SQLAlchemy tables (works for both SQLite and PostgreSQL)
        Base.metadata.create_all(bind=engine)
        logger.info("SQLAlchemy tables created.")

        # Apply database optimizations
        try:
            from utils.database_optimization import create_database_indexes, optimize_query_performance
            create_database_indexes()
            optimize_query_performance()
            logger.info("Database optimizations applied.")
        except ImportError:
            logger.warning("Database optimization utilities not available")
        except Exception as e:
            logger.warning(f"Failed to apply database optimizations: {str(e)}")

        logger.info("Database initialized successfully")
        return True

    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        return False
