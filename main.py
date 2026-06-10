"""
Main application.
"""

import logging
import os
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy.orm import Session

import threading

from api.api import api_router
from database import init_db, get_db
from utils.config import settings
from utils.error_handling import setup_exception_handlers
from utils.security import SecurityMiddleware, RateLimitMiddleware

# ---------------------------------------------------------------------------
# Sentry — error tracking (no-op when SENTRY_DSN is not set)
# ---------------------------------------------------------------------------
_SENTRY_DSN = os.getenv("SENTRY_DSN", "")
if _SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            environment=os.getenv("ENVIRONMENT", "production"),
            traces_sample_rate=0.1,   # capture 10% of transactions for performance
            integrations=[FastApiIntegration(), SqlalchemyIntegration()],
        )
        logging.getLogger(__name__).info("Sentry error tracking enabled")
    except ImportError:
        logging.getLogger(__name__).warning(
            "SENTRY_DSN is set but sentry-sdk is not installed — "
            "add sentry-sdk to requirements.txt"
        )

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# httpx logs full request URLs at INFO — the Telegram bot token is part of the
# URL, so it would leak into production logs. Keep these loggers at WARNING.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

# Initialize database (skip for Railway deployment if no DATABASE_URL)
try:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        init_db()
        logger.info("Database initialized successfully")
    else:
        logger.warning("No DATABASE_URL found - skipping database initialization for Railway deployment")
except Exception as e:
    logger.error(f"Failed to initialize database: {str(e)}")
    # Don't raise in Railway deployment - let app start without DB for now
    if os.getenv("ENVIRONMENT") != "production":
        raise

# Create FastAPI app with enhanced configuration
app = FastAPI(
    title="BetSightly Football Predictions API",
    description="Advanced ML-powered football match predictions with confidence scoring",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None
)

# Phase 5: Re-enable production middleware
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "*.betsightly.com", "*.onrender.com", "*.railway.app", "testserver"]
)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityMiddleware)

# CORS — accepts the production Vercel domain + any preview deploy
# (betsightly-frontend.vercel.app and betsightly-frontend-HASH-XXX.vercel.app),
# plus any explicit ALLOWED_ORIGINS env var, plus local dev.
_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "")
_explicit_origins = [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]

_defaults = [
    "https://betsightly-frontend.vercel.app",
    "https://betsightly.com",
    "https://www.betsightly.com",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:5180",
]
_allowed_origins = list(set(_explicit_origins + _defaults))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    # Matches: betsightly-frontend.vercel.app AND betsightly-frontend-anything.vercel.app
    # (so all Vercel preview deploys work — they look like betsightly-frontend-abc123-team.vercel.app)
    allow_origin_regex=r"https://betsightly-frontend([-.][^.]+)?\.vercel\.app",
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    max_age=3600,
)
logger.info(f"CORS allows: {_allowed_origins} + betsightly-frontend*.vercel.app")

# Phase 5: Re-enable exception handlers
setup_exception_handlers(app)

# Include API router
app.include_router(api_router, prefix="/api")

# World Cup 2026 endpoints
try:
    from worldcup.api import router as worldcup_router
    app.include_router(worldcup_router)
    logger.info("World Cup 2026 API endpoints registered")
except ImportError as e:
    logger.warning(f"World Cup module not available: {e}")

# Ensure rollover-chain table exists in PostgreSQL
try:
    from worldcup.rollover_db import ensure_table as _rollover_ensure_table
    _rollover_ensure_table()
except Exception as e:
    logger.warning(f"Could not ensure rollover_days table: {e}")

# Start background results checker (every 6h)
try:
    from worldcup.results_checker import start_background_loop as _start_results_loop
    _start_results_loop()
except Exception as e:
    logger.warning(f"Could not start results checker: {e}")


def _start_telegram_bot_thread():
    """
    Spawn the Telegram bot polling loop in a supervised daemon thread.

    The bot crashes routinely during deploys (Telegram returns 409 Conflict
    while old and new instances briefly poll simultaneously). Instead of
    dying silently until the next deploy, restart with backoff — the old
    instance exits within a minute and the retry then succeeds.
    """
    import threading
    import asyncio
    import time as _time

    MAX_RESTARTS = 10

    def _run():
        restarts = 0
        while restarts <= MAX_RESTARTS:
            try:
                # The bot needs its own event loop inside this thread
                asyncio.set_event_loop(asyncio.new_event_loop())
                from telegram_bot import main as _bot_main
                _bot_main()
                logger.info("Telegram bot exited cleanly")
                return
            except Exception as e:
                restarts += 1
                backoff = min(30 * restarts, 300)  # 30s, 60s, ... capped at 5 min
                logger.error(
                    f"Telegram bot crashed ({restarts}/{MAX_RESTARTS}): {e} — "
                    f"restarting in {backoff}s"
                )
                _time.sleep(backoff)
        logger.error("Telegram bot exceeded max restarts — giving up until next deploy")

    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        logger.info("Telegram bot disabled (TELEGRAM_BOT_TOKEN not set)")
        return

    t = threading.Thread(target=_run, daemon=True, name="telegram-bot")
    t.start()
    logger.info("Telegram bot started in supervised background thread")


try:
    _start_telegram_bot_thread()
except Exception as e:
    logger.warning(f"Could not start Telegram bot: {e}")

def _auto_generate_predictions():
    """Auto-generate today's predictions on startup (runs in background thread)."""
    import time
    time.sleep(5)  # Let the server finish booting first
    try:
        from services.daily_predictions_service import DailyPredictionsService
        from database import SessionLocal
        from services.daily_predictions_service import DailyPredictionSummary

        today_str = datetime.now().strftime("%Y-%m-%d")
        today_date = datetime.now().date()

        db = SessionLocal()
        try:
            existing = db.query(DailyPredictionSummary).filter(
                DailyPredictionSummary.prediction_date == today_date
            ).first()

            if existing and existing.generation_status == "completed":
                logger.info(f"Predictions for {today_str} already exist — skipping auto-generate")
                return

            logger.info(f"Auto-generating predictions for {today_str}...")
            service = DailyPredictionsService()
            result = service.generate_daily_predictions(today_str)
            status = result.get("status", "unknown")
            count = result.get("summary", {}).get("predictions_generated", 0)
            logger.info(f"Auto-generate complete: status={status}, predictions={count}")
        finally:
            db.close()

    except Exception as e:
        logger.error(f"Auto-generate predictions failed: {e}")

# Start auto-generation in background thread on app startup
threading.Thread(target=_auto_generate_predictions, daemon=True).start()
logger.info("Background prediction auto-generation scheduled")


@app.get("/")
def root():
    """Root endpoint with enhanced information."""
    return {
        "service": "BetSightly Football Predictions API",
        "version": "1.0.0",
        "status": "operational",
        "message": "Advanced ML-powered football predictions",
        "docs_url": "/docs" if settings.DEBUG else "Contact admin for API documentation",
        "health_check": "/api/health/",
        "predictions": "/api/predictions/",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/health")
def health_check():
    """Basic health check endpoint.

    Intentionally duplicates the /api/health/ router route: this one answers
    the no-trailing-slash form without a 307 redirect, which some load
    balancer probes don't follow. Keep both.
    """
    try:
        return {
            "status": "healthy",
            "service": "BetSightly API",
            "version": "1.0.0",
            "timestamp": datetime.now().isoformat(),
            "environment": os.getenv("ENVIRONMENT", "production")
        }
    except Exception as e:
        # Fallback response if anything fails
        return {
            "status": "healthy",
            "service": "BetSightly API",
            "version": "1.0.0",
            "error": "health check error"
        }

