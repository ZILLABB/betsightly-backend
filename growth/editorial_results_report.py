"""Combined published-product results for Telegram and growth channels.

This is a PUBLICATION accounting view, not BetSightly's model-scored
calibration/ROI record. An admin-curated slip counts as the published tier when
the engine had no official publication for that same date/tier. Engine takes
priority when both sources erroneously contain the same key.
"""
from __future__ import annotations

from datetime import date, timedelta


def merge_published_record(
    official: dict, official_history: list[dict],
    editorial_history: list[dict], *, as_of: str, days: int,
) -> dict:
    """Pure bounded merge, idempotent by date+tier, never alters official facts."""
    yesterday = date.fromisoformat(as_of)
    first = yesterday - timedelta(days=days - 1)
    seen = {
        (str(item.get("date")), str(item.get("category")))
        for item in official_history
        if item.get("date") and item.get("category")
    }
    merged = dict(official)
    merged["by_category"] = {
        tier: dict(info) for tier, info in (official.get("by_category") or {}).items()
    }
    editorial_rows = []
    manual = {"won": 0, "lost": 0, "void": 0, "pending": 0, "settled": 0}
    for record in editorial_history:
        if record.get("editorial_manual") is not True:
            continue
        day, tier = str(record.get("date") or ""), str(record.get("tier") or "")
        if not day or not tier:
            continue
        try:
            day_date = date.fromisoformat(day)
        except ValueError:
            continue
        key = (day, tier)
        if not first <= day_date <= yesterday or key in seen:
            continue
        status = str(record.get("status") or "pending").lower()
        if status not in {"won", "lost", "void", "pending"}:
            status = "pending"
        seen.add(key)
        editorial_rows.append(record)
        manual[status] += 1
        if status in ("won", "lost"):
            manual["settled"] += 1
        merged[status] = int(merged.get(status) or 0) + 1
        if status in ("won", "lost"):
            merged["settled"] = int(merged.get("settled") or 0) + 1
        rec = merged["by_category"].setdefault(
            tier, {"unit": "published_product", "won": 0, "lost": 0,
                   "void": 0, "pending": 0, "settled": 0},
        )
        rec[status] = int(rec.get(status) or 0) + 1
        if status in ("won", "lost"):
            rec["settled"] = int(rec.get("settled") or 0) + 1
        if status == "pending" and (
            not merged.get("oldest_pending_date")
            or day < merged["oldest_pending_date"]
        ):
            merged["oldest_pending_date"] = day

    settled = int(merged.get("settled") or 0)
    merged["win_rate"] = round(int(merged.get("won") or 0) / settled, 4) if settled else None
    for rec in merged["by_category"].values():
        settled_category = int(rec.get("settled") or 0)
        rec["win_rate"] = (
            round(int(rec.get("won") or 0) / settled_category, 4)
            if settled_category else None
        )
    merged["manual_editorial"] = manual
    merged["official_model"] = {
        status: int(official.get(status) or 0)
        for status in ("won", "lost", "pending", "void", "settled")
    }
    merged["editorial_rows"] = editorial_rows
    merged["accounting_version"] = (
        str(official.get("accounting_version") or "published_product")
        + "+editorial_fill_v1"
    )
    return merged
