"""Typed, line-exact bookmaker quote helpers.

Probabilities from one totals line are evidence for that exact line only.  A
3.5 quote may help infer expected goals, but it is never labelled as the
bookmaker probability for Over/Under 2.5.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any


DEFAULT_MAX_AGE_SECONDS = 60 * 60


def _as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def _captured_at(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def total_quote(
    odds: dict | None,
    line: float,
    *,
    now: datetime | None = None,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
) -> dict:
    """Return a validated full-game totals quote for ``line``.

    The status is explicit so callers cannot accidentally treat a missing,
    malformed, stale, wrong-period, or different-line quote as exact market
    evidence.
    """
    odds = odds or {}
    requested = float(line)
    quotes = odds.get("total_quotes")
    if not isinstance(quotes, list):
        quotes = []
    candidates = [quote for quote in quotes if isinstance(quote, dict)]

    # Backward-compatible read of an in-memory legacy quote.  It remains
    # line-exact, but its unknown capture time is exposed rather than hidden.
    if not candidates and odds.get("ou_line") is not None:
        candidates = [{
            "market": "total_goals",
            "period": "full_game",
            "line": odds.get("ou_line"),
            "over_odds": odds.get(f"over_{str(requested).replace('.', '_')}"),
            "under_odds": odds.get(f"under_{str(requested).replace('.', '_')}"),
            "implied_over": odds.get("implied_over"),
            "implied_under": odds.get("implied_under"),
            "captured_at": odds.get("captured_at"),
            "source": odds.get("provider"),
        }]

    exact = None
    saw_wrong_market = False
    saw_wrong_period = False
    for quote in candidates:
        quote_line = _as_float(quote.get("line"))
        if quote_line is None or abs(quote_line - requested) > 1e-9:
            continue
        # Do not use corners/cards or another market's line as goal evidence.
        # Legacy quotes are explicitly tagged total_goals above.
        if quote.get("market") != "total_goals":
            saw_wrong_market = True
            continue
        if quote.get("period") != "full_game":
            saw_wrong_period = True
            continue
        exact = quote
        break

    if exact is None:
        status = "WRONG_PERIOD" if saw_wrong_period else (
            "WRONG_MARKET" if saw_wrong_market else "MISSING"
        )
        return {"status": status, "line": requested}

    over = _as_float(exact.get("implied_over"))
    under = _as_float(exact.get("implied_under"))
    if over is None or under is None or over >= 1 or under >= 1:
        return {"status": "MALFORMED", "line": requested}

    captured = _captured_at(exact.get("captured_at"))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if exact.get("captured_at") and captured is None:
        return {"status": "MALFORMED", "line": requested}
    if captured is not None:
        age = (current.astimezone(timezone.utc) - captured).total_seconds()
        if age < -60:
            return {
                "status": "FUTURE", "line": requested,
                "captured_at": captured.isoformat(), "source": exact.get("source"),
            }
        if age > max_age_seconds:
            return {
                "status": "STALE", "line": requested,
                "captured_at": captured.isoformat(), "source": exact.get("source"),
            }

    return {
        "status": "EXACT",
        "market": "total_goals",
        "period": "full_game",
        "line": requested,
        "over_odds": _as_float(exact.get("over_odds")),
        "under_odds": _as_float(exact.get("under_odds")),
        "implied_over": over,
        "implied_under": under,
        "captured_at": captured.isoformat() if captured else None,
        "freshness": "fresh" if captured else "unknown",
        "source": exact.get("source"),
    }


def exact_total_probability(odds: dict | None, line: float, side: str) -> float | None:
    quote = total_quote(odds, line)
    if quote.get("status") != "EXACT":
        return None
    return float(quote[f"implied_{side}"])
