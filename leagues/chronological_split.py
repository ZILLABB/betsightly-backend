"""Chronological train/calibration/test split helpers.

The contract is intentionally calendar-date aware: a single UTC calendar date
must belong to exactly one split. This prevents fixtures from the same date
appearing on opposite sides of a train/calibration or calibration/test boundary.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Any


def _calendar_key(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    date_method = getattr(value, "date", None)
    if callable(date_method):
        result = date_method()
        if hasattr(result, "isoformat"):
            return result.isoformat()

    text = str(value)
    if len(text) < 10:
        raise ValueError(f"Cannot derive calendar date from {value!r}")
    return text[:10]


def whole_date_boundaries(
    dates: Iterable[Any],
    *,
    train_frac: float = 0.70,
    calib_frac: float = 0.15,
) -> tuple[int, int]:
    """Return exclusive train/calibration boundaries aligned to whole dates."""
    values = list(dates)
    n = len(values)
    if n < 3:
        raise ValueError("Need at least three samples for train/calibration/test")
    if not (0.0 < train_frac < 1.0):
        raise ValueError("train_frac must be between 0 and 1")
    if not (0.0 < calib_frac < 1.0):
        raise ValueError("calib_frac must be between 0 and 1")
    if train_frac + calib_frac >= 1.0:
        raise ValueError("train_frac + calib_frac must leave a non-empty test share")

    keys = [_calendar_key(value) for value in values]
    if any(keys[i] < keys[i - 1] for i in range(1, n)):
        raise ValueError("Dates must be sorted chronologically")

    boundaries = [i for i in range(1, n) if keys[i] != keys[i - 1]]
    if len(boundaries) < 2:
        raise ValueError("Need at least three distinct calendar dates")

    train_target = max(1, int(n * train_frac))
    calib_target = max(train_target + 1, int(n * (train_frac + calib_frac)))

    train_candidates = boundaries[:-1]
    i_tr = next(
        (boundary for boundary in train_candidates if boundary >= train_target),
        train_candidates[-1],
    )

    calib_candidates = [boundary for boundary in boundaries if boundary > i_tr]
    if not calib_candidates:
        raise ValueError("No calendar-date boundary remains for calibration/test")
    i_ca = next(
        (boundary for boundary in calib_candidates if boundary >= calib_target),
        calib_candidates[-1],
    )

    if not (0 < i_tr < i_ca < n):
        raise ValueError(
            f"Invalid whole-date split boundaries: train={i_tr}, calib={i_ca}, n={n}"
        )
    return i_tr, i_ca


def describe_whole_date_split(
    dates: Iterable[Any],
    *,
    train_frac: float = 0.70,
    calib_frac: float = 0.15,
) -> dict:
    values = list(dates)
    i_tr, i_ca = whole_date_boundaries(
        values,
        train_frac=train_frac,
        calib_frac=calib_frac,
    )
    keys = [_calendar_key(value) for value in values]
    n = len(values)

    return {
        "strategy": "whole_calendar_date",
        "derived_samples": n,
        "train": i_tr,
        "calib": i_ca - i_tr,
        "test": n - i_ca,
        "train_end_index": i_tr,
        "calib_end_index": i_ca,
        "train_start": keys[0],
        "train_end": keys[i_tr - 1],
        "calib_start": keys[i_tr],
        "calib_end": keys[i_ca - 1],
        "test_start": keys[i_ca],
        "test_end": keys[-1],
        "train_calib_same_date_boundary": keys[i_tr - 1] == keys[i_tr],
        "calib_test_same_date_boundary": keys[i_ca - 1] == keys[i_ca],
    }
