"""Stage 3C research candidate: pregame-safe boxscore/player features.

Never joins the *target* game's box score to its own predictors. Each
fixture date is evaluated from previously completed same-season history.
No current injury status or future roster appears in historical features.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from itertools import groupby
from pathlib import Path
from statistics import mean

from basketball.research_features import FEATURE_COLUMNS as V1_FEATURES, make_rows
from basketball.research_data import read_games

VERSION="nba-advanced-boxscore-shadow-v1"
ADVANCED_COLS=(
    "home_est_poss_5","away_est_poss_5",
    "home_off_rating_5","away_off_rating_5",
    "home_def_rating_5","away_def_rating_5",
    "home_efg_5","away_efg_5",
    "home_3rate_5","away_3rate_5",
    "home_turnover_rate_5","away_turnover_rate_5",
    "home_rotation_minutes_5","away_rotation_minutes_5",
    "home_top_scorer_share_5","away_top_scorer_share_5",
)
FEATURE_COLUMNS=V1_FEATURES+ADVANCED_COLS
MIN_PRIOR=5


def _load_json(path:Path)->list[dict]:
    content=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(content,list):raise ValueError("Expected private box-score list")
    return content


def _prepare(games:list[dict],team_rows:list[dict],
             player_rows:list[dict])->tuple[dict,dict]:
    finals={str(g["game_id"]):g for g in games if g["status"]=="final"}
    teams={}
    for row in team_rows:
        key=(str(row["game_id"]),str(row["team_id"]))
        if key in teams:raise ValueError("Duplicate team box-score row")
        teams[key]=row
    players=defaultdict(list)
    seen=set()
    for row in player_rows:
        key=(str(row["game_id"]),str(row["team_id"]),str(row["athlete_id"]))
        if key in seen:raise ValueError("Duplicate player box-score")
        seen.add(key)
        players[(key[0],key[1])].append(row)
    # Only accept a game where both sides are verified by the authoritative
    # local fixture, including the opponent and result identity.
    valid_team={}
    valid_player={}
    for game_id,g in finals.items():
        home=(game_id,str(g["home_id"]))
        away=(game_id,str(g["away_id"]))
        h,a=teams.get(home),teams.get(away)
        if h is None or a is None:continue
        if (h["score"]!=g["home_score"] or a["score"]!=g["away_score"] or
                str(h["opponent_team_id"])!=away[1] or
                str(a["opponent_team_id"])!=home[1]):
            raise ValueError("NBA advanced feature fixture score or identity conflict")
        valid_team[home]=h
        valid_team[away]=a
        valid_player[home]=players.get(home,[])
        valid_player[away]=players.get(away,[])
    return valid_team,valid_player


def _team_vectors(tail:list[dict],player_tail:list[list[dict]])->tuple:
    if len(tail)<MIN_PRIOR:raise ValueError("Insufficient earlier advanced data")
    f=tail[-MIN_PRIOR:]
    player_games=player_tail[-MIN_PRIOR:]
    if len(player_games)!=MIN_PRIOR or any(not group for group in player_games):
        raise ValueError("Missing per-game player box score")
    # Defensive allowed efficiency requires matching opponent rows. Stored
    # opponent estimate was attached at the verified earlier game join.
    possessions=mean(r["estimated_possessions"] for r in f)
    offensive=mean(r["estimated_offensive_rating"] for r in f)
    defensive=mean(r["opponent_offensive_rating"] for r in f)
    efg=mean(r["e_fg"] for r in f if r["e_fg"] is not None)
    three=mean(r["three_rate"] for r in f if r["three_rate"] is not None)
    tov=mean(r["turnovers"]/r["estimated_possessions"] for r in f)
    rotations=[]
    top_scoring=[]
    for group in player_games:
        active=[p for p in group if p["minutes"]>0]
        if not active:raise ValueError("No valid earlier player minutes")
        top_scoring.append(max(p["points"] for p in active)/
                           max(1,sum(p["points"] for p in active)))
        rotations.append(sum(p["minutes"] for p in active))
    if not (160<=mean(rotations)<=320):
        raise ValueError("Player minutes coverage incomplete")
    return (
        possessions, offensive,defensive,efg,three,tov,
        mean(rotations),mean(top_scoring),
    )


def make_advanced_rows(games:list[dict],team_rows:list[dict],
                       player_rows:list[dict])->tuple[list[dict],dict]:
    baseline=make_rows(games,min_prior=5)
    baseline_by_id={str(r["game_id"]):r for r in baseline}
    teams,players=_prepare(games,team_rows,player_rows)
    history=defaultdict(list)
    p_history=defaultdict(list)
    finished=[]
    skipped=0
    for _, batch_iter in groupby(
        sorted(games,key=lambda g:(g["date"],str(g["game_id"]))),
        lambda g:g["date"]
    ):
        batch=list(batch_iter)
        for g in batch:
            base=baseline_by_id.get(str(g["game_id"]))
            if not base:continue
            h=(g["season"],str(g["home_id"]))
            a=(g["season"],str(g["away_id"]))
            if (len(history[h])<MIN_PRIOR or len(history[a])<MIN_PRIOR or
                    len(p_history[h])<MIN_PRIOR or len(p_history[a])<MIN_PRIOR):
                skipped+=1
                continue
            try:
                h_feature=_team_vectors(history[h],p_history[h])
                a_feature=_team_vectors(history[a],p_history[a])
            except (ValueError,ZeroDivisionError):
                skipped+=1
                continue
            extras=tuple(val for pair in zip(h_feature,a_feature) for val in pair)
            finished.append({
                **base,"features":tuple(base["features"])+extras,
                "feature_schema":VERSION,
            })
        for g in batch:
            if g["status"]!="final" or g["postseason"]:continue
            gid=str(g["game_id"])
            h=(gid,str(g["home_id"]))
            a=(gid,str(g["away_id"]))
            th,ta=teams.get(h),teams.get(a)
            if th is None or ta is None:continue
            key_h=(g["season"],h[1]);key_a=(g["season"],a[1])
            history[key_h].append({**th,
                "opponent_offensive_rating":ta["estimated_offensive_rating"]})
            history[key_a].append({**ta,
                "opponent_offensive_rating":th["estimated_offensive_rating"]})
            p_history[key_h].append(players.get(h,[]))
            p_history[key_a].append(players.get(a,[]))
    return finished,{
        "baseline_eligible_rows":len(baseline),
        "advanced_eligible_rows":len(finished),
        "skipped_missing_prior_advanced_games":skipped,
        "exact_joined_final_games":len(teams)//2,
        "candidate_schema":VERSION,
        "research_only":True,
        "not_a_betting_model":True,
    }


def from_home(home:str|Path)->tuple[list[dict],dict]:
    root=Path(home)
    games=read_games(root/"nba_games.jsonl")
    box=root/"advanced"
    years=sorted({g["season"] for g in games})
    all_team=[]
    all_player=[]
    both=[]
    for season in years:
        t,p=box/f"team_{season}.json",box/f"player_{season}.json"
        if t.is_file() and p.is_file():
            all_team.extend(_load_json(t))
            all_player.extend(_load_json(p))
            both.append(season)
    if not both:
        return [],{
            "status":"not_ready","reason":"no_seasons_with_both_validated_assets",
            "available_seasons":[],"research_only":True,
        }
    rows,metrics=make_advanced_rows(games,all_team,all_player)
    metrics.update({
        "status":"ready" if rows else "warming_up",
        "available_seasons":both,
        "feature_count":len(FEATURE_COLUMNS),
        "research_only":True,
        "public_publishing_enabled":False,
    })
    return rows,metrics
