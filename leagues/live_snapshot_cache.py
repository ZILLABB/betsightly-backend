"""Non-authoritative cached matchday scoreboard.

The published card and official settlement are separate. This cache handles
only provisional UI observations from configured scoreboard sources. No score
from this module ever updates a wager, published pick, win/loss, or calibration.

Unlike the historical copy/paste implementation, the cache path is anchored to
the backend repository root, never the current working directory. A date-bound
key avoids showing yesterday's games on today's scoreboard.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

CACHE_ROOT = Path(__file__).resolve().parents[1] / "cache" / "live_scores"
TTL_SECONDS = 25
MAX_SAVED_AGE_SECONDS = 18 * 3600


def _wat_day(at: datetime | None = None) -> str:
    """Cache by the displayed *publication* date, not midnight WAT.

    BetSightly publishes its next card at 08:00 WAT. Between midnight and
    07:59 WAT the previous card is still live, so a midnight cache turnover
    could discard scores before their final settlement is visible.
    """
    now = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    wall = now + timedelta(hours=1)
    if wall.hour < 8:
        wall -= timedelta(days=1)
    return wall.date().isoformat()


def _date_file(day: str, cache_root: Path) -> Path:
    # day is generated locally, never from query parameters.
    return cache_root / ("published_" + day + ".json")


def _is_snapshot(raw) -> bool:
    return (isinstance(raw, dict) and isinstance(raw.get("scores"), dict)
            and isinstance(raw.get("published_match_ids"), list)
            and isinstance(raw.get("dates"), list)
            and isinstance(raw.get("fetched_at"), str))


def _elapsed(fetched_at: str) -> float | None:
    try:
        dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return None
        return max(0., (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds())
    except (ValueError, TypeError):
        return None


class LiveScoreSnapshot:
    """Stale-while-revalidate snapshot, single-flight per process.

    The stale flag is carried per row. A failed upstream read NEVER clears the
    last visible score; stale scores are not re-labelled as live verified facts.
    Disk fallback is best effort (Render ephemeral disks may be reset).
    """

    def __init__(self, *, cache_root: Path | None = None,
                 day: Callable[[], str] = _wat_day, ttl_seconds: int = TTL_SECONDS):
        self._root = cache_root or CACHE_ROOT
        self._day_fn = day
        self._ttl = max(10, ttl_seconds)
        self._lock = threading.RLock()
        self._day = ""
        self._snapshot: dict | None = None
        self._fetched_mono = 0.
        self._refreshing = False
        self._last_error: str | None = None
        self._retry_after = 0.

    def _read_disk(self, day: str) -> dict | None:
        try:
            with _date_file(day, self._root).open("r", encoding="utf-8") as f:
                raw = json.load(f)
            if raw.get("cache_day") != day or not _is_snapshot(raw):
                return None
            age = _elapsed(raw["fetched_at"])
            if age is None or age > MAX_SAVED_AGE_SECONDS:
                return None
            return raw
        except (OSError, ValueError, TypeError):
            return None

    def _persist(self, day: str, data: dict) -> None:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            path = _date_file(day, self._root)
            temp = path.with_name(path.name + "." + str(threading.get_ident()) + ".tmp")
            try:
                with temp.open("w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
                os.replace(temp, path)
            finally:
                try:
                    temp.unlink(missing_ok=True)
                except OSError:
                    pass
        except (OSError, TypeError):
            logger.debug("Live score disk cache not writable; memory cache remains usable")

    @staticmethod
    def _combine_missing(current: dict, older: dict | None) -> dict:
        """Preserve missing scores only for IDs STILL in the published card."""
        if not older:
            return current
        allowed = set(current.get("published_match_ids") or [])
        scores = dict(current["scores"])
        for match_id, prior in older.get("scores", {}).items():
            if match_id in allowed and match_id not in scores and isinstance(prior, dict):
                scores[match_id] = dict(prior, stale=True)
        return dict(current, scores=scores)

    def _refresh(self, day: str, fetcher: Callable[[], dict]) -> None:
        try:
            fresh = fetcher()
            if not _is_snapshot(fresh) or fresh.get("error"):
                raise ValueError("unusable_score_snapshot")
            fresh = dict(fresh, cache_day=day)
            with self._lock:
                if day != self._day:
                    return
                fresh = self._combine_missing(fresh, self._snapshot)
                self._snapshot = fresh
                self._fetched_mono = time.monotonic()
                self._last_error = None
            self._persist(day, fresh)
        except Exception as exc:
            logger.warning("Matchday score refresh failed: %s", type(exc).__name__)
            with self._lock:
                self._last_error = type(exc).__name__
                self._retry_after = time.monotonic() + 15
        finally:
            with self._lock:
                self._refreshing = False

    def _present(self) -> dict:
        snap = dict(self._snapshot or {
            "scores": {}, "leagues": [], "dates": [],
            "fetched_at": None, "published_match_ids": [],
        })
        elapsed = _elapsed(snap.get("fetched_at")) if snap.get("fetched_at") else None
        stale = (elapsed is None or elapsed > self._ttl or self._last_error is not None)
        snap["scores"] = {
            k: dict(v, stale=bool(stale or v.get("stale")))
            for k, v in snap["scores"].items() if isinstance(v, dict)
        }
        snap["stale"] = bool(stale)
        snap["refreshing"] = self._refreshing
        snap["cache_age_seconds"] = int(elapsed) if elapsed is not None else None
        snap["source_error"] = self._last_error
        snap.pop("published_match_ids", None)  # internal only
        snap.pop("cache_day", None)
        return snap

    def get(self, fetcher: Callable[[], dict]) -> dict:
        day = self._day_fn()
        synchronous = False
        with self._lock:
            if self._day != day:
                self._day = day
                self._snapshot = self._read_disk(day)
                self._fetched_mono = 0.
                self._last_error = None
                self._refreshing = False
                self._retry_after = 0.
            age = _elapsed(self._snapshot.get("fetched_at")) if self._snapshot else None
            fresh = (age is not None and age < self._ttl and self._last_error is None)
            if fresh:
                return self._present()
            if not self._refreshing and time.monotonic() >= self._retry_after:
                self._refreshing = True
                if self._snapshot:
                    threading.Thread(target=self._refresh, args=(day, fetcher),
                                     daemon=True, name="betsightly-live-score-refresh").start()
                else:
                    synchronous = True
            if not synchronous:
                return self._present()
        # Cold start: return the initial snapshot instead of an empty scoreboard
        # whenever a source succeeds; the next requests are stale-safe.
        self._refresh(day, fetcher)
        with self._lock:
            return self._present()
