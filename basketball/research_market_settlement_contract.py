"""Research-only exact market resolution, never a betting slip or recommendation.

No bookmaker line is inferred. Only a complete final scoreboard plus explicit
market identity can be graded; quarters/halves/player props are blocked until
period-score, roster, DNP and bookmaker rules are verified independently.
"""
from __future__ import annotations
from math import isfinite

SUPPORTED = frozenset({"full_game_moneyline", "full_game_total",
                       "full_game_home_spread", "full_game_home_team_total",
                       "full_game_away_team_total"})
UNSUPPORTED = frozenset({"first_half_total", "second_half_total",
                         "first_quarter_total", "second_quarter_total",
                         "third_quarter_total", "fourth_quarter_total",
                         "player_points", "player_rebounds", "player_assists",
                         "player_threes"})
LEAGUE_PERIODS = {"nba": (4, 12), "wnba": (4, 10), "ncaa_men": (2, 20),
                  "ncaa_women": (4, 10), "euroleague": (4, 10),
                  "eurocup": (4, 10), "nbl_au": (4, 10)}


def grade_full_game(market: dict, final: dict) -> dict:
    """Exact event+competitor+side+line; returns research settlement only."""
    if not isinstance(market, dict) or not isinstance(final, dict):
        raise ValueError("NBA_MARKET_EVIDENCE_INVALID")
    kind, league = market.get("kind"), market.get("league")
    if kind not in SUPPORTED or league not in LEAGUE_PERIODS:
        raise ValueError("NBA_MARKET_UNSUPPORTED_OR_PERIOD_EVIDENCE_MISSING")
    if market.get("overtime_included") is not True:
        raise ValueError("NBA_MARKET_OVERTIME_RULE_UNVERIFIED")
    if (final.get("status") != "final" or
        str(market.get("event_id") or "") != str(final.get("event_id") or "")
        or not final.get("event_id") or
        str(market.get("home_id") or "") != str(final.get("home_id") or "")
        or str(market.get("away_id") or "") != str(final.get("away_id") or "")
        or not final.get("home_id") or not final.get("away_id") or
        final.get("home_id") == final.get("away_id")):
        raise ValueError("NBA_MARKET_FINAL_IDENTITY_NOT_VERIFIED")
    home, away = final.get("home_score"), final.get("away_score")
    if (type(home) is not int or type(away) is not int or
        not 0 <= home <= 400 or not 0 <= away <= 400):
        raise ValueError("NBA_MARKET_FINAL_SCORE_UNVERIFIED")
    side = market.get("side")
    if kind == "full_game_moneyline":
        if side not in ("home", "away"):
            raise ValueError("NBA_MARKET_SIDE_INVALID")
        if home == away:
            raise ValueError("NBA_MARKET_UNRESOLVED_DRAW")
        delta = (home-away) if side == "home" else (away-home)
    else:
        line = market.get("line")
        if type(line) not in (float, int) or not isfinite(line) or not -300 <= line <= 500:
            raise ValueError("NBA_MARKET_EXACT_LINE_REQUIRED")
        if kind == "full_game_home_spread":
            if side != "home":
                raise ValueError("NBA_MARKET_SIDE_INVALID")
            delta = home + line - away
        else:
            if side not in ("over", "under"):
                raise ValueError("NBA_MARKET_SIDE_INVALID")
            observed = (home+away if kind == "full_game_total" else
                        home if kind == "full_game_home_team_total" else away)
            delta = observed-line if side == "over" else line-observed
    outcome = "won" if delta > 0 else "lost" if delta < 0 else "push"
    return {"status": "verified_final_research_grade", "outcome": outcome,
            "event_id": str(final["event_id"]), "market_kind": kind,
            "research_only": True, "not_bookable": True,
            "no_code_generated": True, "bookmaker_rule_acceptance": False}
