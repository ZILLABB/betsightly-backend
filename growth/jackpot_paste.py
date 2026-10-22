"""Admin-only paste of fixture names, validated against approved BetSightly picks.

Text is untrusted input. Neither market names nor odds pasted by a user are
assumed bookable. The candidate board still enforces current model evidence,
kickoff validity, bookmaker mapping and readback at booking time.
"""
from __future__ import annotations

import re
import unicodedata
from math import isfinite, prod
from difflib import SequenceMatcher

MAX_LINES = 80
MAX_TEXT_LENGTH = 9000
_VS = re.compile(r"\s+(?:vs\.?|v\.?)\s+", re.I)
_PREFIX = re.compile(r"^\s*(?:\d+[.)-]\s*|[-*•]\s*)")
_STOP = {"fc", "afc", "sc", "sk", "nk", "gnk", "fk", "cf", "club", "the"}
_MARKETS = {
    "1": "home_win", "home": "home_win", "home win": "home_win",
    "2": "away_win", "away": "away_win", "away win": "away_win",
    "x": "draw", "draw": "draw",
    "btts yes": "btts_yes", "gg yes": "btts_yes",
    "both teams to score yes": "btts_yes",
    "over 1.5": "over_1_5", "over 2.5": "over_2_5",
    "over 3.5": "over_3_5", "1x": "home_or_draw",
    "home or draw": "home_or_draw", "x2": "away_or_draw",
    "away or draw": "away_or_draw",
    "dnb home": "dnb_home", "dnb away": "dnb_away",
}
_PRICE = re.compile(r"\\s*@\\s*\\d+(?:\\.\\d+)?\\s*$")


def _team(value: str) -> str:
    raw = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    raw = raw.replace("&", "and")
    pieces = re.findall(r"[a-z0-9]+", raw)
    while pieces and pieces[0] in _STOP:
        pieces.pop(0)
    while pieces and pieces[-1] in _STOP:
        pieces.pop()
    return " ".join(pieces)


def parse_fixture_lines(value: str) -> list[dict]:
    if len(value) > MAX_TEXT_LENGTH:
        raise ValueError("Maximum pasted text length is 9,000 characters.")
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines or len(lines) > MAX_LINES:
        raise ValueError("Paste 1 to 80 matches, one 'Home vs Away' per line.")
    parsed = []
    seen = set()
    for index, line in enumerate(lines, 1):
        cleaned = _PREFIX.sub("", line).strip()
        sides = cleaned.split("|")
        if len(sides) > 2:
            raise ValueError(f"Line {index}: use at most one '|' separator.")
        fixture_text = sides[0].strip()
        requested_market = None
        if len(sides) == 2:
            market_label = _PRICE.sub("", sides[1]).lower().strip()
            market_label = " ".join(market_label.split())
            requested_market = _MARKETS.get(market_label)
            if not requested_market:
                raise ValueError(
                    f"Line {index}: unknown pick '{market_label}'. "
                    "Use Home win, Away win, BTTS Yes, Draw, Over 1.5, "
                    "Over 2.5, Over 3.5, 1X, X2, DNB Home or DNB Away."
                )
        parts = _VS.split(fixture_text)
        if len(parts) != 2 or not all(2 <= len(p.strip()) <= 90 for p in parts):
            raise ValueError(f"Line {index}: expected 'Home vs Away' (no odds required).")
        home, away = (p.strip() for p in parts)
        identity = (_team(home), _team(away))
        if not all(identity) or identity[0] == identity[1]:
            raise ValueError(f"Line {index}: invalid fixture identity.")
        if identity in seen:
            raise ValueError(f"Line {index}: duplicate fixture.")
        seen.add(identity)
        parsed.append({"line": index, "home_team": home, "away_team": away,
                       "requested_market": requested_market})
    return parsed


def _match_score(left: str, right: str) -> float:
    a, b = _team(left), _team(right)
    if a == b:
        return 1.0
    # Names are not automatically corrected unless BOTH club names match
    # closely. Suggestions below never become accepted booking selections.
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def match_fixture_lines(lines: list[dict], candidates: list[dict]) -> dict:
    by_fixture: dict[str, dict] = {}
    for row in candidates:
        fid = str(row.get("match_id") or "")
        if fid and fid not in by_fixture:
            by_fixture[fid] = row
    matched, unmatched, used = [], [], set()
    for line in lines:
        rated = []
        for fid, row in by_fixture.items():
            home = _match_score(line["home_team"], str(row.get("home_team") or ""))
            away = _match_score(line["away_team"], str(row.get("away_team") or ""))
            rated.append((min(home, away), (home + away) / 2, fid, row))
        rated.sort(key=lambda item: (-item[0], -item[1], item[2]))
        first = rated[0] if rated else None
        second = rated[1] if len(rated) > 1 else None
        exact = first and first[0] == 1.0
        # A fuzzy match must have two very similar team names and a clear
        # margin over the runner-up. Otherwise report uncertainty to admin.
        safe = first and (exact or (
            first[0] >= .92 and first[1] >= .95 and
            (not second or first[1] - second[1] >= .08)
        ))
        if not safe or first[2] in used:
            unmatched.append({
                **line,
                "reason": ("AMBIGUOUS_OR_DUPLICATE" if safe and first[2] in used
                           else "NOT_APPROVED_ON_CURRENT_BOARD"),
                "suggested_match": (
                    f"{first[3].get('home_team')} vs {first[3].get('away_team')}"
                    if first and first[0] >= .7 else None
                ),
            })
            continue
        used.add(first[2])
        matched.append({
            **line, "match_id": first[2],
            "matched_home": first[3].get("home_team"),
            "matched_away": first[3].get("away_team"),
            "match_method": "exact" if exact else "strict_name_similarity",
        })
    return {"matched": matched, "unmatched": unmatched}


def pasted_preview(payload: dict) -> dict:
    from growth.private_jackpot import candidate_board
    from growth.jackpot_optimizer import optimize
    items = parse_fixture_lines(str(payload.get("fixtures_text") or ""))
    board = candidate_board(payload)
    if board.get("status") != "success":
        return {**board, "matched": [], "unmatched": [], "share_code": None}
    result = match_fixture_lines(items, board.get("candidates") or [])
    fixture_ids = {row["match_id"] for row in result["matched"]}
    qualifying = [row for row in board["candidates"] if row.get("match_id") in fixture_ids]
    target = float(payload.get("target_odds") or 100000)
    max_legs = int(payload.get("max_legs") or 50)
    choices = {row["selection_id"]: row for row in qualifying}
    explicit_count = sum(bool(row["requested_market"]) for row in items)
    if explicit_count and explicit_count != len(items):
        raise ValueError(
            "Every pasted line needs a market after |, or none should. "
            "Mixing exact selections with automatic markets is not supported."
        )
    if explicit_count:
        picked = []
        not_available = []
        markets_by_fixture = {
            (str(row["match_id"]), str(row["market"])): row for row in qualifying
        }
        for matched in result["matched"]:
            choice = markets_by_fixture.get(
                (matched["match_id"], matched["requested_market"])
            )
            if choice is None:
                not_available.append({
                    **matched, "reason": "REQUESTED_MARKET_NOT_APPROVED",
                    "suggested_match": None,
                })
            else:
                picked.append(choice)
        result["unmatched"].extend(not_available)
        # No auto-swapping markets or dropping a pick to reach target.
        result["matched"] = [
            row for row in result["matched"]
            if all(row["line"] != bad["line"] for bad in not_available)
        ]
        total = prod(float(row["odds"]) for row in picked)
        available = not result["unmatched"] and len(picked) == len(items)
        within_limit = len(picked) <= max_legs
        proposal = {
            "status": (
                "UNMATCHED_FIXTURES" if not available else
                "TOO_MANY_LEGS" if not within_limit else
                "BELOW_TARGET" if total < target else
                "PROPOSED_NOT_BOOKED"
            ),
            "reason": (
                f"{len(result['unmatched'])} exact fixtures/markets are "
                "unavailable or unapproved. No substitutions or code requested."
                if not available else
                f"Exact selections require {len(picked)} legs; max_legs is {max_legs}."
                if not within_limit else
                f"Exact approved selections total {total:,.2f}x, below {target:,.2f}x."
                if total < target else
                "Exact pasted picks retained; confirmation still requires full "
                "SportyBet readback of all selections at or above the odds target."
            ),
            "selection_ids": ([str(row["selection_id"]) for row in picked]
                              if available and within_limit else []),
            "legs": len(picked),
            "indicative_odds": round(total, 3),
            "maximum_reference_odds": round(total, 3),
            "maximum_model_eligible_reference_odds": round(total, 3),
            "portfolio_type": "USER_SUPPLIED_EXACT_MARKETS",
            "optimization_method": "exact_pasted_market_match",
            "booking_code_created": False,
        }
    else:
        proposal = optimize(qualifying, target, max_legs)
    return {
        **proposal,
        "matched": result["matched"],
        "unmatched": result["unmatched"],
        "pasted_fixture_count": len(items),
        "matched_fixture_count": len(result["matched"]),
        "unmatched_fixture_count": len(result["unmatched"]),
        "candidate_count": len(qualifying),
        "selected_games": [choices[s] for s in proposal.get("selection_ids") or [] if s in choices],
        "source": ("PASTED_EXACT_MARKETS" if explicit_count else
                   "PASTED_NAMES_MATCHED_TO_APPROVED_BOARD"),
        "exact_market_mode": bool(explicit_count),
        "requested_market_count": explicit_count,
        "bookmaker_code_created": False,
        "share_code": None,
        "note": (
            "Exact pasted markets are never swapped. Pasting cannot add "
            "unscored fixtures or invent bookmaker prices; missing or "
            "unapproved matches remain unavailable."
        ),
    }


def pasted_auto_book(payload: dict) -> dict:
    """Explicitly administrator-confirmed. Reject any dropped pasted fixtures."""
    preview = pasted_preview(payload)
    if preview.get("status") != "PROPOSED_NOT_BOOKED":
        return {**preview, "share_code": None}
    if preview["unmatched_fixture_count"]:
        return {
            **preview,
            "status": "UNMATCHED_FIXTURES",
            "reason": (
                f"{preview['unmatched_fixture_count']} pasted matches are not on "
                "the approved/bookable board. No fixture is silently dropped "
                "from your submitted list and no code was requested."
            ),
            "share_code": None,
        }
    from growth.private_jackpot import booking_request
    result = booking_request({
        **payload, "selection_ids": preview["selection_ids"],
    })
    if result.get("status") != "success":
        return {
            **result,
            "pasted_preview": preview,
            "share_code": None,
        }
    return {
        **result,
        "pasted_preview": preview,
        "source": "PASTED_NAMES_MATCHED_TO_APPROVED_BOARD",
    }
