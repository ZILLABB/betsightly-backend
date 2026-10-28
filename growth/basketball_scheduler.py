"""Periodic, fail-closed reconciliation of saved basketball bookmaker codes.

Runs inside BetSightly's existing *scheduler-owned* 15-minute tick. Never
requests a new booking code, opens a bet, changes a model, or touches
research-only forecasts. Per-leg settling is governed by verified NBA/European final-score evidence.
"""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)


def tick(*, settle=None, recorder=None) -> dict:
    production_tick = settle is None
    if recorder is None and production_tick:
        from growth.basketball_result_checks import record
        recorder = record

    def finish(outcome):
        if recorder is not None:
            try:
                recorder(outcome)
            except Exception as exc:
                logger.warning("Basketball result audit unavailable: %s",
                               type(exc).__name__)
        return outcome

    if settle is None:
        from growth.basketball_settlement import settle_due
        settle = settle_due
    try:
        result = settle()
    except Exception as exc:
        logger.warning("Private basketball final score check failed closed: %s",
                       type(exc).__name__)
        return finish({"status": "unavailable", "reason": type(exc).__name__})
    if not isinstance(result, dict):
        return finish({"status": "unavailable", "reason": "invalid_receipt"})
    if result.get("status") != "success":
        logger.warning("Basketball settlement provider incomplete: %s",
                       str(result.get("status", "unknown"))[:80])
        return finish({"status": "unavailable", "reason": str(result.get("status"))[:80]})
    count = result.get("verified_final_legs", result.get("nba_final_legs", 0))
    changed = result.get("tickets_updated", 0)
    if type(count) is not int or type(changed) is not int or count < 0 or changed < 0:
        return finish({"status": "unavailable", "reason": "invalid_counts"})
    if changed:
        logger.info("Verified basketball booking settlement: %d tickets; %d legs",
                    changed, count)
    return finish({"status": "success", "verified_final_legs": count,
                   "nba_final_legs": result.get("nba_final_legs", count),
                   "tickets_updated": changed})
