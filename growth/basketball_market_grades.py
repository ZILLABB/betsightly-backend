"""Deterministic full-game NBA grading for candidate team-total markets.

This does not enable bookmaker selections. Current booking still allows only
219 (winner) and 225 (full-game total). This module is a research acceptance
contract for exact previously identified home/away total lines, including OT.
"""
import re

TEAM_TOTAL = {"227": "home", "228": "away"}


def grade_team_total(leg: dict, *, home_points: int, away_points: int):
    kind = str(leg.get("market_id") or "")
    side = TEAM_TOTAL.get(kind)
    if side is None or leg.get("side") != side:
        return None
    direction = str(leg.get("outcome_id") or "")
    if direction not in {"12", "13"}:
        return None
    specifier = str(leg.get("specifier") or "")
    match = re.fullmatch(r"total=(\d{1,3}(?:\.0|\.5)?)", specifier)
    if not match or type(home_points) is not int or type(away_points) is not int:
        return None
    if not 0 <= home_points < 400 or not 0 <= away_points < 400:
        return None
    threshold = float(match.group(1))
    if not 0 < threshold < 300:
        return None
    actual = home_points if side == "home" else away_points
    if actual == threshold:
        return "void"
    is_over = actual > threshold
    return "won" if is_over == (direction == "12") else "lost"
