"""Fail-closed rollover progression. Pure policy for publishing and display.

A three-day rollover is one challenge, not three unrelated daily slips.
Never proceed to day N+1 until all earlier days are settled as won.
Never erase already-published fixtures or rewrite their settlement history.
"""
from __future__ import annotations


def chain_state(days: list[dict], today: str, target_days: int = 3) -> dict:
    """Decide whether today's single stage may be published.

    No look-ahead: generating dates after today is forbidden. A previously
    precommitted day is active only if all earlier days actually won.
    Failed/voided chains are terminal; start a new chain strictly after
    every previously published day, avoiding conflicting same-day tickets.
    """
    ordered = sorted(days, key=lambda d: (int(d.get("day_number") or 0),
                                          str(d.get("date") or "")))
    latest_date = max((str(d.get("date") or "") for d in ordered), default="")
    has_loss = any(d.get("status") == "lost" for d in ordered)
    has_void = any(d.get("status") == "void" for d in ordered)
    complete = (len(ordered) >= target_days and
                all(d.get("status") == "won" for d in ordered))
    terminal = ("failed" if has_loss else "voided" if has_void
                else "completed" if complete else "")
    if terminal:
        restart = bool(today > latest_date)
        return {
            "status": terminal,
            "can_generate": restart,
            "new_chain": restart,
            "day_number": 1 if restart else None,
            "active_date": None,
        }

    for idx, day in enumerate(ordered):
        if day.get("date") != today or day.get("status") != "pending":
            continue
        if all(prior.get("status") == "won" for prior in ordered[:idx]):
            return {"status": "active", "can_generate": False,
                    "new_chain": False, "day_number": idx + 1,
                    "active_date": today}
        return {"status": "awaiting_previous_win", "can_generate": False,
                "new_chain": False, "day_number": None, "active_date": None}

    if any(d.get("status") == "pending" for d in ordered):
        return {"status": "awaiting_settlement", "can_generate": False,
                "new_chain": False, "day_number": None, "active_date": None}

    if any(str(d.get("date") or "") >= today for d in ordered):
        return {"status": "awaiting_next_day", "can_generate": False,
                "new_chain": False, "day_number": None, "active_date": None}

    if ordered and not all(d.get("status") == "won" for d in ordered):
        return {"status": "awaiting_result", "can_generate": False,
                "new_chain": False, "day_number": None, "active_date": None}

    return {
        "status": "ready",
        "can_generate": True,
        "new_chain": not ordered,
        "day_number": len(ordered) + 1,
        "active_date": None,
    }


def allow_append_day(prior_days: list[dict], new_day: dict,
                     chain_start_date: str) -> bool:
    """Persistence boundary: never insert future stage after non-wins.

    Even if a caller bypasses the presentation policy, the database write
    must require a contiguous won history and strictly increasing dates.
    Existing archived rows are never rewritten by this guard.
    """
    try:
        number = int(new_day["day_number"])
        date = str(new_day["date"])
        if number not in (1, 2, 3) or len(date) != 10:
            return False
        if number == 1:
            return not prior_days and date >= chain_start_date
        if len(prior_days) != number - 1:
            return False
        ordered = sorted(prior_days, key=lambda d: int(d["day_number"]))
        return all(
            int(day["day_number"]) == idx
            and day["status"] == "won"
            and str(day["date"]) < date
            for idx, day in enumerate(ordered, start=1)
        ) and len({day["date"] for day in ordered}) == len(ordered)
    except (KeyError, TypeError, ValueError):
        return False
