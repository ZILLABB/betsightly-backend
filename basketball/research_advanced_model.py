"""Stage 3C independent NBA advanced candidate and immutable shadow records.

The v1 models, main private SQLite ledger and paper forecasts are immutable.
This experimental model uses verified team/player box scores and strictly
pre-tipoff predictions. Historical comparisons are development diagnostics,
not new unseen evaluation or betting profitability.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from basketball.research_advanced_features import FEATURE_COLUMNS, VERSION, from_home

MODEL_VERSION="nba-advanced-shadow-2026-v1"
BASELINE_MODEL_VERSION="nba-moneyline-offline-v1"
MIN_TRAIN=350
MIN_VALID=100


def _deps():
    import joblib
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return joblib,np,LogisticRegression,make_pipeline,StandardScaler


def _score(actual,probs,np):
    y=np.asarray(actual,dtype=float)
    p=np.asarray(probs,dtype=float)
    if not len(y) or not np.isfinite(p).all() or not np.isfinite(y).all():
        raise ValueError("Advanced evaluation requires real labels and finite predictions")
    p=np.clip(p,1e-9,1-1e-9)
    return {
        "games":len(y),
        "accuracy":round(float(np.mean((p>=.5)==y)),5),
        "brier":round(float(np.mean((p-y)**2)),6),
        "log_loss":round(float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p))),6),
    }


def build_candidate(home:Path|str)->dict:
    """Fit shadow candidate on completed games ending in 2025, validate 2026.

    The v1 same-fixture comparator is trained on exactly the SAME matched
    cohort, not against the prior v1 official historic 1711-game report.
    2027 is reserved for *new pregame* shadow records, not retrospective
    evaluation of previously completed 2027 games.
    """
    root=Path(home)
    rows,coverage=from_home(root)
    if coverage["status"]=="not_ready":
        return {"status":"blocked","reason":coverage["reason"],"coverage":coverage,
                "research_only":True,"public_publishing_enabled":False}
    train=[r for r in rows if r["status"]=="final" and r["season"]<=2025]
    valid=[r for r in rows if r["status"]=="final" and r["season"]==2026]
    if len(train)<MIN_TRAIN or len(valid)<MIN_VALID:
        return {
            "status":"blocked","reason":"insufficient_earlier_matched_box_scores",
            "training_games":len(train),"validation_games":len(valid),
            "required_train":MIN_TRAIN,"required_validation":MIN_VALID,
            "coverage":coverage,"research_only":True,
            "public_publishing_enabled":False,
        }
    joblib,np,LR,pipe,scaler=_deps()
    def X(part,baseline):
        return np.asarray(
            [r["features"][:14] if baseline else r["features"] for r in part],
            dtype=float,
        )
    y_train=np.asarray([r["home_win"] for r in train],dtype=int)
    y_valid=np.asarray([r["home_win"] for r in valid],dtype=int)
    if len(set(y_train))!=2:
        raise ValueError("Advanced training cohort lacks two result classes")
    results={}
    fits={}
    for name,baseline in (("matched_v1_features",True),("advanced_candidate",False)):
        candidates=[]
        for c in (.03,.1,.3,1.0):
            model=pipe(scaler(),LR(C=c,max_iter=1000,random_state=42))
            model.fit(X(train,baseline),y_train)
            p=model.predict_proba(X(valid,baseline))[:,1]
            candidates.append((float(np.mean((p-y_valid)**2)),c,model))
        _,choice,winner=min(candidates,key=lambda item:(item[0],item[1]))
        pred=winner.predict_proba(X(valid,baseline))[:,1]
        results[name]={
            "selected_C":choice,
            "validation_2026":_score(y_valid,pred,np),
        }
        # Only refit on truly completed pre-2027 games. Do not include
        # outcomes from the intended 2027 forward-shadow period.
        all_history=[r for r in rows if r["status"]=="final" and r["season"]<=2026]
        refit=pipe(scaler(),LR(C=choice,max_iter=1000,random_state=42))
        refit.fit(X(all_history,baseline),
                  np.asarray([r["home_win"] for r in all_history],dtype=int))
        fits[name]=refit
    # Score projection research is also independent of bookmaker markets.
    # Validation is historical/development-only and uses real final scores.
    from sklearn.linear_model import Ridge
    score_results={}
    score_fits={}
    historical=[r for r in rows if r["status"]=="final" and r["season"]<=2026]
    for target in ("total_points","home_margin"):
        score_results[target]={}
        score_fits[target]={}
        for name,baseline in (("matched_v1_features",True),
                              ("advanced_candidate",False)):
            Xt=X(train,baseline)
            Xv=X(valid,baseline)
            target_train=np.asarray([r[target] for r in train],dtype=float)
            target_valid=np.asarray([r[target] for r in valid],dtype=float)
            candidates=[]
            for alpha in (.1,1.,10.,100.):
                reg=pipe(scaler(),Ridge(alpha=alpha))
                reg.fit(Xt,target_train)
                predictions=reg.predict(Xv)
                candidates.append((
                    float(np.mean(np.abs(predictions-target_valid))),
                    alpha,reg))
            _,selected,chosen=min(candidates,key=lambda r:(r[0],r[1]))
            difference=chosen.predict(Xv)-target_valid
            score_results[target][name]={
                "selected_alpha":selected,
                "historical_validation_2026":{
                    "games":len(valid),
                    "mae":round(float(np.mean(np.abs(difference))),5),
                    "rmse":round(float(np.sqrt(np.mean(difference**2))),5),
                    "bias":round(float(np.mean(difference)),5),
                },
            }
            frozen=pipe(scaler(),Ridge(alpha=selected))
            frozen.fit(X(historical,baseline),
                       np.asarray([r[target] for r in historical],dtype=float))
            score_fits[target][name]=frozen
    # Selection on validation doesn't license promotion or establish a
    # fresh holdout result: 2026 previously appeared in v1 historical tests.
    report={
        "status":"development_only",
        "model_version":MODEL_VERSION,"schema":VERSION,
        "training_through_season":2026,
        "training_games":len(train),"validation_games":len(valid),
        "matched_feature_count":len(FEATURE_COLUMNS),
        "matched_model_comparison":results,
        "score_projection_comparison":score_results,
        "bookmaker_lines_or_spreads_validated":False,
        "first_half_splits_available":False,
        "validation_2026_is_not_new_unseen_holdout":True,
        "true_prospective_2027_settled_games":0,
        "pass_to_public_model":False,"bookmaker_odds_present":False,
        "markets":["nba_moneyline_shadow_only"],
        "injuries_used_in_training":False,
        "research_only":True,
        "coverage":coverage,
    }
    target=root/"advanced"/"shadow_model.joblib"
    staged=target.with_name(target.name+".tmp")
    try:
        joblib.dump({
            "schema":VERSION,"model_version":MODEL_VERSION,
            "features":FEATURE_COLUMNS,
            "trained_through_season":2026,
            "candidate":fits["advanced_candidate"],
            "matched_v1":fits["matched_v1_features"],
            "score_models":score_fits,
            "report":report,"research_only":True,
        },staged)
        os.replace(staged,target)
    finally:
        if staged.exists():staged.unlink()
    return report


def _canonical(value)->str:
    return json.dumps(value,sort_keys=True,separators=(",",":"))


def run_shadow(home:Path|str,*,now:datetime|None=None)->dict:
    """Append-only shadow pregame JSON, with no writes to existing v1 ledger.

    New predictions are allowed only for the 2027 season with verified
    source freshness, valid upcoming tipoff and completed prior team stats.
    Settlement never uses new 2027 data as training examples.
    """
    instant=now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("A timezone-aware pregame clock is required")
    instant=instant.astimezone(timezone.utc)
    root=Path(home)
    target=root/"advanced"/"shadow_model.joblib"
    if not target.is_file():
        return {"status":"not_configured","created":0,"settled":0,
                "research_only":True}
    joblib,np,_,_,_=_deps()
    bundle=joblib.load(target)  # only locally produced trusted artifacts
    if (bundle.get("schema")!=VERSION or
        bundle.get("model_version")!=MODEL_VERSION or
        tuple(bundle.get("features",()))!=FEATURE_COLUMNS or
        bundle.get("trained_through_season")!=2026 or
        bundle.get("research_only") is not True):
        raise ValueError("Incompatible or untrusted shadow candidate model")
    # Source snapshot freshness gate also applies to independent shadow
    # predictions; no making first-time picks on an old fixture file.
    from basketball.research_readiness import build_readiness
    from basketball.research_data import read_games
    from basketball.research_readiness import _model_cutoff
    games=read_games(root/"nba_games.jsonl")
    model_exists,cutoff=_model_cutoff(root)
    readiness=build_readiness(games,now=instant,days_ahead=7,
                              model_exists=model_exists,
                              model_cutoff=cutoff)
    eligible={str(r["game_id"]) for r in readiness["fixtures"] if r["eligible"]}
    rows,coverage=from_home(root)
    ledger=root/"advanced"/"shadow_2027.jsonl"
    existing={}
    if ledger.is_file():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if not line:continue
            value=json.loads(line)
            data={k:v for k,v in value.items() if k not in ("sha256","settlement")}
            if hashlib.sha256(_canonical(data).encode()).hexdigest()!=value["sha256"]:
                raise ValueError("Immutable shadow record hash mismatch")
            game_id=str(value["game_id"])
            if game_id in existing:
                raise ValueError("Duplicate immutable shadow game")
            existing[game_id]=value
    by_game={str(g["game_id"]):g for g in games}
    # Deterministic append order; only current upcoming 2027 league games.
    new=[]
    for row in rows:
        gid=str(row["game_id"])
        game=by_game.get(gid)
        if (gid in existing or gid not in eligible or
            not game or game["season"]!=2027 or game["status"]!="scheduled"):
            continue
        kickoff=datetime.fromisoformat(game["start_utc"].replace("Z","+00:00"))
        if kickoff<=instant or kickoff>instant.replace(
            hour=0,minute=0,second=0,microsecond=0
        )+__import__("datetime").timedelta(days=3):
            continue
        x=np.asarray([row["features"]],dtype=float)
        prob=float(bundle["candidate"].predict_proba(x)[:,1][0])
        reference=float(bundle["matched_v1"].predict_proba(x[:,:14])[:,1][0])
        score_models=bundle.get("score_models") or {}
        def expected(target,variant):
            models=score_models.get(target) or {}
            m=models.get(variant)
            if m is None:return None
            features=x[:,:14] if variant=="matched_v1_features" else x
            return round(float(m.predict(features)[0]),3)
        item={
            "game_id":gid,"season":2027,"fixture_date":game["date"],
            "home_id":str(game["home_id"]),"away_id":str(game["away_id"]),
            "start_utc":game["start_utc"],"created_at":instant.isoformat(),
            "model_version":MODEL_VERSION,
            "candidate_home_win_probability":round(prob,5),
            "matched_v1_home_win_probability":round(reference,5),
            "source_feature_schema":VERSION,
            "candidate_total_points":expected("total_points","advanced_candidate"),
            "candidate_home_margin":expected("home_margin","advanced_candidate"),
            "matched_v1_total_points":expected("total_points","matched_v1_features"),
            "matched_v1_home_margin":expected("home_margin","matched_v1_features"),
            "bookmaker_odds_verified":False,"not_for_betting":True,
            "research_only":True,
        }
        digest=hashlib.sha256(_canonical(item).encode()).hexdigest()
        item["sha256"]=digest
        new.append(item)
    # Store immutable pregame records prior to any settlement processing.
    if new:
        ledger.parent.mkdir(parents=True,exist_ok=True)
        with ledger.open("a",encoding="utf-8") as stream:
            for item in new:
                stream.write(_canonical(item)+"\n")
    # Persist settlements separately to preserve original forecast hashes.
    results_path=root/"advanced"/"shadow_settlements_2027.json"
    settled=json.loads(results_path.read_text(encoding="utf-8")) if results_path.is_file() else {}
    changed=0
    for item in [*existing.values(),*new]:
        game=by_game.get(str(item["game_id"]))
        if not game or game["status"]!="final":
            continue
        if (str(game["home_id"])!=item["home_id"] or
            str(game["away_id"])!=item["away_id"] or
            game["date"]!=item["fixture_date"]):
            raise ValueError("Shadow final fixture identity mismatch")
        scores=[game["home_score"],game["away_score"]]
        if item["game_id"] in settled:
            if settled[item["game_id"]]["scores"]!=scores:
                raise ValueError("Shadow settlement changed verified score")
            continue
        settled[item["game_id"]]={
            "scores":scores,
            "source":game["source"],
            "verified_at":instant.isoformat(),
        }
        changed+=1
    if changed:
        stage=results_path.with_name(results_path.name+".tmp")
        try:
            stage.write_text(_canonical(settled)+"\n",encoding="utf-8")
            os.replace(stage,results_path)
        finally:
            if stage.exists():stage.unlink()
    # Report metrics only for genuine pre-tipoff entries recorded in the
    # shadow ledger; no backfilling completed games.
    original=list(existing.values())+new
    scored=[item for item in original if item["game_id"] in settled]
    info={"candidate":None,"matched_v1":None}
    if scored:
        y=[int(settled[item["game_id"]]["scores"][0]>
               settled[item["game_id"]]["scores"][1]) for item in scored]
        info={
            "candidate":_score(y,[r["candidate_home_win_probability"] for r in scored],np),
            "matched_v1":_score(y,[r["matched_v1_home_win_probability"] for r in scored],np),
        }
    score_errors={}
    for kind in ("candidate","matched_v1"):
        for target in ("total_points","home_margin"):
            estimates=[item for item in scored
                       if item.get(f"{kind}_{target}") is not None]
            if not estimates:
                score_errors[f"{kind}_{target}_mae"]=None
                continue
            actual=[
                sum(settled[item["game_id"]]["scores"])
                if target=="total_points" else
                settled[item["game_id"]]["scores"][0]-
                settled[item["game_id"]]["scores"][1]
                for item in estimates
            ]
            score_errors[f"{kind}_{target}_mae"]=round(
                sum(abs(item[f"{kind}_{target}"]-value)
                    for item,value in zip(estimates,actual))/len(estimates),4)
    return {
        "status":"research_only","created":len(new),
        "total_shadow_forecasts":len(original),
        "settled":len(scored),"newly_settled":changed,
        "performance":info,
        "point_projection_errors":score_errors,
        "minimum_descriptive_games":100,
        "sample_gate_met":len(scored)>=100,
        "first_2027_pregame_only":True,
        "public_publishing_enabled":False,
    }
