"""
Growth Engine orchestration.

`run_daily()` is the whole pipeline: read the published card, build the
dataset, render content, store it, and publish whatever is due on a trusted
channel. It is safe to call on a timer and safe to call twice.

The hard rule this module exists to keep: **the Growth Engine must never be
able to break prediction generation.** It is invoked from the same daemon
thread that keeps the daily card fresh, so every step is wrapped and the
function returns a report instead of raising. A Telegram outage, a template
bug or a dead social API all end as a recorded failure, never as an exception
climbing back into the prediction loop.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# WAT is UTC+1 with no daylight saving, matching leagues.daily_feed.
WAT_OFFSET = timedelta(hours=1)


def _wat_now() -> datetime:
    return datetime.now(timezone.utc) + WAT_OFFSET


def _due_templates(now_utc: datetime, schedule: dict) -> list[str]:
    """Templates whose scheduled time has passed today.

    Compares on elapsed minutes rather than an exact match because the loop
    ticks every 15 minutes and would otherwise skip a slot whenever a tick
    landed either side of it. Duplicate protection is what makes "has passed"
    safe to act on repeatedly.
    """
    due = []
    minutes_now = now_utc.hour * 60 + now_utc.minute
    for template, hhmm in (schedule or {}).items():
        try:
            hh, mm = str(hhmm).split(":")
            slot = int(hh) * 60 + int(mm)
        except Exception:
            continue
        if minutes_now >= slot:
            due.append(template)
    return due


def run_daily(force: bool = False, publish: bool = True,
              only_templates: Optional[list[str]] = None) -> dict:
    """Generate and distribute today's content. Never raises."""
    report: dict[str, Any] = {
        "ok": False, "date": None, "generated": 0, "stored": 0,
        "skipped": 0, "published": [], "failed": [], "notes": [],
    }

    try:
        from growth.models import (
            ensure_tables, get_setting, channel_auto_publishes, Status,
        )
        from growth import content as gc
        from growth import dataset as ds
        from growth import store
        from growth.publishers import get_sender

        ensure_tables()

        if not get_setting("engine_enabled", True) and not force:
            report["notes"].append("engine disabled in settings")
            return report

        # 1) Verify a card exists. No card means no marketing — never invent one.
        data = ds.build()
        if not data:
            report["notes"].append("no published card yet today")
            return report

        # Publication is keyed on the *publishing day*, not the card's fixture
        # date. Those differ: when the current day is too thin the card falls
        # forward to the next day with enough fixtures, and on 19 August that
        # shift mid-afternoon changed the key from 08-19 to 08-20, so every
        # template re-published — two results posts sixteen minutes apart with
        # different numbers, then a fresh "Thursday, 20 August" card that
        # evening. One post per template per calendar day, whichever fixtures
        # the card happens to be pointing at.
        from leagues.daily_feed import _publish_date
        publish_key = _publish_date()
        report["date"] = publish_key
        report["card_date"] = data["date"]

        # 2) Render everything.
        items = gc.generate(data)
        report["generated"] = len(items)
        if not items:
            report["notes"].append("nothing to say from today's card")
            return report

        # Content is stored under the publishing day so the duplicate guard
        # and the archive agree on what "today" means.
        for item in items:
            item["date"] = publish_key

        # 3) Store. Hash-keyed, so a second run stores nothing new.
        stored = store.store_items(items)
        report["stored"] = stored["created"]
        report["skipped"] = stored["skipped"]

        if not publish:
            report["ok"] = True
            report["notes"].append("generation only, publishing skipped")
            return report

        # 4) Publish what is due on channels trusted to post unattended.
        schedule = get_setting("schedule") or {}
        now = datetime.now(timezone.utc)
        due = set(only_templates or _due_templates(now, schedule))
        if force and only_templates:
            due = set(only_templates)

        for row in store.list_content(publish_date=publish_key):
            channel, template = row["platform"], row["template"]

            if template not in due:
                continue
            if row["status"] not in Status.PUBLISHABLE:
                continue
            if not channel_auto_publishes(channel):
                continue

            # Isolated per item: one channel raising must not cost the others
            # their post. Without this a single broken integration takes the
            # whole day's distribution down, which is exactly the coupling the
            # engine is supposed to avoid.
            try:
                sender = get_sender(channel)
                if sender is None:
                    # Draft-only channel (social). Content is stored for a human.
                    continue
                result = store.publish_one(row["id"], sender)
            except Exception as e:
                logger.error(f"growth: channel {channel} raised for {template}: {e}",
                             exc_info=True)
                report["failed"].append(
                    {"channel": channel, "template": template,
                     "id": row["id"], "reason": str(e)}
                )
                continue

            if result.get("ok"):
                report["published"].append(
                    {"channel": channel, "template": template, "id": row["id"]}
                )
            elif result.get("reason") not in (None, "already published or in flight"):
                report["failed"].append(
                    {"channel": channel, "template": template,
                     "id": row["id"], "reason": result.get("reason")}
                )

        report["ok"] = True
        logger.info(
            f"growth: {report['date']} generated={report['generated']} "
            f"stored={report['stored']} skipped={report['skipped']} "
            f"published={len(report['published'])} failed={len(report['failed'])}"
        )
        return report

    except Exception as e:
        # Deliberately swallowed: this runs alongside prediction generation.
        logger.error(f"growth: run_daily failed: {e}", exc_info=True)
        report["notes"].append(f"error: {e}")
        return report


def retry_failed() -> dict:
    """Re-attempt failed publications that are due. Never raises."""
    out = {"attempted": 0, "recovered": 0, "still_failing": 0}
    try:
        from growth import store
        from growth.publishers import get_sender

        for pub in store.retryable_publications():
            sender = get_sender(pub["channel"])
            if sender is None or not pub.get("content_id"):
                continue
            out["attempted"] += 1
            result = store.publish_one(pub["content_id"], sender)
            if result.get("ok"):
                out["recovered"] += 1
            else:
                out["still_failing"] += 1
    except Exception as e:
        logger.error(f"growth: retry_failed failed: {e}", exc_info=True)
    return out


def status() -> dict:
    """Snapshot for the dashboard and for health checks."""
    try:
        from growth.models import all_settings, ensure_tables
        from growth import store
        from growth.publishers import LIVE_CHANNELS, DRAFT_ONLY_CHANNELS
        from growth.publishers.telegram import is_configured

        ensure_tables()
        today = _wat_now().strftime("%Y-%m-%d")
        content = store.list_content(publish_date=today)
        pubs = store.list_publications(publish_date=today)

        by_status: dict[str, int] = {}
        for row in content:
            by_status[row["status"]] = by_status.get(row["status"], 0) + 1

        return {
            "date": today,
            "settings": all_settings(),
            "content_total": len(content),
            "content_by_status": by_status,
            "publications": pubs,
            "channels": {
                "live": sorted(LIVE_CHANNELS),
                "draft_only": sorted(DRAFT_ONLY_CHANNELS),
                "telegram_configured": is_configured(),
            },
        }
    except Exception as e:
        logger.error(f"growth: status failed: {e}", exc_info=True)
        return {"error": str(e)}
