"""Staging-only, read-only NBA SportyBet market observations.

Captures exact full-game total-point lines/decimal odds, not wagers. Matches
only exact known NBA identities plus bounded UTC tipoff time. Unmatched events
and incomplete provider crawls fail closed. No edge or bookmaker ROI inferred.
"""
from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from basketball.research_coldstart import _json, _now
from basketball.research_nba_cdn import NBA_TEAM_CODES
from basketball.research_scoreboard import _utc

SPORT_ID = "sr:sport:2"
MARKETS = ("219", "225")
MAX_PAGES = 10
PAGE_SIZE = 100
TIPOFF_WINDOW = timedelta(minutes=30)
BEFORE_TIPOFF = timedelta(minutes=10)
EXACT_TEAM_NAMES = {
    **{name.casefold(): name for name in NBA_TEAM_CODES},
    "los angeles clippers": "LA Clippers",
}
BASE_PATH = "/api/ng/factsCenter/pcUpcomingEvents"


def _active(value):
    return value not in (False, 0, "0", "false", "False")


def _canonical(name):
    if not isinstance(name, str):
        return None
    return EXACT_TEAM_NAMES.get(" ".join(name.split()).casefold())


def _event(raw, *, competition):
    if not isinstance(raw, dict):
        raise ValueError("NBA_EVENT_NOT_OBJECT")
    home, away = _canonical(raw.get("homeTeamName")), _canonical(raw.get("awayTeamName"))
    if home is None or away is None or home == away:
        return None
    ident = str(raw.get("eventId") or "")
    if not re.fullmatch(r"sr:match:[0-9]+", ident):
        raise ValueError("NBA_EVENT_ID_INVALID")
    try:
        start = datetime.fromtimestamp(
            int(raw["estimateStartTime"]) / 1000, tz=timezone.utc
        )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("NBA_EVENT_TIPOFF_INVALID") from exc
    markets = []
    for market in raw.get("markets") or []:
        if not isinstance(market, dict):
            raise ValueError("NBA_MARKET_MALFORMED")
        mid = str(market.get("id") or "")
        spec = str(market.get("specifier") or "")
        if mid not in MARKETS or not _active(market.get("isActive", True)):
            continue
        if str(market.get("status") or "").upper() in {"SUSPENDED", "CLOSED", "INACTIVE"}:
            continue
        if mid == "219" and spec:
            continue
        if mid == "225" and not re.fullmatch(r"total=\d+(?:\.\d+)?", spec):
            continue
        outcomes = {}
        for item in market.get("outcomes") or []:
            outcome_id = str(item.get("id") or "")
            if (mid, outcome_id) not in {
                ("219", "4"), ("219", "5"),
                ("225", "12"), ("225", "13"),
            } or not _active(item.get("isActive", True)):
                continue
            try:
                odds = float(item.get("odds"))
            except (ValueError, TypeError):
                continue
            if not 1.0 < odds <= 1000 or not math.isfinite(odds):
                continue
            outcomes[outcome_id] = odds
        required = ("4", "5") if mid == "219" else ("12", "13")
        if not all(key in outcomes for key in required):
            continue
        value = {
            "market_id": mid, "specifier": spec,
            "prices": {key: outcomes[key] for key in required},
        }
        if mid == "225":
            line = float(spec.split("=", 1)[1])
            if not 100 <= line <= 400:
                continue
            value["line"] = line
        markets.append(value)
    return {
        "event_id": ident, "home": home, "away": away,
        "tipoff_utc": start.isoformat(), "competition": competition,
        "markets": markets,
    }


def match_board(fixtures, events, *, now=None):
    """Return exact matches only; reject multiple potential bookmaker events."""
    instant = _now(now)
    by_pair = {}
    for g in fixtures:
        if g.get("status") == "final" or g.get("postseason"):
            continue
        start = _utc(g.get("start_utc"))
        if start is None or start < instant + BEFORE_TIPOFF:
            continue
        identity = (_canonical(g.get("home_name")), _canonical(g.get("away_name")))
        if None in identity or identity[0] == identity[1]:
            continue
        by_pair.setdefault(identity, []).append(g)
    results = []
    claimed = set()
    for event in events:
        if not event or not event["markets"]:
            continue
        start = _utc(event["tipoff_utc"])
        candidates = [
            fixture for fixture in by_pair.get((event["home"], event["away"]), ())
            if abs((_utc(fixture["start_utc"]) - start)) <= TIPOFF_WINDOW
        ]
        if len(candidates) > 1:
            raise ValueError("NBA_MATCH_AMBIGUOUS")
        if not candidates:
            continue
        fixture = candidates[0]
        gid = str(fixture["game_id"])
        if gid in claimed:
            raise ValueError("NBA_BOOKMAKER_EVENT_DUPLICATE")
        claimed.add(gid)
        results.append({
            "game_id": gid, "event_id": event["event_id"],
            "home": event["home"], "away": event["away"],
            "kickoff_utc": fixture["start_utc"],
            "markets": event["markets"],
        })
    return sorted(results, key=lambda x: (x["kickoff_utc"], x["game_id"]))


def fetch_exact_nba_markets(fixtures, *, now=None, loader=None):
    """Bounded upstream crawl. Incomplete pages cannot produce market evidence."""
    from leagues import sportybet
    instant = _now(now)
    loader = loader or sportybet._get_json
    base_url = sportybet.BASE_URL
    if base_url != "https://www.sportybet.com":
        raise ValueError("NBA_BOOKMAKER_ORIGIN_NOT_APPROVED")
    count = None
    seen = set()
    events = []
    processed = 0
    pages = 0
    for page in range(1, MAX_PAGES + 1):
        url = (
            base_url + BASE_PATH + "?sportId=" + quote(SPORT_ID, safe="")
            + "&marketId=219%2C225&pageSize=" + str(PAGE_SIZE)
            + "&pageNum=" + str(page)
        )
        response = loader(url, timeout=20)
        if not isinstance(response, dict) or response.get("bizCode") not in (None, 10000):
            raise RuntimeError("NBA_BOOKMAKER_PROVIDER_REJECTED")
        data = response.get("data") or {}
        if count is None:
            count = int(data.get("totalNum") or 0)
            if count <= 0 or count > PAGE_SIZE * MAX_PAGES:
                raise ValueError("NBA_BOOKMAKER_PAGE_COUNT_INVALID")
        tournaments = data.get("tournaments") or []
        if not isinstance(tournaments, list):
            raise ValueError("NBA_BOOKMAKER_TOURNAMENTS_INVALID")
        pages = page
        for tour in tournaments:
            if not isinstance(tour, dict):
                raise ValueError("NBA_BOOKMAKER_TOURNAMENT_INVALID")
            competition = str(tour.get("name") or "")
            category = str(tour.get("categoryName") or "")
            excluded = re.search(
                r"esport|e-basketball|ebasketball|virtual|simulated|cyber",
                competition + " " + category, re.I,
            )
            for raw in tour.get("events") or []:
                processed += 1
                ident = str(raw.get("eventId") or "") if isinstance(raw, dict) else ""
                if not ident or ident in seen:
                    raise ValueError("NBA_BOOKMAKER_EVENT_IDENTITY_INVALID")
                seen.add(ident)
                if excluded:
                    continue
                event = _event(raw, competition=competition)
                if event:
                    events.append(event)
        if len(seen) >= count and page >= math.ceil(count / PAGE_SIZE):
            break
    if not count or len(seen) < count or pages < math.ceil(count / PAGE_SIZE):
        raise RuntimeError("NBA_BOOKMAKER_CRAWL_INCOMPLETE")
    matches = match_board(fixtures, events, now=instant)
    receipt = {
        "source": "sportybet_ng_basketball_read_only",
        "observed_at": instant.isoformat(),
        "provider_events": len(seen), "matched_fixtures": len(matches),
        "fixtures": matches,
        "research_only": True, "not_bookable": True,
        "prices_not_licensed_for_public_redistribution": True,
    }
    receipt["digest"] = hashlib.sha256(_json(receipt).encode("utf-8")).hexdigest()
    return receipt


def compare_to_archive(board, observation):
    """Projection-versus-quoted line. No probability or EV without calibration."""
    forecast = {str(g["game_id"]): g for g in board["games"]}
    comparisons = []
    for event in observation.get("fixtures", []):
        item = forecast.get(event["game_id"])
        if item is None:
            raise ValueError("MARKET_SNAPSHOT_WITHOUT_ARCHIVED_FORECAST")
        for market in event["markets"]:
            if market["market_id"] != "225":
                continue
            estimate = item.get("advanced_total")
            if estimate is None:
                estimate = item.get("projected_total")
            # The observed bookmaker line and model's directional forecast
            # can be graded only after a verified final. This is PAPER
            # agreement, not evidence a real wager was placed or won.
            direction = (
                "over" if estimate is not None and estimate > market["line"]
                else "under" if estimate is not None and estimate < market["line"]
                else None
            )
            ah = item.get("actual_home_score")
            aa = item.get("actual_away_score")
            final = (
                int(ah) + int(aa) if item.get("status") == "verified_settled"
                and isinstance(ah, int) and isinstance(aa, int)
                and not isinstance(ah, bool) and not isinstance(aa, bool)
                else None
            )
            grade = "pending"
            if final is not None and direction is not None:
                if final == market["line"]:
                    grade = "push"
                else:
                    actual_direction = (
                        "over" if final > market["line"] else "under"
                    )
                    grade = "correct" if actual_direction == direction else "incorrect"
            comparisons.append({
                "paper_direction": direction,
                "paper_grade": grade,
                "actual_total": final,
                "real_bet_settlement": None,
                "game_id": event["game_id"],
                "home": event["home"], "away": event["away"],
                "tipoff_utc": event["kickoff_utc"], "event_id": event["event_id"],
                "market_id": "225", "line": market["line"],
                "over_odds": market["prices"]["12"],
                "under_odds": market["prices"]["13"],
                "projected_total": estimate,
                "difference": (round(estimate - market["line"], 2)
                               if estimate is not None else None),
                "model_probability": None, "expected_value": None,
                "recommendation": "NO_SELECTION_UNCALIBRATED",
                "market_status": item["status"],
                "observed_at": observation["observed_at"],
            })
    graded = [x for x in comparisons if x["paper_grade"] in (
        "correct", "incorrect", "push"
    )]
    return {
        "paper_grade_summary": {
            "correct": sum(x["paper_grade"] == "correct" for x in graded),
            "incorrect": sum(x["paper_grade"] == "incorrect" for x in graded),
            "push": sum(x["paper_grade"] == "push" for x in graded),
            "real_bets_placed": 0,
        },
        "status": "private_market_comparison",
        "observed_at": observation["observed_at"],
        "fixture_matches": len(observation.get("fixtures", [])),
        "quoted_totals": comparisons[:120],
        "calibrated_betting_edge": False, "not_bookable": True,
        "public_publishing_enabled": False, "source": observation["source"],
        "digest": observation["digest"],
    }
