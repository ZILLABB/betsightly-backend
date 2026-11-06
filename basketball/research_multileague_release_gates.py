"""Fail-closed release maturity for WNBA/NCAA/EuroLeague/EuroCup/NBL.

Data availability != licensed training != a tested prediction model.
No writes, no cross-league grading, no basketball bookmaker code.
"""
from __future__ import annotations

CANDIDATE_LEAGUES = ("wnba", "ncaa_men", "ncaa_women",
                     "euroleague", "eurocup", "nbl_au")
MIN_INDEPENDENT_FINALS = 100
MIN_COMPLETE_SEASONS = 2


def assess_league(league, evidence):
    if league not in CANDIDATE_LEAGUES or not isinstance(evidence, dict):
        raise ValueError("NBA_LEAGUE_UNKNOWN_OR_EVIDENCE_INVALID")
    checks = ("licensed_for_this_use", "stable_team_ids",
              "cross_source_final_agreement", "date_complete",
              "league_period_rules_verified", "pre_tipoff_features_original",
              "independent_calibration_passed")
    accepted = {name: evidence.get(name) is True for name in checks}
    finals = evidence.get("independent_verified_finals")
    seasons = evidence.get("complete_seasons")
    if type(finals) is not int or not 0 <= finals <= 200000:
        raise ValueError("NBA_LEAGUE_FINAL_COUNT_INVALID")
    if type(seasons) is not int or not 0 <= seasons <= 100:
        raise ValueError("NBA_LEAGUE_SEASON_COUNT_INVALID")
    blockers = [name for name in checks if not accepted[name]]
    if finals < MIN_INDEPENDENT_FINALS:
        blockers.append("insufficient_independent_finals")
    if seasons < MIN_COMPLETE_SEASONS:
        blockers.append("incomplete_historical_seasons")
    return {"league": league, "phase": "candidate" if blockers else "validated_research",
            "verified_final_count": finals, "complete_seasons": seasons,
            "blockers": blockers, "source_readiness_checked": True,
            "model_eligible": not blockers,
            "public_publishing_enabled": False,
            "bookmaker_code_enabled": False, "not_bookable": True}
