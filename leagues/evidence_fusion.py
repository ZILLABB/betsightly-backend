"""Builder-only fusion of replay and current live calibration evidence."""
from __future__ import annotations
import json, math
from functools import lru_cache
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent/"data"/"replay"
PROMOTED={"over_1_5","under_3_5","under_4_5","home_or_draw","away_or_draw","home_or_away","dnb_home","dnb_away"}
RESTRICTED={"btts_yes","btts_no","home_win","draw","away_win"}

@lru_cache(maxsize=1)
def _evidence():
    def load(name): return json.loads((ROOT/name).read_text())
    return load("market_summary.json"),load("calibration_buckets.json"),load("league_market_summary.json")

def _bucket(p):
    edges=((0,.5),(.5,.55),(.55,.6),(.6,.65),(.65,.7),(.7,.75),(.75,.8),(.8,.85),(.85,.9),(.9,1.00001))
    return next(f"{int(lo*100)}-{int(min(hi,1)*100)}" for lo,hi in edges if lo<=p<hi)

def _wilson_lower(rate,n,z=1.96):
    if not n:return 0.0
    den=1+z*z/n; centre=(rate+z*z/(2*n))/den
    return max(0.0,centre-z*math.sqrt(rate*(1-rate)/n+z*z/(4*n*n))/den)

def fused_market_evidence(market:str,probability:float,league:str|None,live:dict|None=None)->dict:
    summary,buckets,leagues=_evidence(); global_cell=summary.get(market) or {}
    bucket_cell=(buckets.get(market) or {}).get(_bucket(probability)) or {}
    league_key=" ".join(str(league or "").lower().split())
    league_cell=(leagues.get(market) or {}).get(league_key) or {}
    # Narrow evidence must earn use; otherwise fall through explicitly.
    if bucket_cell.get("n",0)>=500: cell,level=bucket_cell,"market_confidence_bucket"
    elif league_cell.get("n",0)>=500: cell,level=league_cell,"market_league"
    else: cell,level=global_cell,"market_global"
    hist_n=int(cell.get("n") or 0); hist_rate=float(cell.get("actual") or probability)
    hist_error=abs(float(cell.get("calibration_error") or 0))
    live=live or {}; live_n=int(live.get("n") or 0); live_rate=live.get("actual")
    # Historical replay acts as a reliability prior with 25 effective trials:
    # the pre-existing live evidence threshold. Millions of correlated,
    # bookmaker-anchored rows therefore cannot overwhelm current production.
    prior_n=25 if hist_n>=500 else min(25,hist_n)
    alpha=hist_rate*prior_n; beta=(1-hist_rate)*prior_n
    if live_n and live_rate is not None:
        alpha+=float(live_rate)*live_n; beta+=(1-float(live_rate))*live_n
    effective_n=alpha+beta; estimate=alpha/effective_n if effective_n else probability
    lower=_wilson_lower(estimate,effective_n)
    live_conflict=bool(live_n>=15 and live_rate is not None and abs(float(live_rate)-hist_rate)>.12)
    if market in RESTRICTED: state="SHADOW"
    elif market in PROMOTED and hist_n>=500 and hist_error<=.04 and not live_conflict: state="SUPPORTED"
    elif hist_n>=500 and hist_error<=.04: state="PROVISIONAL"
    else: state="REJECTED"
    adjusted=min(probability,estimate) if estimate<probability else probability+.25*(estimate-probability)
    if live_conflict: adjusted=min(adjusted,float(live_rate))
    return {"state":state,"hierarchy_level":level,"historical_n":hist_n,
            "recent_historical_n":global_cell.get("recent_2_seasons_n",0),
            "historical_reliability_estimate":round(hist_rate,4),"live_n":live_n,
            "live_reliability_estimate":live_rate,"live_conflict":live_conflict,
            "evidence_adjusted_probability":round(max(.01,min(.99,adjusted)),4),
            "lower_reliability_bound":round(lower,4),"replay_fidelity":global_cell.get("fidelity"),
            "historical_calibration_error":round(hist_error,4)}
