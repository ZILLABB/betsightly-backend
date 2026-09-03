"""
Growth Engine persistence.

Follows the conventions already in the codebase: SQLAlchemy models on the
shared `Base`, created through `ensure_tables()` rather than Alembic (the
project has one migration and creates everything via `create_all`).

Duplicate protection is a database constraint, not application logic. The
publish path is reachable from the daily thread, the Telegram job and an admin
button, so "check then insert" in Python has a race between them. A unique
index on (publish_date, channel, template) means the second writer gets an
IntegrityError and stops, whatever order they arrive in.

That matters more than it looks: the app currently runs `--workers 1`, so
in-process guards happen to work today. The moment Render scales to two
workers, every in-memory guard silently stops working and the channel gets
two posts. The constraint keeps holding.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer, String, Text, UniqueConstraint, Index,
)

from database import Base, SessionLocal

logger = logging.getLogger(__name__)


# ── Status vocabulary ──────────────────────────────────────

class Status:
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    ALL = (DRAFT, APPROVED, SCHEDULED, PUBLISHED, FAILED, CANCELLED)
    # Statuses from which publishing is legitimate.
    PUBLISHABLE = (APPROVED, SCHEDULED)


class GrowthContent(Base):
    """One rendered piece of content for one platform on one day."""
    __tablename__ = "growth_content"

    id = Column(Integer, primary_key=True, autoincrement=True)
    publish_date = Column(String(10), nullable=False, index=True)
    template = Column(String(32), nullable=False, index=True)
    platform = Column(String(24), nullable=False, index=True)

    payload = Column(Text, nullable=False)          # JSON
    url = Column(String(512), nullable=True)
    content_hash = Column(String(64), nullable=False, unique=True, index=True)

    status = Column(String(16), nullable=False, default=Status.DRAFT, index=True)
    error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(String(64), nullable=True)
    published_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_growth_content_date_platform", "publish_date", "platform"),
    )

    def as_dict(self, include_payload: bool = True) -> dict:
        out = {
            "id": self.id,
            "publish_date": self.publish_date,
            "template": self.template,
            "platform": self.platform,
            "url": self.url,
            "hash": self.content_hash,
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "published_at": self.published_at.isoformat() if self.published_at else None,
        }
        if include_payload:
            try:
                out["payload"] = json.loads(self.payload)
            except Exception:
                out["payload"] = {}
        return out


class GrowthPublication(Base):
    """A publish attempt against one channel.

    The unique constraint is the duplicate guard for the whole engine: one
    row per (date, channel, template), so a second run cannot post the same
    thing twice however it was triggered.
    """
    __tablename__ = "growth_publications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    content_id = Column(Integer, nullable=True, index=True)
    publish_date = Column(String(10), nullable=False, index=True)
    channel = Column(String(24), nullable=False, index=True)
    template = Column(String(32), nullable=False)

    status = Column(String(16), nullable=False, default=Status.SCHEDULED, index=True)
    external_id = Column(String(128), nullable=True)   # e.g. Telegram message_id
    attempts = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    next_retry_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    published_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("publish_date", "channel", "template",
                         name="uq_growth_pub_date_channel_template"),
    )

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "content_id": self.content_id,
            "publish_date": self.publish_date,
            "channel": self.channel,
            "template": self.template,
            "status": self.status,
            "external_id": self.external_id,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class GrowthSetting(Base):
    """Admin-controlled configuration, one row per key.

    Key/value rather than a columned singleton so a new control can be added
    without a migration on a database that has no migration discipline.
    """
    __tablename__ = "growth_settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=True)      # JSON-encoded
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GrowthEvent(Base):
    """One attributed visit or action on the site.

    Deliberately not tied to an account: the frontend creates a random,
    first-party browser ID and the API stores only a keyed hash. It survives
    normal return visits but cannot link browsers or devices. A separate
    session hash scopes one tab session. Raw IP addresses are never stored.
    """
    __tablename__ = "growth_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_date = Column(String(10), nullable=False, index=True)
    event_type = Column(String(40), nullable=False, index=True)
    event_class = Column(String(16), nullable=True, index=True)  # USER_EVENT|SYSTEM_EVENT
    path = Column(String(256), nullable=True)

    source = Column(String(64), nullable=True, index=True)     # utm_source
    medium = Column(String(64), nullable=True)                 # utm_medium
    campaign = Column(String(64), nullable=True, index=True)   # utm_campaign
    content_tag = Column(String(64), nullable=True)            # utm_content
    utm_term = Column(String(64), nullable=True)
    ref = Column(String(64), nullable=True, index=True)        # creator referral

    visitor_hash = Column(String(32), nullable=True, index=True)
    session_hash = Column(String(32), nullable=True, index=True)
    event_key = Column(String(64), nullable=True, index=True)
    is_new_visitor = Column(Boolean, default=True)
    referrer_host = Column(String(128), nullable=True)

    # Non-sensitive product context. Keeping commonly grouped dimensions in
    # columns avoids parsing JSON for every dashboard request; metadata holds
    # optional details that are not used as primary dimensions.
    tier = Column(String(32), nullable=True, index=True)
    target_odds = Column(Float, nullable=True)
    booking_status = Column(String(32), nullable=True, index=True)
    leg_count = Column(Integer, nullable=True)
    actual_odds = Column(Float, nullable=True)
    country = Column(String(8), nullable=True, index=True)
    country_code = Column(String(2), nullable=True, index=True)
    region = Column(String(96), nullable=True)
    city = Column(String(96), nullable=True)
    timezone = Column(String(64), nullable=True)
    device_category = Column(String(16), nullable=True, index=True)
    os_family = Column(String(24), nullable=True)
    browser_family = Column(String(32), nullable=True)
    screen_width = Column(Integer, nullable=True)
    screen_height = Column(Integer, nullable=True)
    booking_id = Column(String(64), nullable=True, index=True)
    product_source = Column(String(24), nullable=True, index=True)
    metadata_json = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_growth_events_date_type", "event_date", "event_type"),
        Index("ix_growth_events_date_source", "event_date", "source"),
    )


class GrowthReferral(Base):
    """A creator or partner referral code."""
    __tablename__ = "growth_referrals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(64), nullable=False, unique=True, index=True)
    name = Column(String(128), nullable=True)
    note = Column(Text, nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


_TABLES = [
    GrowthContent.__table__,
    GrowthPublication.__table__,
    GrowthSetting.__table__,
    GrowthEvent.__table__,
    GrowthReferral.__table__,
]


def ensure_tables() -> bool:
    """Create the growth tables if absent. Safe to call repeatedly."""
    try:
        from database import engine
        Base.metadata.create_all(bind=engine, tables=_TABLES)
        # create_all does not add columns to an existing installation. This
        # project already uses additive runtime migrations for operational
        # tables, so analytics follows the same safe, idempotent pattern.
        from sqlalchemy import inspect, text
        existing = {c["name"] for c in inspect(engine).get_columns("growth_events")}
        additions = {
            "session_hash": "VARCHAR(32)", "event_key": "VARCHAR(64)",
            "event_class": "VARCHAR(16)",
            "tier": "VARCHAR(32)", "target_odds": "FLOAT",
            "booking_status": "VARCHAR(32)", "leg_count": "INTEGER",
            "actual_odds": "FLOAT", "country": "VARCHAR(8)",
            "country_code": "VARCHAR(2)", "region": "VARCHAR(96)",
            "city": "VARCHAR(96)", "timezone": "VARCHAR(64)",
            "device_category": "VARCHAR(16)", "os_family": "VARCHAR(24)",
            "browser_family": "VARCHAR(32)", "screen_width": "INTEGER",
            "screen_height": "INTEGER", "booking_id": "VARCHAR(64)",
            "product_source": "VARCHAR(24)", "utm_term": "VARCHAR(64)",
            "metadata_json": "TEXT",
        }
        with engine.begin() as conn:
            for name, sql_type in additions.items():
                if name not in existing:
                    conn.execute(text(
                        f"ALTER TABLE growth_events ADD COLUMN {name} {sql_type}"))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_growth_events_date_visitor "
                "ON growth_events (event_date, visitor_hash)"))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_growth_events_event_key "
                "ON growth_events (event_key)"))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_growth_events_class_date "
                "ON growth_events (event_class, event_date)"))
        return True
    except Exception as e:
        logger.warning(f"Could not ensure growth tables: {e}")
        return False


# ── Settings access ────────────────────────────────────────

DEFAULT_SETTINGS: dict[str, Any] = {
    "engine_enabled": True,
    # Telegram is verified and already publishes today, so it starts automatic.
    # Everything else starts in approval mode, per the launch decision — an
    # integration that posts publicly should prove itself under supervision.
    "channel_enabled": {
        "telegram": True, "website": True,
        "instagram": True, "facebook": True, "tiktok": True,
        "x": False, "youtube": True,
    },
    "channel_auto_publish": {
        "telegram": True, "website": True,
        "instagram": False, "facebook": False, "tiktok": False,
        "x": False, "youtube": False,
    },
    # Times are UTC. WAT is UTC+1, so 07:00 UTC is the 08:00 WAT card publish.
    "schedule": {
        "daily_5": "07:30",
        "rollover": "07:35",
        "two_odds": "14:00",
        "results": "21:00",
    },
    "default_landing": "predictions",
    "max_retries": 3,
    "retry_base_seconds": 60,
}


def get_setting(key: str, default: Any = None) -> Any:
    try:
        db = SessionLocal()
        try:
            row = db.query(GrowthSetting).filter(GrowthSetting.key == key).first()
            if not row or row.value is None:
                return DEFAULT_SETTINGS.get(key, default)
            value = json.loads(row.value)
            if key == "schedule" and isinstance(value, dict):
                # Existing installations keep their saved schedule row across
                # deploys. Merge in newly supported templates and remove the
                # retired Value post instead of requiring a manual DB edit.
                value = {**DEFAULT_SETTINGS["schedule"], **value}
                value.pop("value", None)
            return value
        finally:
            db.close()
    except Exception:
        return DEFAULT_SETTINGS.get(key, default)


def set_setting(key: str, value: Any) -> bool:
    try:
        db = SessionLocal()
        try:
            row = db.query(GrowthSetting).filter(GrowthSetting.key == key).first()
            payload = json.dumps(value)
            if row:
                row.value = payload
            else:
                db.add(GrowthSetting(key=key, value=payload))
            db.commit()
            return True
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"set_setting({key}) failed: {e}")
        return False


def all_settings() -> dict:
    """Effective settings — stored values layered over the defaults."""
    out = dict(DEFAULT_SETTINGS)
    try:
        db = SessionLocal()
        try:
            for row in db.query(GrowthSetting).all():
                if row.value is None:
                    continue
                try:
                    out[row.key] = json.loads(row.value)
                except Exception:
                    continue
        finally:
            db.close()
    except Exception:
        pass
    return out


def channel_is_enabled(channel: str) -> bool:
    return bool((get_setting("channel_enabled") or {}).get(channel, False))


def channel_auto_publishes(channel: str) -> bool:
    """Auto-publish requires the channel to be both enabled and trusted."""
    if not channel_is_enabled(channel):
        return False
    return bool((get_setting("channel_auto_publish") or {}).get(channel, False))
