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
    "http://localhost:3777",
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

# Multi-league prediction engine endpoints
try:
    from leagues.api import router as leagues_router
    app.include_router(leagues_router, prefix="/api/leagues")
    # Back-compat alias for older frontend builds that call /api/worldcup/*
    app.include_router(leagues_router, prefix="/api/worldcup", include_in_schema=False)
    logger.info("Leagues API endpoints registered")
except ImportError as e:
    logger.warning(f"Leagues module not available: {e}")

# Growth Engine — marketing content generation and distribution.
# Mounted outside api_router because its public half (the tracking beacon and
# the crawler-facing /p/{slug} pages) must not sit behind the API key, while
# its admin half carries its own cookie auth rather than the shared key.
try:
    from growth.api import router as growth_router, public_router as growth_public
    from growth.models import ensure_tables as _growth_ensure_tables

    app.include_router(growth_router, prefix="/api/growth")
    app.include_router(growth_public, prefix="/api/growth")
    # Share links need to be short and clean, so /p/{slug} is also served at
    # the root — a URL posted to social is read by people, not just crawlers.
    app.include_router(growth_public, prefix="", include_in_schema=False)
    _growth_ensure_tables()
    logger.info("Growth Engine endpoints registered")
except Exception as e:
    logger.warning(f"Growth Engine not available: {e}")

# Ensure rollover-chain table exists in PostgreSQL
try:
    from leagues.rollover_db import ensure_table as _rollover_ensure_table
    _rollover_ensure_table()
    from leagues.picks_db import (
        ensure_table as _slips_ensure_table,
        ensure_card_table as _cards_ensure_table,
    )
    _slips_ensure_table()
    _cards_ensure_table()
except Exception as e:
    logger.warning(f"Could not ensure rollover_days table: {e}")

# Start background results checker (every 6h) — World Cup rollover chains
try:
    from leagues.results_checker import start_background_loop as _start_results_loop
    _start_results_loop()
except Exception as e:
    logger.warning(f"Could not start results checker: {e}")


def _start_prediction_settlement_loop():
    """Settle main-pipeline predictions against real scores, once every 12h.

    Scores yesterday + today (late finishers) so the public accuracy numbers
    stay current. One football-data.org call per pass — no polling.
    """
    import threading
    import time as _time

    def _run():
        _time.sleep(120)  # let the app finish booting
        while True:
            try:
                from services.prediction_results_service import PredictionResultsService
                from datetime import datetime as _dt, timedelta as _td
                svc = PredictionResultsService()
                yesterday = (_dt.now() - _td(days=1)).strftime("%Y-%m-%d")
                today = _dt.now().strftime("%Y-%m-%d")
                svc.settle_date(yesterday)
                svc.settle_date(today)
            except Exception as e:
                logger.error(f"Prediction settlement failed: {e}")
            _time.sleep(12 * 3600)

    threading.Thread(target=_run, daemon=True, name="prediction-settlement").start()
    logger.info("Prediction settlement loop started (12h interval)")


try:
    _start_prediction_settlement_loop()
except Exception as e:
    logger.warning(f"Could not start prediction settlement loop: {e}")


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
                is_conflict = "Conflict" in str(e) or "409" in str(e)
                log = logger.warning if is_conflict else logger.error
                log(
                    f"Telegram bot {'conflict' if is_conflict else 'crashed'} "
                    f"({restarts}/{MAX_RESTARTS}): {e} — restarting in {backoff}s"
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

# Which publishing day has already had its "new predictions" alert. The loop
# ticks every 15 minutes; without this it would announce the card four times an
# hour.
# The in-memory alert guard that used to live here is gone. It reset on every
# process start, which is precisely why deploying sent a notification. The
# replacement is a claimed row in notification_deliveries, keyed on the
# publishing day and the channel — see services/push_notification_service.py.


def _ensure_today_generated():
    """Generate today's predictions + accumulator feed if missing.

    Idempotent: skips ML generation when the day's summary is completed,
    and the accumulator feed reads odds through a 6h disk cache, so calling
    this repeatedly is cheap.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_date = datetime.now().date()

    # 1) Daily ML predictions
    try:
        from services.daily_predictions_service import (
            DailyPredictionsService, DailyPredictionSummary,
        )
        from database import SessionLocal

        db = SessionLocal()
        try:
            existing = db.query(DailyPredictionSummary).filter(
                DailyPredictionSummary.prediction_date == today_date
            ).first()
            already_done = existing is not None and existing.generation_status == "completed"
        finally:
            db.close()

        if already_done:
            logger.debug(f"Predictions for {today_str} already exist")
        else:
            logger.info(f"Daily loop: generating predictions for {today_str}...")
            result = DailyPredictionsService().generate_daily_predictions(today_str)
            status = result.get("status", "unknown")
            count = result.get("summary", {}).get("predictions_generated", 0)
            logger.info(f"Daily loop: generation complete: status={status}, predictions={count}")
    except Exception as e:
        logger.error(f"Daily loop: prediction generation failed: {e}")

    # 2) Accumulator feed + rollover chain extension. Without this, the
    # chain only grows when a user happens to hit /accumulators/today —
    # the 09:00 Telegram post would find no picks on quiet mornings.
    try:
        from leagues.daily_feed import build_daily_accumulators
        build_daily_accumulators()
    except Exception as e:
        logger.error(f"Daily loop: accumulator feed build failed: {e}")

    # Subscriber alerts used to fire from here, guarded by a dict held in
    # process memory. That dict is empty in a new process, so every deploy and
    # every restart announced the day again — one notification per push, and
    # two to four whenever a deploy cycled more than once. Sitting on the boot
    # path also meant an afternoon restart re-announced the morning's card.
    #
    # The alert is now a step of the daily job in leagues/scheduler.py, inside
    # the run claim and behind a delivery row of its own, so it goes out once
    # per publishing day however often this process starts.

    # 3) Growth Engine. Runs last and swallows its own errors, so marketing
    # can never be the reason predictions fail to generate. run_daily is
    # idempotent — publication rows are claimed under a unique constraint —
    # so calling it on every 15-minute tick posts each item exactly once.
    try:
        from growth.engine import retry_failed, run_daily
        run_daily()
        retry_failed()
    except Exception as e:
        logger.error(f"Daily loop: growth engine failed: {e}")


def _start_daily_generation_loop():
    """Keep each day's artifacts present, and publish the card at 08:00 WAT.

    The audience books in the morning in Nigeria (UTC+1), so the day's card is
    generated right at 08:00 WAT with a full slate of fixtures still ahead of
    the user. Waiting for the first visitor to trigger it would publish
    whatever was left by the time someone happened to load the page.

    The loop still ticks every 15 minutes so a restart or a missed window
    recovers on its own; generation itself is idempotent and the card is
    locked once written, so extra passes are harmless.
    """
    import time as _time
    from datetime import timezone as _tz, timedelta as _td

    PUBLISH_HOUR_UTC = 7  # 08:00 WAT

    def _run():
        _time.sleep(5)  # let the server finish booting first
        last_published = None
        while True:
            try:
                now = datetime.now(_tz.utc)
                wat = now + _td(hours=1)
                wat_day = wat.strftime("%Y-%m-%d")

                _ensure_today_generated()

                # Past 08:00 WAT, run the full day: settle, refit, publish,
                # distribute. This used to build the card and nothing else, so
                # results were settled and Telegram posted only when something
                # else happened to trigger them.
                #
                # The scheduled GitHub Action runs the same job, and the job
                # claims the day in the database before doing any work — so
                # whichever fires first does it and the other returns
                # "skipped". That makes this loop a fallback rather than a
                # duplicate, and it keeps publishing if the Action is ever
                # unavailable. `last_published` stays as an in-process short
                # circuit only; the database is what actually decides.
                if wat.hour >= 8 and last_published != wat_day:
                    try:
                        from leagues.scheduler import run_daily_job
                        report = run_daily_job()
                        if report.get("status") != "skipped":
                            logger.info(
                                f"Daily run for {wat_day}: {report.get('status')} "
                                f"(failed: {report.get('failed') or 'none'})")
                        last_published = wat_day
                    except Exception as e:
                        logger.error(f"Daily run failed: {e}")
            except Exception as e:
                logger.error(f"Daily generation loop iteration failed: {e}")
            _time.sleep(900)

    threading.Thread(target=_run, daemon=True, name="daily-generation").start()
    logger.info("Daily generation loop started (15 min checks, publishes 08:00 WAT)")


_start_daily_generation_loop()


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

