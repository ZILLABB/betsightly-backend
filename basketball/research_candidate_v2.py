"""Independent offline comparison of locked v1 and experimental NBA v2.

Both models use the identical chronological train/validation/test game IDs.
Regularization is selected from validation ONLY. Test results are inspected
once for descriptive research and CANNOT promote a live model or publish odds.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

from basketball.research_features import FEATURE_COLUMNS as V1_COLUMNS, make_rows
from basketball.research_features_v2 import (
    FEATURE_COLUMNS as V2_COLUMNS, VERSION as V2_SCHEMA, make_rows_v2,
)
from basketball.research_model import chronological_split

CANDIDATE_VERSION = "nba-moneyline-candidate-v2-research"
REVIEW_MIN_TEST = 500
MIN_BRIER_IMPROVEMENT = 0.003


def _depend():
    import numpy as np
    from sklearn.linear_model import LogisticRegression, Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return np, LogisticRegression, Ridge, make_pipeline, StandardScaler


def _metrics(y, p, np) -> dict:
    eps = 1e-12
    p = np.clip(np.asarray(p,dtype=float),eps,1-eps)
    y = np.asarray(y,dtype=float)
    if len(y)==0 or not np.isfinite(p).all():
        raise ValueError("A real labeled holdout is required")
    return {
        "games": int(len(y)),
        "accuracy": round(float(np.mean((p>=.5)==y)),5),
        "brier": round(float(np.mean((p-y)**2)),6),
        "log_loss": round(float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p))),6),
        "home_win_rate": round(float(np.mean(y)),5),
    }


def _score(y, predicted, np) -> dict:
    difference = np.asarray(predicted,dtype=float)-np.asarray(y,dtype=float)
    return {
        "mae": round(float(np.mean(np.abs(difference))),5),
        "rmse": round(float(np.sqrt(np.mean(difference**2))),5),
        "bias": round(float(np.mean(difference)),5),
    }


def _fit_classifier(rows, held, np, LogisticRegression, pipeline, scaler):
    train, validation, test = rows
    to_x = lambda records: np.asarray([r["features"] for r in records],dtype=float)
    to_y = lambda records: np.asarray([r["home_win"] for r in records],dtype=int)
    x_train, y_train = to_x(train), to_y(train)
    x_val, y_val = to_x(validation), to_y(validation)
    x_test, y_test = to_x(test), to_y(test)
    choices=[]
    for c in (.03,.1,.3,1.):
        model=pipeline(scaler(),LogisticRegression(
            C=c, max_iter=1000,solver="lbfgs",random_state=42))
        model.fit(x_train,y_train)
        val_prob=model.predict_proba(x_val)[:,1]
        choices.append((float(np.mean((val_prob-y_val)**2)),c,model))
    _, c, chosen=min(choices,key=lambda item:(item[0],item[1]))
    return {
        "selected_C":c,
        "validation":_metrics(y_val,chosen.predict_proba(x_val)[:,1],np),
        "test":_metrics(y_test,chosen.predict_proba(x_test)[:,1],np),
        "test_probabilities":chosen.predict_proba(x_test)[:,1],
    }


def _fit_score_targets(train, val, test, np, Ridge, pipeline, scaler):
    x = lambda rows:np.asarray([r["features"] for r in rows],dtype=float)
    outputs={}
    for target in ("total_points","home_margin"):
        y=lambda rows:np.asarray([r[target] for r in rows],dtype=float)
        options=[]
        for alpha in (.1,1.,10.,100.):
            model=pipeline(scaler(),Ridge(alpha=alpha))
            model.fit(x(train),y(train))
            options.append((float(np.mean(np.abs(
                model.predict(x(val))-y(val)))),alpha,model))
        _, alpha, winner=min(options,key=lambda o:(o[0],o[1]))
        outputs[target]={
            "selected_alpha":alpha,
            "validation":_score(y(val),winner.predict(x(val)),np),
            "test":_score(y(test),winner.predict(x(test)),np),
        }
    return outputs


def compare_on_real_finals(games:list[dict]) -> dict:
    """Run matched-cohort comparison; does NOT write artifacts or refit v1."""
    v1=make_rows(games)
    v2=make_rows_v2(games)
    if len(v1)!=len(v2):
        raise ValueError("Baseline/candidate cohort mismatch")
    train, val, test=chronological_split(v1)
    by_id={str(r["game_id"]):r for r in v2}
    def match(records):
        subset=[by_id[str(row["game_id"])] for row in records]
        for old, new in zip(records,subset):
            if (old["date"],old.get("home_win")) != (new["date"],new.get("home_win")):
                raise ValueError("Baseline/candidate outcome or date mismatch")
        return subset
    train2,val2,test2=tuple(map(match,(train,val,test)))
    np, LogisticRegression, Ridge, pipeline, scaler=_depend()
    incumbent=_fit_classifier((train,val,test), None,np,LogisticRegression,pipeline,scaler)
    candidate=_fit_classifier((train2,val2,test2), None,np,LogisticRegression,pipeline,scaler)
    test_y=np.asarray([r["home_win"] for r in test],dtype=float)
    incumbent_prob=incumbent.pop("test_probabilities")
    candidate_prob=candidate.pop("test_probabilities")
    paired=(candidate_prob-test_y)**2-(incumbent_prob-test_y)**2
    improvement=float(-np.mean(paired))
    # Segment diagnostics, not a new fitting or tuning step.
    by_season={}
    for year in sorted({r["season"] for r in test}):
        indices=[i for i,r in enumerate(test) if r["season"]==year]
        if indices:
            by_season[str(year)]={
                "games":len(indices),
                "v1_brier":_metrics(test_y[indices],incumbent_prob[indices],np)["brier"],
                "candidate_brier":_metrics(test_y[indices],candidate_prob[indices],np)["brier"],
            }
    minimum_met=len(test)>=REVIEW_MIN_TEST
    suggested=bool(
        minimum_met and improvement>=MIN_BRIER_IMPROVEMENT and
        candidate["test"]["log_loss"]<=incumbent["test"]["log_loss"] and
        candidate["test"]["accuracy"]>=incumbent["test"]["accuracy"]-.01)
    score_v1=_fit_score_targets(train,val,test,np,Ridge,pipeline,scaler)
    score_v2=_fit_score_targets(train2,val2,test2,np,Ridge,pipeline,scaler)
    digest=hashlib.sha256(json.dumps([
        (g["game_id"],g["date"],g["status"],g["home_score"],g["away_score"])
        for g in sorted(games,key=lambda g:(g["date"],str(g["game_id"])))
    ],separators=(",",":"),default=str).encode()).hexdigest()
    return {
        "status":"completed", "phase":"stage_3a_experimental_candidate",
        "research_only":True,
        "promoted_to_live":False,
        "published":False,
        "prospective_predictions_created":0,
        "candidate_version":CANDIDATE_VERSION,
        "candidate_schema":V2_SCHEMA,
        "v1_feature_count":len(V1_COLUMNS),
        "candidate_feature_count":len(V2_COLUMNS),
        "training_games":len(train),
        "validation_games":len(val),
        "untouched_test_games":len(test),
        "test_period":{"from":test[0]["date"],"through":test[-1]["date"]},
        "source_hash":digest,
        "incumbent_moneyline":incumbent,
        "candidate_moneyline":candidate,
        "paired_test_brier_improvement":round(improvement,6),
        "test_season_segments":by_season,
        "score_targets":{
            "incumbent":score_v1,
            "candidate":score_v2,
        },
        "review_gate":{
            "min_test_games":REVIEW_MIN_TEST,
            "required_brier_improvement":MIN_BRIER_IMPROVEMENT,
            "sample_sufficient":minimum_met,
            "passes_descriptive_research_gate":suggested,
            "live_model_promotion_allowed":False,
            "note":"Even passing this gate cannot replace the immutable v1 model or claim a betting edge. Prospectively evaluate a frozen candidate separately.",
        },
        "not_measured":{
            "possessions_pace":True,
            "offensive_defensive_rating":True,
            "injuries":True,
            "travel_distance":True,
            "odds_or_bookmaker_roi":True,
        },
        "commercial_use_review_required":True,
    }


def write_candidate_report(games:list[dict], path:str|Path)->dict:
    """Write only metrics; no model pickle, inputs, betting odds or selections."""
    result=compare_on_real_finals(games)
    dest=Path(path)
    dest.parent.mkdir(parents=True,exist_ok=True)
    stage=dest.with_name(dest.name+".tmp")
    try:
        stage.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,dest)
    finally:
        if stage.exists(): stage.unlink()
    return result
