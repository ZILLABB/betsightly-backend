"""NBA opening-week score projection research: totals, margin, team points.

Fixed-form previous-season and earlier-current-season scored/allowed means.
Not a probabilistic spread, bookmaker line, market price, or wagering model.
Never changes archived moneyline forecasts, trusted v1 or advanced candidates.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from itertools import groupby
from pathlib import Path

from basketball.research_coldstart import _now, _read_ledger, _signed, _json
from basketball.research_data import read_games, APPROVED_RESEARCH_SOURCES
from basketball.research_readiness import _snapshot_health, _timestamp
from basketball.research_cup_classification import identify_cup_final

VERSION = "nba-opening-score-prior-shadow-v1"
FORECASTS = "opening_score_forecasts.jsonl"
FINALS = "opening_score_settlements.jsonl"
MIN_PRIOR = 20
WARMUP_LIMIT = 4
PREGAME_BUFFER = timedelta(minutes=10)
WINDOW = timedelta(hours=48)


def _corrected(games):
    """Exclude only the exact nonstandings NBA Cup final, never edit source."""
    status, identified = identify_cup_final(games)
    if status == "ambiguous_multiple_matches":
        raise ValueError("Ambiguous nonstandings Cup final source")
    blocked = {str(g["game_id"]) for g in identified}
    return [g for g in games if str(g["game_id"]) not in blocked]


def _history(games):
    previous = defaultdict(lambda: [0., 0., 0])
    league = defaultdict(lambda: [0., 0., 0])
    for g in games:
        if g["status"] != "final" or g["postseason"]:
            continue
        season = int(g["season"])
        h, a = str(g["home_id"]), str(g["away_id"])
        hs, av = g["home_score"], g["away_score"]
        if (not all(isinstance(n,int) and not isinstance(n,bool)
                    for n in (hs,av)) or min(hs,av) < 0):
            raise ValueError("Invalid verified NBA final")
        previous[(season,h)][0] += hs
        previous[(season,h)][1] += av
        previous[(season,h)][2] += 1
        previous[(season,a)][0] += av
        previous[(season,a)][1] += hs
        previous[(season,a)][2] += 1
        league[season][0] += hs
        league[season][1] += av
        league[season][2] += 1
    return previous,league


def _estimate(prior, recent):
    # Previous year supplies 12 pseudo-games, current year at most four.
    prev_for,prev_allowed,n = prior
    curr_for,curr_allowed,m = recent
    if n < MIN_PRIOR:
        raise ValueError("Insufficient previous-season actual scored/allowed games")
    return ((12 * prev_for/n + curr_for)/(12+m),
            (12 * prev_allowed/n + curr_allowed)/(12+m))


def candidates(games, *, now=None, historical=False, seasons=(2025,2026)):
    instant = _now(now)
    vetted = _corrected(games)
    previous, league = _history(vetted)
    current = defaultdict(lambda: [0., 0., 0])
    rows = []
    ordered = sorted(vetted, key=lambda g: (
        int(g["season"]),g["date"],str(g["game_id"])))
    for (_, _),group in groupby(
        ordered,key=lambda g:(int(g["season"]),g["date"])
    ):
        day = list(group)
        for g in day:
            if g["postseason"]:
                continue
            if historical:
                if g["status"] != "final" or g["season"] not in seasons:
                    continue
            elif g["status"] != "scheduled":
                continue
            stamp = _timestamp(g.get("start_utc"))
            if stamp is None or (not historical and not (
                instant + PREGAME_BUFFER < stamp <= instant + WINDOW
            )):
                continue
            season = int(g["season"])
            h,a = str(g["home_id"]),str(g["away_id"])
            hp,ap = previous[(season-1,h)],previous[(season-1,a)]
            hc,ac = current[(season,h)],current[(season,a)]
            if hp[2] < MIN_PRIOR or ap[2] < MIN_PRIOR:
                continue
            if hc[2] > WARMUP_LIMIT and ac[2] > WARMUP_LIMIT:
                continue
            lg = league[season-1]
            if lg[2] < 200:
                continue
            hfor,hallow = _estimate(hp,hc)
            afor,aallow = _estimate(ap,ac)
            # Same home advantage added/subtracted to preserve projected
            # total. Its value is fixed before future 2027 results.
            home = (hfor + aallow)/2 + 1.5
            away = (afor + hallow)/2 - 1.5
            expected_total = home+away
            expected_margin = home-away
            baseline_home,baseline_away = lg[0]/lg[2], lg[1]/lg[2]
            row={
                "game_id":str(g["game_id"]), "date":g["date"],
                "start_utc":stamp.isoformat(),"season":season,
                "home_id":h,"away_id":a,
                "home_team":g["home_name"],"away_team":g["away_name"],
                "current_home_games":hc[2],"current_away_games":ac[2],
                "prior_home_games":hp[2],"prior_away_games":ap[2],
                "predicted_home_points":round(home,4),
                "predicted_away_points":round(away,4),
                "predicted_total":round(expected_total,4),
                "predicted_home_margin":round(expected_margin,4),
                "league_baseline_total":round(baseline_home+baseline_away,4),
                "league_baseline_margin":round(baseline_home-baseline_away,4),
                "league_baseline_home_points":round(baseline_home,4),
                "league_baseline_away_points":round(baseline_away,4),
                "source":g["source"],"model_version":VERSION,
            }
            if historical:
                row.update({
                    "actual_total":g["home_score"]+g["away_score"],
                    "actual_home_margin":g["home_score"]-g["away_score"],
                    "actual_home_points":g["home_score"],
                    "actual_away_points":g["away_score"],
                })
            rows.append(row)
        # Every game on the same schedule date uses the same earlier
        # historical state, including cases with misleading UTC ordering.
        for g in day:
            if g["status"] != "final" or g["postseason"]:
                continue
            season=int(g["season"])
            h,a=str(g["home_id"]),str(g["away_id"])
            hs, av=g["home_score"],g["away_score"]
            current[(season,h)][0]+=hs
            current[(season,h)][1]+=av
            current[(season,h)][2]+=1
            current[(season,a)][0]+=av
            current[(season,a)][1]+=hs
            current[(season,a)][2]+=1
    return sorted(rows,key=lambda r:(r["start_utc"],r["game_id"]))


TARGETS=(
    ("total","predicted_total","league_baseline_total","actual_total"),
    ("home_margin","predicted_home_margin","league_baseline_margin","actual_home_margin"),
    ("home_points","predicted_home_points","league_baseline_home_points","actual_home_points"),
    ("away_points","predicted_away_points","league_baseline_away_points","actual_away_points"),
)


def _metrics(rows):
    result={"games":len(rows),"targets":{}}
    for target,pred,baseline,actual in TARGETS:
        n=len(rows)
        if not n:
            result["targets"][target]={"candidate_mae":None,
                                       "baseline_mae":None,
                                       "paired_mae_improvement":None,
                                       "candidate_rmse":None,
                                       "candidate_bias":None}
            continue
        errors=[float(r[pred])-float(r[actual]) for r in rows]
        errors_base=[float(r[baseline])-float(r[actual]) for r in rows]
        candidate_mae=sum(abs(x) for x in errors)/n
        base_mae=sum(abs(x) for x in errors_base)/n
        result["targets"][target]={
            "candidate_mae":round(candidate_mae,4),
            "baseline_mae":round(base_mae,4),
            "paired_mae_improvement":round(base_mae-candidate_mae,4),
            "candidate_rmse":round(math.sqrt(sum(x*x for x in errors)/n),4),
            "candidate_bias":round(sum(errors)/n,4),
        }
    return result


def benchmark(games):
    rows=candidates(games,historical=True)
    return {
        "status":"research_only","model_version":VERSION,
        "historical_folds":{
            str(y):_metrics([r for r in rows if r["season"]==y])
            for y in (2025,2026)},
        "pooled":_metrics(rows),
        "leakage_guard":"previous season and earlier same-date batches only",
        "cup_final_nonstandings_excluded_from_research_features":True,
        "historical_results_are_not_live_validation":True,
        "market_lines_or_odds_present":False,
        "not_a_betting_market":True,
        "no_writes":True,
    }


def _read(path):
    return _read_ledger(path)


def audit(home, *, now=None):
    instant=_now(now)
    root=Path(home)
    try:
        original=_read(root/FORECASTS)
        results=_read(root/FINALS)
        file=root/"nba_games.jsonl"
        games={str(g["game_id"]):g for g in read_games(file)} if file.is_file() else {}
    except (ValueError,TypeError,OSError,UnicodeError) as exc:
        return {"status":"integrity_failed","reason":type(exc).__name__,
                "research_only":True,"no_writes":True,
                "forecasts":None,"settled":None,"pending":None}
    errors=[]
    seen=set()
    for item in original:
        gid=str(item.get("game_id"))
        game=games.get(gid)
        published=_timestamp(item.get("captured_at"))
        start=_timestamp(item.get("start_utc"))
        values=[item.get(k) for k in (
            "predicted_home_points","predicted_away_points",
            "predicted_total","predicted_home_margin")]
        if (gid in seen or game is None or not published or not start or
            published>=start or published+PREGAME_BUFFER>=start or
            item.get("model_version")!=VERSION or
            item.get("research_only") is not True or
            item.get("not_bookable") is not True or
            item.get("bookmaker_prices_verified") is not False or
            item.get("source") not in APPROVED_RESEARCH_SOURCES or
            _timestamp(game.get("start_utc"))!=start or
            any(str(item.get(k))!=str(game.get(k))
                for k in ("date","season","home_id","away_id")) or
            any(not isinstance(v,(int,float)) or isinstance(v,bool)
                or not math.isfinite(v) for v in values) or
            abs(values[2]-values[0]-values[1])>0.0002 or
            abs(values[3]-values[0]+values[1])>0.0002):
            errors.append("invalid_pregame_score_projection")
        seen.add(gid)
    done={}
    for item in results:
        gid=str(item.get("game_id"))
        game=games.get(gid)
        end=_timestamp(item.get("settled_at"))
        if (gid in done or gid not in seen or not game or
            game["status"]!="final" or not end or
            end<=_timestamp(game.get("start_utc")) or
            item.get("home_score")!=game["home_score"] or
            item.get("away_score")!=game["away_score"] or
            item.get("source") not in APPROVED_RESEARCH_SOURCES):
            errors.append("invalid_score_verification")
        done[gid]=item
    if errors:
        return {"status":"integrity_failed","integrity_errors":sorted(set(errors)),
                "research_only":True,"no_writes":True,
                "forecasts":len(original),"settled":len(done),"pending":None,
                "prospective_metrics":None}
    matched=[]
    for item in original:
        gid=str(item["game_id"])
        if gid not in done:
            continue
        fin=done[gid]
        home,away=fin["home_score"],fin["away_score"]
        matched.append({**item,
                        "actual_total":home+away,
                        "actual_home_margin":home-away,
                        "actual_home_points":home,
                        "actual_away_points":away})
    states={"not_started":0,"awaiting_verified_final":0,
            "final_available_pending_settlement":0,"verified_settled":0}
    for item in original:
        gid=str(item["game_id"])
        if gid in done:
            states["verified_settled"]+=1
        elif gid in games and games[gid]["status"]=="final":
            states["final_available_pending_settlement"]+=1
        elif _timestamp(item["start_utc"])>instant:
            states["not_started"]+=1
        else:
            states["awaiting_verified_final"]+=1
    return {
        "status":("awaiting_first_forecast" if not original else
                  "awaiting_first_verified_final" if not matched
                  else "forward_observations"),
        "research_only":True,"model_version":VERSION,
        "forecasts":len(original),"settled":len(matched),
        "pending":len(original)-len(matched),
        "prospective_metrics":_metrics(matched),
        "last_30_verified":_metrics(matched[-30:]),
        "operational_states":states,
        "integrity_errors":[],"no_writes":True,"not_bookable":True,
        "no_bookmaker_lines_or_roi":True,"trusted_v1_changed":False,
    }


def capture(home, *, now=None):
    instant=_now(now)
    root=Path(home)
    games=read_games(root/"nba_games.jsonl")
    if _snapshot_health(games,instant)["status"]!="fresh":
        return {"status":"source_not_fresh","created":0,"research_only":True}
    checked=audit(root,now=instant)
    if checked["status"]=="integrity_failed":
        return {"status":"integrity_failed","created":0}
    recorded={str(r["game_id"]) for r in _read(root/FORECASTS)}
    upcoming=candidates(games,now=instant)
    new=[r for r in upcoming if str(r["game_id"]) not in recorded][:30]
    if new:
        with (root/FORECASTS).open("a",encoding="utf-8") as out:
            for item in new:
                row={**item,"captured_at":instant.isoformat(),
                     "research_only":True,"not_bookable":True,
                     "bookmaker_prices_verified":False}
                out.write(_json({**row,"sha256":_signed(row)})+"\n")
    return {"status":"research_only","created":len(new),
            "eligible":len(upcoming),"already_recorded":len(upcoming)-len(new),
            "not_bookable":True}


def settle(home, *, now=None):
    instant=_now(now)
    root=Path(home)
    checked=audit(root,now=instant)
    if checked["status"]=="integrity_failed":
        return {"status":"integrity_failed","new_settlements":0}
    forecast=_read(root/FORECASTS)
    recorded={str(r["game_id"]) for r in _read(root/FINALS)}
    path=root/"nba_games.jsonl"
    games={str(g["game_id"]):g for g in read_games(path)} if path.is_file() else {}
    fresh=[]
    for row in forecast:
        game=games.get(str(row["game_id"]))
        if (str(row["game_id"]) in recorded or not game or
            game["status"]!="final" or
            instant<=_timestamp(game.get("start_utc"))):
            continue
        if game["source"] not in APPROVED_RESEARCH_SOURCES:
            raise ValueError("Unknown NBA score source")
        payload={
            "game_id":str(row["game_id"]),
            "home_score":game["home_score"],
            "away_score":game["away_score"],
            "source":game["source"],
            "settled_at":instant.isoformat(),
            "research_only":True,
        }
        fresh.append({**payload,"sha256":_signed(payload)})
    if fresh:
        with (root/FINALS).open("a",encoding="utf-8") as out:
            for item in fresh:
                out.write(_json(item)+"\n")
    return {"status":"research_only","new_settlements":len(fresh),
            "not_bookable":True}


def cycle(home, *, now=None):
    instant=_now(now)
    result=settle(home,now=instant)
    if result["status"]=="integrity_failed":
        return {"status":"integrity_failed","created":0,
                "new_settlements":0}
    captured=capture(home,now=instant)
    return {**captured,"new_settlements":result["new_settlements"]}
