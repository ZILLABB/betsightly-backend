"""Official Rollover daily odds contract (not a profitability guarantee).

A new rollover stage must have genuine bookmaker odds between 2.00x and
4.00x inclusive. A published code is displayed only when its validated
SportyBet price also satisfies the range.
"""
import math

ROLLOVER_MIN_ODDS = 2.0
ROLLOVER_MAX_ODDS = 4.0


def rollover_odds_in_range(odds) -> bool:
    try:
        price = float(odds)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(price) and ROLLOVER_MIN_ODDS <= price <= ROLLOVER_MAX_ODDS
