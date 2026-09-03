"""Shared semantics for rates shown in the admin dashboard."""

from __future__ import annotations


def conversion(numerator: int, denominator: int, *, minimum: int = 20,
               low_sample: int = 50) -> dict:
    numerator = max(0, min(int(numerator or 0), int(denominator or 0)))
    denominator = max(0, int(denominator or 0))
    if denominator < minimum:
        status, rate = "insufficient", None
    else:
        status = "low" if denominator < low_sample else "normal"
        rate = round(numerator / denominator, 4)
    return {"numerator": numerator, "denominator": denominator,
            "rate": rate, "sample_status": status}


def retention(numerator: int, denominator: int) -> dict:
    return conversion(numerator, denominator, minimum=30, low_sample=100)


def source_meta(source: str, as_of: str | None, status: str = "fresh",
                freshness_seconds: int | None = None) -> dict:
    return {"source": source, "as_of": as_of, "status": status,
            "freshness_seconds": freshness_seconds}
