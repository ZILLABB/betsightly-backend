"""
Storing and publishing generated content.

Everything that can post publicly on the user's behalf goes through here, and
the two guarantees this module makes are:

- **Generation is idempotent.** Content is keyed by hash, so running the job
  twice over unchanged data stores nothing new.
- **Publishing happens at most once.** A publication row is claimed with a
  unique constraint *before* the network call, so two concurrent runs cannot
  both send. If the send then fails, the claim is marked FAILED and becomes
  retryable — the row is a lock, not a lie about having posted.

The ordering matters and is easy to get backwards: claiming after sending
would mean a crash between send and insert loses the record and the next run
posts again.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from sqlalchemy.exc import IntegrityError

from database import SessionLocal
from growth.models import (
    GrowthContent, GrowthPublication, Status,
    channel_auto_publishes, channel_is_enabled, get_setting,
)

logger = logging.getLogger(__name__)


def store_items(items: list[dict]) -> dict:
    """Persist generated content. Returns counts of created vs already-present.

    Each item's status is decided by whether its channel is trusted to publish
    without review: trusted channels go straight to APPROVED, everything else
    waits as DRAFT for an admin.
    """
    created = skipped = 0
    ids: list[int] = []

    db = SessionLocal()
    try:
        for item in items:
            existing = (
                db.query(GrowthContent)
                .filter(GrowthContent.content_hash == item["hash"])
                .first()
            )
            if existing:
                skipped += 1
                ids.append(existing.id)
                continue

            status = (Status.APPROVED if channel_auto_publishes(item["platform"])
                      else Status.DRAFT)
            row = GrowthContent(
                publish_date=item["date"],
                template=item["template"],
                platform=item["platform"],
                payload=json.dumps(item["payload"], ensure_ascii=False, default=str),
                url=item.get("url"),
                content_hash=item["hash"],
                status=status,
            )
            db.add(row)
            try:
                db.commit()
                created += 1
                ids.append(row.id)
            except IntegrityError:
                # Another run inserted the same hash between our check and
                # commit. That is the guard working, not an error.
                db.rollback()
                skipped += 1

        return {"created": created, "skipped": skipped, "ids": ids}
    finally:
        db.close()


def claim_publication(publish_date: str, channel: str, template: str,
                      content_id: Optional[int] = None) -> Optional[GrowthPublication]:
    """Reserve the right to publish this (date, channel, template), or None.

    None means somebody already holds it — either it published, or it is in
    flight, or it failed and is not yet due for retry. Returning None is the
    normal way a duplicate is prevented, so callers treat it as a no-op rather
    than an error.
    """
    db = SessionLocal()
    try:
        existing = (
            db.query(GrowthPublication)
            .filter(
                GrowthPublication.publish_date == publish_date,
                GrowthPublication.channel == channel,
                GrowthPublication.template == template,
            )
            .first()
        )

        if existing:
            if existing.status == Status.PUBLISHED:
                return None
            if existing.status == Status.FAILED:
                max_retries = int(get_setting("max_retries", 3) or 3)
                if existing.attempts >= max_retries:
                    return None
                due = existing.next_retry_at
                if due and datetime.utcnow() < due:
                    return None
                existing.status = Status.SCHEDULED
                db.commit()
                db.refresh(existing)
                db.expunge(existing)
                return existing
            # SCHEDULED and not failed — another worker is mid-flight.
            return None

        row = GrowthPublication(
            content_id=content_id,
            publish_date=publish_date,
            channel=channel,
            template=template,
            status=Status.SCHEDULED,
            attempts=0,
        )
        db.add(row)
        try:
            db.commit()
            db.refresh(row)
            db.expunge(row)
            return row
        except IntegrityError:
            # Lost the race. The winner will publish.
            db.rollback()
            return None
    finally:
        db.close()


def mark_published(publication_id: int, external_id: Optional[str] = None,
                   content_id: Optional[int] = None) -> None:
    db = SessionLocal()
    try:
        row = db.query(GrowthPublication).filter(
            GrowthPublication.id == publication_id).first()
        if not row:
            return
        row.status = Status.PUBLISHED
        row.external_id = str(external_id) if external_id is not None else None
        row.attempts = (row.attempts or 0) + 1
        row.published_at = datetime.utcnow()
        row.last_error = None

        if content_id:
            content = db.query(GrowthContent).filter(
                GrowthContent.id == content_id).first()
            if content:
                content.status = Status.PUBLISHED
                content.published_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def mark_failed(publication_id: int, error: str,
                content_id: Optional[int] = None) -> None:
    """Record a failed attempt and schedule the next one with backoff."""
    db = SessionLocal()
    try:
        row = db.query(GrowthPublication).filter(
            GrowthPublication.id == publication_id).first()
        if not row:
            return
        row.attempts = (row.attempts or 0) + 1
        row.status = Status.FAILED
        row.last_error = str(error)[:2000]

        base = int(get_setting("retry_base_seconds", 60) or 60)
        # Exponential: 1x, 2x, 4x ... capped so a broken channel does not
        # schedule a retry days out and then fire it into a stale card.
        delay = min(base * (2 ** max(0, row.attempts - 1)), 3600)
        row.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)

        if content_id:
            content = db.query(GrowthContent).filter(
                GrowthContent.id == content_id).first()
            if content:
                content.status = Status.FAILED
                content.error = str(error)[:2000]
        db.commit()
        logger.warning(
            f"growth: publish failed ({row.channel}/{row.template}) "
            f"attempt {row.attempts}: {error} — retry in {delay}s"
        )
    finally:
        db.close()


def publish_one(content_id: int, sender: Callable[[dict], Any]) -> dict:
    """Publish a stored item through `sender`, once.

    `sender` receives the payload dict and returns an external id (or None).
    Any exception it raises is recorded and retried later; it never propagates
    to the caller, because the caller is usually the daily thread that also
    runs prediction work.
    """
    db = SessionLocal()
    try:
        content = db.query(GrowthContent).filter(GrowthContent.id == content_id).first()
        if not content:
            return {"ok": False, "reason": "not found"}
        if content.status not in Status.PUBLISHABLE:
            return {"ok": False, "reason": f"status is {content.status}"}
        if not channel_is_enabled(content.platform):
            return {"ok": False, "reason": f"channel {content.platform} disabled"}
        payload = json.loads(content.payload)
        date, platform, template = content.publish_date, content.platform, content.template
    finally:
        db.close()

    claim = claim_publication(date, platform, template, content_id)
    if not claim:
        return {"ok": False, "reason": "already published or in flight"}

    try:
        external_id = sender(payload)
    except Exception as e:
        mark_failed(claim.id, str(e), content_id)
        return {"ok": False, "reason": str(e), "publication_id": claim.id}

    mark_published(claim.id, external_id, content_id)
    return {"ok": True, "publication_id": claim.id, "external_id": external_id}


# ── Queries for the dashboard ──────────────────────────────

def list_content(publish_date: Optional[str] = None, platform: Optional[str] = None,
                 status: Optional[str] = None, limit: int = 200) -> list[dict]:
    db = SessionLocal()
    try:
        q = db.query(GrowthContent)
        if publish_date:
            q = q.filter(GrowthContent.publish_date == publish_date)
        if platform:
            q = q.filter(GrowthContent.platform == platform)
        if status:
            q = q.filter(GrowthContent.status == status)
        rows = q.order_by(GrowthContent.publish_date.desc(),
                          GrowthContent.id.desc()).limit(limit).all()
        return [r.as_dict() for r in rows]
    finally:
        db.close()


def get_content(content_id: int) -> Optional[dict]:
    db = SessionLocal()
    try:
        row = db.query(GrowthContent).filter(GrowthContent.id == content_id).first()
        return row.as_dict() if row else None
    finally:
        db.close()


def set_content_status(content_id: int, status: str,
                       actor: Optional[str] = None) -> Optional[dict]:
    if status not in Status.ALL:
        raise ValueError(f"unknown status {status!r}")
    db = SessionLocal()
    try:
        row = db.query(GrowthContent).filter(GrowthContent.id == content_id).first()
        if not row:
            return None
        row.status = status
        if status == Status.APPROVED:
            row.approved_at = datetime.utcnow()
            row.approved_by = actor
        db.commit()
        db.refresh(row)
        return row.as_dict()
    finally:
        db.close()


def list_publications(publish_date: Optional[str] = None, limit: int = 200) -> list[dict]:
    db = SessionLocal()
    try:
        q = db.query(GrowthPublication)
        if publish_date:
            q = q.filter(GrowthPublication.publish_date == publish_date)
        rows = q.order_by(GrowthPublication.publish_date.desc(),
                          GrowthPublication.id.desc()).limit(limit).all()
        return [r.as_dict() for r in rows]
    finally:
        db.close()


def retryable_publications(limit: int = 50) -> list[dict]:
    """Failed publications that are due for another attempt."""
    max_retries = int(get_setting("max_retries", 3) or 3)
    db = SessionLocal()
    try:
        rows = (
            db.query(GrowthPublication)
            .filter(GrowthPublication.status == Status.FAILED,
                    GrowthPublication.attempts < max_retries)
            .order_by(GrowthPublication.id.asc())
            .limit(limit)
            .all()
        )
        now = datetime.utcnow()
        return [r.as_dict() for r in rows
                if not r.next_retry_at or r.next_retry_at <= now]
    finally:
        db.close()
