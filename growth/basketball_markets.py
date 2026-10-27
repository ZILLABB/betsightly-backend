"""Strictly gated additional full-game basketball markets.

These IDs were identified from third-party market mappings, not guaranteed by
SportyBet's undocumented web feed. Keep DISABLED until exact live market labels,
outcome sides and share-code readback are independently confirmed. Unsupported
period/player markets must never be silently substituted.
"""
from __future__ import annotations
import os
import re


def enabled():
    return os.getenv("BASKETBALL_EXTENDED_MARKETS_ENABLED", "false").lower() in ("1", "true", "yes")


def market_ids():
    return ("219", "225", "223", "227", "228") if enabled() else ("219", "225")


def _side_from_description(desc, home, away):
    value = re.sub(r"[^a-z0-9]", "", str(desc or "").lower())
    home_norm = re.sub(r"[^a-z0-9]", "", home.lower())
    away_norm = re.sub(r"[^a-z0-9]", "", away.lower())
    if value in ("1", "home", home_norm):
        return "home"
    if value in ("2", "away", away_norm):
        return "away"
    return None


def parse_extended(raw: dict, home: str, away: str):
    """Accept only exact, labelled bookmaker selections with settlement rules."""
    if not enabled():
        return None
    mid = str(raw.get("id") or "")
    spec = str(raw.get("specifier") or "")
    if mid == "223":
        if not re.fullmatch(r"hcp=[+-]?\d{1,3}(?:\.5|\.0)?", spec):
            return None
        marketside = None
        desc = str(raw.get("desc") or "").lower()
        if "handicap" not in desc and "spread" not in desc:
            return None
        marketname = "Full game spread incl. OT"
        line = float(spec[4:])
        if abs(line) > 80:
            return None
    elif mid in ("227", "228"):
        if not re.fullmatch(r"total=\d{1,3}(?:\.5|\.0)?", spec):
            return None
        value = float(spec[6:])
        if not 0 < value < 300:
            return None
        marketside = "home" if mid == "227" else "away"
        desc = str(raw.get("desc") or "").lower()
        team = home if marketside == "home" else away
        if ("total" not in desc or not (
            ("home" in desc and marketside == "home") or
            ("away" in desc and marketside == "away") or
            re.sub(r"[^a-z0-9]", "", team.lower()) in
            re.sub(r"[^a-z0-9]", "", desc)
        )):
            return None
        marketname = ("Home" if marketside == "home" else "Away") + " team points incl. OT"
    else:
        return None

    outcomes = []
    seen_sides = set()
    for outcome in raw.get("outcomes") or []:
        side = None
        oid = str(outcome.get("id") or "")
        desc = str(outcome.get("desc") or "")
        if mid == "223":
            side = _side_from_description(desc, home, away)
            if side is None or side in seen_sides:
                return None
            label = (home if side == "home" else away) + " handicap " + ("%+g" % line)
        else:
            if oid not in ("12", "13"):
                continue
            side = marketside
            direction = "Over" if oid == "12" else "Under"
            if desc.strip().lower() != direction.lower():
                return None
            label = ("Home" if side == "home" else "Away") + " " + direction + " " + spec[6:]
        try:
            price = float(outcome.get("odds"))
        except (ValueError, TypeError):
            continue
        from math import isfinite
        if not isfinite(price) or not 1 < price < 1001 or outcome.get("isActive", True) in (False, 0, "false"):
            continue
        if (mid == "223" and side in seen_sides) or (mid != "223" and oid in seen_sides):
            return None
        seen_sides.add(side if mid == "223" else oid)
        outcomes.append({"outcome_id": oid, "label": label, "odds": round(price, 3), "side": side})
    if mid == "223" and set(x["side"] for x in outcomes) != {"home", "away"}:
        return None
    if not outcomes:
        return None
    return {"market_id": mid, "specifier": spec, "label": marketname, "outcomes": outcomes}
