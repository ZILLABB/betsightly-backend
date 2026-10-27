"""Periodic, fail-closed reconciliation of saved NBA basketball bookmaker codes.

Runs inside BetSightly's existing *scheduler-owned* 15-minute tick. Never
requests a new booking code, opens a bet, changes a model, or touches
research-only forecasts. Per-leg settling is governed by verified ESPN finals.
"""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)


def tick(*, settle=None) -> dict:
    if settle is None:
        from growth.basketball_settlement import settle_due
        settle = settle_due
    try:
        result = settle()
    except Exception as exc:
        logger.warning("Private basketball final score check failed closed: %s",
                       type(exc).__name__)
        return {"status": "unavailable", "reason": type(exc).__name__}
    if not isinstance(result, dict):
        return {"status": "unavailable", "reason": "invalid_receipt"}
    if result.get("status") != "success":
        logger.warning("Basketball settlement provider incomplete: %s",
                       str(result.get("status", "unknown"))[:80])
        return {"status": "unavailable", "reason": str(result.get("status"))[:80]}
    count = result.get("nba_final_legs", 0)
    changed = result.get("tickets_updated", 0)
    if type(count) is not int or type(changed) is not int or count < 0 or changed < 0:
        return {"status": "unavailable", "reason": "invalid_counts"}
    if changed:
        logger.info("Verified NBA booking settlement: %d tickets; %d legs",
                    changed, count)
    return {"status": "success", "nba_final_legs": count,
            "tickets_updated": changed}
