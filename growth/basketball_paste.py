"""Strict, admin-only text input for existing basketball bookmaker verification."""
import re
import time

from growth import basketball_jackpot as bj
from leagues import sportybet

_PAIR = re.compile(r"^\s*(?:\d{1,2}[\.\)]\s*)?(.+?)\s+[vV](?:s\.?)?\s+(.+?)\s*\|\s*(.+?)\s*$")
_TOTAL = re.compile(r"^(over|under)\s*(\d+(?:\.\d+)?)\s*(?:points?|pts?)?$", re.I)
_ODDS = re.compile(r"\s*@\s*\d+(?:\.\d+)?\s*$")


def _id(name):
    return re.sub(r"[^a-z0-9]", "", sportybet._norm(name).lower())


def _parse(text):
    if not isinstance(text, str) or len(text) > 9000:
        raise ValueError("Paste no more than 9,000 characters.")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not 1 <= len(lines) <= 50:
        raise ValueError("Paste 1 to 50 basketball picks, one per line.")
    result = []
    for i, line in enumerate(lines, 1):
        match = _PAIR.fullmatch(line)
        if not match:
            result.append({"line": i, "reason": "INVALID_FORMAT"})
            continue
        home, away, label = (p.strip() for p in match.groups())
        name = _ODDS.sub("", label).strip().lower()
        points = _TOTAL.fullmatch(name)
        if points:
            mid, oid = "225", "12" if points.group(1).lower() == "over" else "13"
            spec = "total=" + ("%g" % float(points.group(2)))
        elif name in {"home", "home win", "home ml", "home moneyline", "1", home.lower(), home.lower()+" win"}:
            mid, oid, spec = "219", "4", ""
        elif name in {"away", "away win", "away ml", "away moneyline", "2", away.lower(), away.lower()+" win"}:
            mid, oid, spec = "219", "5", ""
        else:
            result.append({"line": i, "reason": "UNSUPPORTED_MARKET"})
            continue
        if _id(home) == _id(away):
            result.append({"line": i, "reason": "INVALID_FIXTURE"})
            continue
        result.append({"line": i, "home": home, "away": away,
                       "market_id": mid, "outcome_id": oid, "specifier": spec})
    return result


def resolve(request, board):
    rows = _parse(request.get("fixtures_text", ""))
    index = {}
    for fixture in board["fixtures"]:
        index.setdefault((_id(fixture["home_team"]), _id(fixture["away_team"])), []).append(fixture)
    selected, errors, used = [], [], set()
    for row in rows:
        line = row["line"]
        if "reason" in row:
            errors.append({"line": line, "reason": row["reason"]})
            continue
        matches = index.get((_id(row["home"]), _id(row["away"])), [])
        available = [m for m in matches if m["kickoff_ms"] > (time.time()+bj.KICKOFF_BUFFER)*1000]
        if len(available) != 1:
            errors.append({"line": line, "reason": "FIXTURE_NOT_FOUND_OR_AMBIGUOUS"})
            continue
        event = available[0]
        if event["event_id"] in used:
            errors.append({"line": line, "reason": "DUPLICATE_FIXTURE"})
            continue
        used.add(event["event_id"])
        options = [o for market in event["markets"] if
                   (market["market_id"], market["specifier"]) == (row["market_id"], row["specifier"])
                   for o in market["outcomes"] if o["outcome_id"] == row["outcome_id"]]
        if len(options) != 1:
            errors.append({"line": line, "reason": "EXACT_MARKET_UNAVAILABLE"})
            continue
        selected.append({"event_id": event["event_id"], "market_id": row["market_id"],
                         "outcome_id": row["outcome_id"], "specifier": row["specifier"]})
    if errors:
        return {"status": "EXACT_MARKETS_UNAVAILABLE", "sport": "basketball",
                "matched_fixture_count": len(selected), "pasted_fixture_count": len(rows),
                "unmatched": errors, "matched": [], "full_ticket_complete": False,
                "share_code": None, "readback_status": "NOT_REQUESTED",
                "reason": "Resolve every rejected line. No markets were substituted."}, None
    verified = bj._select({**request, "selections": selected}, board)
    return verified, {**request, "selections": selected}


def preview(request):
    board = bj.cached_board()
    if not board:
        return {"status": "BOARD_REFRESH_REQUIRED", "matched_fixture_count": 0,
                "unmatched": [], "full_ticket_complete": False, "share_code": None,
                "reason": "Refresh the complete basketball bookmaker board first."}
    return resolve(request, board)[0]


def book(request):
    board = bj.cached_board()
    if not board:
        return {"status": "BOARD_REFRESH_REQUIRED", "share_code": None}
    report, resolved = resolve(request, board)
    if report["status"] != "PROPOSED_NOT_BOOKED" or not resolved:
        return report
    return bj.book(resolved)
