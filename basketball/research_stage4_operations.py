"""Stage 4 combined advanced-market readiness, source health and forward report.

A single read-only snapshot. Explicitly separates engineering readiness,
development-only comparisons, prospectively settled predictions and rights.
"""
from __future__ import annotations

import json
from datetime import datetime,timezone
from pathlib import Path

from basketball.research_advanced_data import advanced_coverage
from basketball.research_injury_reports import injury_status
from basketball.research_injury_identity_v4 import injury_crosswalk
from basketball.research_markets_v4 import market_report_from_home


def stage4_report(home:str|Path,*,now:datetime|None=None)->dict:
    root=Path(home)
    instant=now or datetime.now(timezone.utc)
    if instant.tzinfo is None:raise ValueError("UTC-aware clock required")
    coverage=advanced_coverage(root)
    injuries=injury_status(root)
    crosswalk=injury_crosswalk(root,as_of=instant)
    markets=market_report_from_home(root)
    # Health doesn't turn absent data into zeros or invented 2027 releases.
    current={str(record["kind"]):record for record in coverage["assets"]
             if record["season"]==2027}
    missing=[kind for kind in ("team","player") if kind not in current]
    reports=list((root/"advanced").glob("*.manifest.json"))
    blocked=[]
    if missing:blocked.append("missing_2027_"+ "_".join(missing)+"_boxscores")
    if not coverage["shadow_model_installed"]:
        blocked.append("advanced_shadow_model_not_installed")
    if injuries["status"] not in ("parsed",):
        blocked.append("official_injury_report_unparsed_or_absent")
    if crosswalk.get("eligible_for_model_features") is not True:
        blocked.append("injury_athlete_identity_or_submission_coverage_unverified")
    if markets["verified_final_count"]<100:
        blocked.append("fewer_than_100_new_verified_forward_games")
    blocked.extend([
        "first_half_period_scores_unavailable",
        "licensed_bookmaker_prices_unavailable",
        "commercial_data_rights_not_cleared",
    ])
    score_info={}
    model=root/"advanced"/"shadow_model.joblib"
    if model.is_file():
        try:
            # Read companion report only through trusted local-only model.
            import joblib
            bundle=joblib.load(model)
            if bundle.get("research_only") is not True:
                raise ValueError("Nonprivate model")
            score_info={
                "version":bundle.get("model_version"),
                "training_through_season":bundle.get("trained_through_season"),
                "paired_calibration_samples":len(bundle.get("market_residuals") or []),
                "historical_validation_is_reused":True,
            }
        except (ValueError,OSError,KeyError,TypeError,EOFError,ImportError):
            blocked.append("shadow_model_unreadable")
    return {
        "status":"research_only",
        "phase":"stage4_integrated",
        "generated_at":instant.astimezone(timezone.utc).isoformat(),
        "current_2027_verified_assets":current,
        "current_2027_missing_assets":missing,
        "advanced":coverage,
        "injury_report":injuries,
        "injury_player_identity":crosswalk,
        "probability_markets":markets,
        "model":score_info,
        "market_support":{
            "moneyline_shadow":coverage["shadow_model_installed"],
            "full_game_total":bool(score_info.get("paired_calibration_samples",0)>=100),
            "full_game_handicap":bool(score_info.get("paired_calibration_samples",0)>=100),
            "home_and_away_team_totals":bool(score_info.get("paired_calibration_samples",0)>=100),
            "first_half":False,
            "player_props":False,
            "injury_adjusted_predictions":False,
        },
        "blockers":blocked,
        "deployable_to_public":False,
        "bookmaker_odds_verified":False,
        "non_bookable_research":True,
        "football_data_isolation":True,
        "no_writes":True,
    }
