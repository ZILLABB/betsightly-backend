"""Fail-closed supervision for the split VPS worker roles.

The Docker process remains alive if a daemon thread dies; check named
background threads so a dead publication/settlement process is restarted.
This is *not* a freshness or success guarantee for a blocked live thread.
"""

from __future__ import annotations


def expected_thread_names(
    role: str,
    ownership: dict[str, bool],
    *,
    telegram_configured: bool,
) -> frozenset[str]:
    if role == "publication" and ownership.get("scheduler"):
        return frozenset({"daily-generation"})
    if role == "settlement" and ownership.get("settlement"):
        return frozenset({"results-checker"})
    if (
        role == "telegram"
        and ownership.get("telegram")
        and telegram_configured
    ):
        return frozenset({"telegram-bot"})
    return frozenset()


def missing_threads(
    expected: frozenset[str],
    live_names: set[str],
) -> frozenset[str]:
    return expected - live_names
