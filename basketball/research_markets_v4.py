"""Stage 4B research-only full-game probability distribution.

Paired 2026 held-out-development residuals are collected ONLY after models
are fit to earlier seasons. They are not an untouched independent test;
projections are prospective only when saved before 2027 fixture tipoff.
Illustrative thresholds are NOT bookmaker lines, prices, edges, picks or ROI.
"""
from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
import json

CALIBRATOR_VERSION="nba-empirical-paired-residuals-v1"
MIN_CALIBRATION=100
# Clearly illustrative, not retrieved from any sportsbook. Values can be
# changed ONLY before saving any forecast; all 2027 forecasts are immutable.
RESEARCH_LINES={
    "total_points":(220.5,225.5,230.5),
    "home_margin":(-5.5,-2.5,2.5,5.5),
    "home_team_points":(107.5,112.5,117.5),
    "away_team_points":(107.5,112.5,117.5),
}


def _valid_number(value):
    if isinstance(value,bool) or value is None:
        raise ValueError("Missing score projection or nonnumeric line")
    v=float(value)
    if not math.isfinite(v):
        raise ValueError("Nonfinite market projection")
    return v


def conditional_market_probability(
    *, target:str, line:float, expected_total:float,
    expected_margin:float, residuals:list[dict],
)->dict:
    """Empirical over/cover/draw(pushed) probabilities from paired errors.

    total: OVER if score total > line; margin: home covers if margin > line.
    team: score > line. Opposite win/loss events plus pushes sum exactly 1.
    Rounding probabilities is for presentation only, never staking.
    """
    if target not in RESEARCH_LINES:
        raise ValueError("Unsupported NBA research target")
    line=_valid_number(line)
    total=_valid_number(expected_total)
    margin=_valid_number(expected_margin)
    if not 80<=total<=400 or not -100<=margin<=100:
        raise ValueError("NBA score projections out of accepted research range")
    if not isinstance(residuals,list) or len(residuals)<MIN_CALIBRATION:
        raise ValueError("At least 100 paired validation residuals required")
    wins=pushes=0
    for item in residuals:
        if not isinstance(item,dict):
            raise ValueError("Corrupted paired residual calibration")
        rt=_valid_number(item.get("total_points"))
        rm=_valid_number(item.get("home_margin"))
        if not -150<=rt<=150 or not -120<=rm<=120:
            raise ValueError("Out-of-bounds NBA validation residual")
        realized_total=total+rt
        realized_margin=margin+rm
        if target=="total_points":
            observed=realized_total
        elif target=="home_margin":
            observed=realized_margin
        elif target=="home_team_points":
            observed=(realized_total+realized_margin)/2
        else:
            observed=(realized_total-realized_margin)/2
        if math.isclose(observed,line,rel_tol=0,abs_tol=1e-7):
            pushes+=1
        elif observed>line:
            wins+=1
    count=len(residuals)
    return {
        "target":target,
        "line":line,
        "above_probability":round(wins/count,6),
        "below_probability":round((count-wins-pushes)/count,6),
        "push_probability":round(pushes/count,6),
        "calibration_samples":count,
        "calibration_type":"historical development residual bootstrap",
        "residual_season":2026,
        "not_a_bookmaker_line":True,
        "market_price_verified":False,
        "not_a_betting_recommendation":True,
    }


def market_grid(*, expected_total:float|None,
                expected_margin:float|None,
                residuals:list[dict]|None)->dict:
    """Four full-game market families; fail-closed for missing real inputs."""
    if expected_total is None or expected_margin is None or residuals is None:
        return {
            "status":"blocked",
            "reason":"missing_pretrained_score_projection_or_paired_residuals",
            "market_price_verified":False,"research_only":True,
        }
    by_target={}
    for target,lines in RESEARCH_LINES.items():
        by_target[target]=[
            conditional_market_probability(
                target=target,line=line,expected_total=expected_total,
                expected_margin=expected_margin,residuals=residuals
            ) for line in lines
        ]
    return {
        "status":"research_only",
        "calibrator":CALIBRATOR_VERSION,
        "markets":by_target,
        "markets_available":[*RESEARCH_LINES],
        "markets_blocked":{
            "first_half_total_points":"No period-specific final-score and pregame training cohort",
            "first_half_spread":"No validated historical first-half scores",
            "player_props":"No bookable pregame player-prop lines or availability feed",
        },
        "thresholds_source":"fixed illustrative research grid, not sportsbook",
        "same_game_market_dependence":"Preserved by paired total-and-margin residuals",
        "calibration_season":2026,
        "validated_on_new_2027_games":False,
        "betting_roi_computed":False,
        "no_bookmaker_odds":True,
        "public_publishing_enabled":False,
    }


def market_report_from_home(home:str|Path)->dict:
    """Read immutable shadow forecasts and separately verified settlements."""
    root=Path(home)/"advanced"
    ledger=root/"shadow_2027.jsonl"
    settled_file=root/"shadow_settlements_2027.json"
    existing=[]
    if ledger.is_file():
        from basketball.research_advanced_model import _canonical
        import hashlib
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if not line.strip():continue
            item=json.loads(line)
            canonical={k:v for k,v in item.items() if k not in ("sha256","settlement")}
            if hashlib.sha256(_canonical(canonical).encode()).hexdigest()!=item.get("sha256"):
                raise ValueError("Research market forecast integrity mismatch")
            existing.append(item)
    settlements=json.loads(settled_file.read_text(encoding="utf-8")) if settled_file.is_file() else {}
    if not isinstance(settlements,dict):
        raise ValueError("Corrupt independent market settlement map")
    samples=defaultdict(list)
    for item in existing:
        actual=settlements.get(str(item["game_id"]))
        if not actual:continue
        scores=actual["scores"]
        if not isinstance(scores,list) or len(scores)!=2:
            raise ValueError("Incomplete market settlement scores")
        total=sum(scores)
        margin=scores[0]-scores[1]
        marks={
            "total_points":total,
            "home_margin":margin,
            "home_team_points":scores[0],
            "away_team_points":scores[1],
        }
        market=item.get("market_probabilities") or {}
        for target,entries in (market.get("markets") or {}).items():
            if target not in RESEARCH_LINES:continue
            for prediction in entries:
                line=_valid_number(prediction["line"])
                p=_valid_number(prediction["above_probability"])
                if not 0<=p<=1:
                    raise ValueError("Invalid stored market probability")
                if marks[target]==line:continue # push is neither win nor loss
                y=1 if marks[target]>line else 0
                samples[(target,line)].append((p,y))
    scored=[]
    for (target,line),values in sorted(samples.items()):
        n=len(values)
        scored.append({
            "target":target,"line":line,
            "settled_nonpush":n,
            "accuracy":round(sum(int((p>=0.5)==y) for p,y in values)/n,5),
            "brier":round(sum((p-y)**2 for p,y in values)/n,6),
            "review_ready":n>=100,
        })
    return {
        "status":"research_only","forecast_count":len(existing),
        "verified_final_count":sum(1 for item in existing
                                   if str(item["game_id"]) in settlements),
        "market_metrics":scored,
        "minimum_forward_games":100,
        "thresholds_are_bookmaker_lines":False,
        "bookmaker_roi":None,
        "first_half_market_enabled":False,
        "commercial_use_review_required":True,
        "no_writes":True,"public_publishing_enabled":False,
    }
