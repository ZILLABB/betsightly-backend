"""Read-only evidence coverage: bookmaker inventory is not a trained model.

No requests, prediction generation, odds recommendation or bookmaker booking.
Derives teams/leagues only from the currently verified cached board.
"""
from __future__ import annotations
from collections import Counter


def summarize(board: dict) -> dict:
    if not isinstance(board, dict) or board.get("status") != "success":
        return {
            "status": "unavailable", "source": "complete_sportybet_basketball_board",
            "research": "nba_private_only", "leagues": [],
            "teams": [], "total_games": 0,
            "note": "No verified complete bookmaker board available.",
        }
    fixtures = board.get("fixtures") or []
    names, all_teams = {}, set()
    market_counts = Counter()
    for f in fixtures:
        league = str(f.get("competition") or "").strip()
        home, away = str(f.get("home_team") or "").strip(), str(f.get("away_team") or "").strip()
        if not league or not home or not away or home == away:
            continue
        label = names.setdefault(league, {"games": 0, "teams": set()})
        label["games"] += 1
        label["teams"].update((home, away))
        all_teams.update((home, away))
        for m in f.get("markets") or []:
            market_counts[str(m.get("market_id"))] += 1
    competitions = sorted(
        ({"name": name, "upcoming_games": entry["games"],
          "teams": sorted(entry["teams"]),
          "model_status": "private_nba_research" if name.upper() == "NBA" else "bookmaker_only"}
         for name, entry in names.items()),
        key=lambda d: (-d["upcoming_games"], d["name"]),
    )
    return {"status": "success", "source": "complete_sportybet_basketball_board",
            "research": "nba_private_only",
            "leagues": competitions[:80], "teams": sorted(all_teams)[:500],
            "total_games": sum(item["games"] for item in competitions),
            "market_counts": dict(sorted(market_counts.items())),
            "fetched_at": board.get("fetched_at"),
            "note": "Bookmaker listings are not evidence of a trained or calibrated model."}


MODEL_READINESS = {
    "nba_moneyline": {"state": "paper_research", "needs": ("prospective_benchmark", "calibration", "injury_validation")},
    "nba_total_points": {"state": "paper_research", "needs": ("prospective_benchmark", "bookmaker_closing_line_check")},
    "nba_spread": {"state": "not_validated", "needs": ("verified_handicap_labels", "margin_distribution", "paper_grades")},
    "nba_team_totals": {"state": "not_validated", "needs": ("verified_market_identity", "team_score_distributions")},
    "nba_periods": {"state": "not_validated", "needs": ("verified_quarter_boxscores", "period_rules")},
    "nba_player_props": {"state": "not_validated", "needs": ("official_player_id_map", "minutes", "injuries", "lineups", "statistical_grades")},
    "wnba": {"state": "no_approved_forecasts", "needs": ("independent_schedule", "historical_finals", "league_calibration")},
    "ncaa": {"state": "no_approved_forecasts", "needs": ("team_identity", "verified_results", "sufficient_history")},
    "euroleague": {"state": "no_approved_forecasts", "needs": ("independent_boxscores", "team_identity", "season_baseline")},
    "other_leagues": {"state": "no_approved_forecasts", "needs": ("free_verified_feeds", "separate_rules", "settlement_acceptance")},
}
