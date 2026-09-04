"""Leak-free replay of the current deterministic football probability path.

Generated evidence is deliberately not imported by ``leg_trust``. Phase 2A
measures; a later, explicit promotion phase may decide how to consume it.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import unicodedata
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import pandas as pd

from leagues.base_rates import GLOBAL_DEFAULTS, MIN_SAMPLE, SHRINKAGE_K
from leagues.predictor import predict

MARKETS = (
    "home_win", "draw", "away_win", "home_or_draw", "home_or_away",
    "away_or_draw", "dnb_home", "dnb_away", "over_1_5", "over_2_5",
    "over_3_5", "under_1_5", "under_2_5", "under_3_5", "under_4_5",
    "home_over_0_5", "away_over_0_5", "home_over_1_5",
    "away_over_1_5", "btts_yes", "btts_no",
)
BUCKETS = ((0, .5), (.5, .55), (.55, .6), (.6, .65), (.65, .7),
           (.7, .75), (.75, .8), (.8, .85), (.85, .9), (.9, 1.00001))


def normalize_identity(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    return " ".join("".join(c if c.isalnum() else " " for c in text
                            if not unicodedata.combining(c)).split())


def devig_1x2(home, draw, away) -> tuple[dict | None, float | None]:
    try:
        prices = [float(home), float(draw), float(away)]
    except (TypeError, ValueError):
        return None, None
    if any(not math.isfinite(x) or x <= 1 for x in prices):
        return None, None
    raw = [1 / x for x in prices]; overround = sum(raw)
    return dict(zip(("home_win", "draw", "away_win"),
                    (x / overround for x in raw))), overround


def devig_two_way(first, second) -> tuple[tuple[float, float] | None, float | None]:
    try:
        prices = [float(first), float(second)]
    except (TypeError, ValueError):
        return None, None
    if any(not math.isfinite(x) or x <= 1 for x in prices):
        return None, None
    raw = [1 / x for x in prices]; overround = sum(raw)
    return (raw[0] / overround, raw[1] / overround), overround


def settle_markets(home: int, away: int) -> dict[str, int | None]:
    total = home + away
    return {
        "home_win": int(home > away), "draw": int(home == away),
        "away_win": int(away > home), "home_or_draw": int(home >= away),
        "home_or_away": int(home != away), "away_or_draw": int(away >= home),
        "dnb_home": None if home == away else int(home > away),
        "dnb_away": None if home == away else int(away > home),
        "over_1_5": int(total >= 2), "over_2_5": int(total >= 3),
        "over_3_5": int(total >= 4), "under_1_5": int(total <= 1),
        "under_2_5": int(total <= 2), "under_3_5": int(total <= 3),
        "under_4_5": int(total <= 4), "home_over_0_5": int(home >= 1),
        "away_over_0_5": int(away >= 1), "home_over_1_5": int(home >= 2),
        "away_over_1_5": int(away >= 2),
        "btts_yes": int(home >= 1 and away >= 1),
        "btts_no": int(home == 0 or away == 0),
    }


def _quality(row: dict) -> tuple:
    return (int(row["source"] == "api_football"),
            int(row.get("odds_home") is not None) + int(row.get("odds_over25") is not None))


def load_and_deduplicate(api_path: Path, github_path: Path) -> tuple[list[dict], dict]:
    """Load both corpora and choose one deterministic record per certain identity."""
    rows, input_counts, rejected = [], {}, 0
    mappings = (
        ("api_football", api_path, {"home_team":"home", "away_team":"away", "date":"date",
         "home_score":"home_score", "away_score":"away_score", "league_name":"league",
         "season":"season", "avg_odds_home":"odds_home", "avg_odds_draw":"odds_draw",
         "avg_odds_away":"odds_away", "avg_odds_over25":"odds_over25",
         "avg_odds_under25":"odds_under25"}),
        ("github_football", github_path, {"HomeTeam":"home", "AwayTeam":"away", "MatchDate":"date",
         "FTHome":"home_score", "FTAway":"away_score", "Division":"league",
         "OddHome":"odds_home", "OddDraw":"odds_draw", "OddAway":"odds_away",
         "Over25":"odds_over25", "Under25":"odds_under25"}),
    )
    for source, path, mapping in mappings:
        frame = pd.read_csv(path, usecols=lambda c: c in mapping, low_memory=False).rename(columns=mapping)
        input_counts[source] = len(frame)
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        for index, value in frame.iterrows():
            try:
                if pd.isna(value["date"]) or pd.isna(value["home"]) or pd.isna(value["away"]): raise ValueError
                hs, aw = int(value["home_score"]), int(value["away_score"])
            except (ValueError, TypeError):
                rejected += 1; continue
            row = {key: (None if pd.isna(item) else item) for key, item in value.to_dict().items()}
            row.update(source=source, source_row_id=int(index), home_score=hs, away_score=aw)
            row["season"] = str(row.get("season") or (row["date"].year if row["date"].month >= 8 else row["date"].year-1))
            # Teams + date + final score are stronger cross-provider identity
            # than provider competition text ("E0" vs "Premier League").
            # A home/away pair cannot play two genuine fixtures on one date;
            # preserving both provenance rows makes this merge auditable.
            row["identity"] = "|".join((normalize_identity(row["home"]), normalize_identity(row["away"]),
                row["date"].date().isoformat(), str(hs), str(aw)))
            rows.append(row)
    chosen, provenance, duplicates, merged = {}, defaultdict(list), 0, 0
    potential = defaultdict(set)
    for row in rows:
        potential["|".join((normalize_identity(row["home"]), normalize_identity(row["away"]),
                  row["date"].date().isoformat(), str(row["home_score"]), str(row["away_score"])))].add(row["source"])
        key = row["identity"]; provenance[key].append({"source":row["source"], "source_row_id":row["source_row_id"]})
        if key not in chosen: chosen[key] = row; continue
        duplicates += 1
        winner, loser = (row, chosen[key]) if _quality(row) > _quality(chosen[key]) else (chosen[key], row)
        for field in ("odds_home","odds_draw","odds_away","odds_over25","odds_under25"):
            if winner.get(field) is None and loser.get(field) is not None: winner[field] = loser[field]; merged += 1
        chosen[key] = winner
    result = []
    for key, row in chosen.items():
        row["provenance"] = provenance[key]; result.append(row)
    result.sort(key=lambda r: (r["date"], r["identity"]))
    return result, {"source_rows": input_counts, "duplicates_detected": duplicates,
                    "potential_cross_source_duplicates": sum(len(v)>1 for v in potential.values()),
                    "fields_merged": merged, "records_rejected": rejected,
                    "unique_matches": len(result),
                    "date_range": [result[0]["date"].date().isoformat(), result[-1]["date"].date().isoformat()],
                    "leagues": len({normalize_identity(r.get("league") or "") for r in result})}


def _empty_score(): return {"n":0,"goals":0,"home_goals":0,"away_goals":0,"o15":0,"o25":0,"home":0,"draw":0,"away":0,"btts":0}
def _add(s, h, a):
    s["n"]+=1; s["goals"]+=h+a; s["home_goals"]+=h; s["away_goals"]+=a
    s["o15"]+=h+a>=2; s["o25"]+=h+a>=3; s["home"]+=h>a; s["draw"]+=h==a; s["away"]+=a>h; s["btts"]+=h>0 and a>0
def _rates(items):
    s=_empty_score()
    for _,h,a in items: _add(s,h,a)
    if s["n"] < MIN_SAMPLE: return dict(GLOBAL_DEFAULTS)
    n=s["n"]; w=n/(n+SHRINKAGE_K)
    raw={"matches":n,"avg_goals":s["goals"]/n,"over_1_5":s["o15"]/n,"over_2_5":s["o25"]/n,
         "home_win":s["home"]/n,"draw":s["draw"]/n,"away_win":s["away"]/n,"btts":s["btts"]/n,
         "home_goals":s["home_goals"]/n,"away_goals":s["away_goals"]/n}
    return {k:(n if k=="matches" else w*raw[k]+(1-w)*GLOBAL_DEFAULTS[k]) for k in raw}


@dataclass
class Agg:
    n:int=0; pred:float=0; actual:float=0; brier:float=0; logloss:float=0; bookmaker_brier:float=0; bookmaker_n:int=0; overround:float=0; market_replay_n:int=0; derived_replay_n:int=0
    def add(self,p,y,bp=None,ov=None,fidelity=None):
        self.n+=1; self.pred+=p; self.actual+=y; self.brier+=(p-y)**2
        self.market_replay_n += fidelity == "MARKET_REPLAY"
        self.derived_replay_n += fidelity == "DERIVED_REPLAY"
        self.logloss+=-(y*math.log(max(p,1e-12))+(1-y)*math.log(max(1-p,1e-12)))
        if bp is not None: self.bookmaker_n+=1; self.bookmaker_brier+=(bp-y)**2; self.overround+=ov or 0
    def value(self):
        if not self.n:return {"n":0}
        rate=self.actual/self.n; base=rate*(1-rate)
        z=1.96; denom=1+z*z/self.n; centre=(rate+z*z/(2*self.n))/denom; half=z*math.sqrt(rate*(1-rate)/self.n+z*z/(4*self.n*self.n))/denom
        return {"n":self.n,"predicted":round(self.pred/self.n,4),"actual":round(rate,4),
                "calibration_error":round(self.pred/self.n-rate,4),"brier":round(self.brier/self.n,4),
                "log_loss":round(self.logloss/self.n,4),"base_rate":round(rate,4),
                "skill_vs_base_rate":round(1-self.brier/self.n/base,4) if base else None,
                "bookmaker_n":self.bookmaker_n,"bookmaker_brier":round(self.bookmaker_brier/self.bookmaker_n,4) if self.bookmaker_n else None,
                "skill_vs_bookmaker":round(1-(self.brier/self.n)/(self.bookmaker_brier/self.bookmaker_n),4) if self.bookmaker_n and self.bookmaker_brier else None,
                "mean_bookmaker_overround":round(self.overround/self.bookmaker_n,4) if self.bookmaker_n else None,
                "full_replay_sample_size":0,"market_replay_sample_size":self.market_replay_n,
                "derived_replay_sample_size":self.derived_replay_n,
                "actual_95pct_ci":[round(max(0,centre-half),4),round(min(1,centre+half),4)]}


def replay(rows: list[dict], max_matches: int | None = None) -> dict:
    """Chronological replay; an entire date is scored before entering state."""
    started=time.perf_counter(); history=defaultdict(int); h2h=defaultdict(int)
    leagues=defaultdict(deque); global_history=deque(); summary=defaultdict(Agg); buckets=defaultdict(lambda:defaultdict(Agg)); by_league=defaultdict(lambda:defaultdict(Agg)); by_season=defaultdict(lambda:defaultdict(Agg)); fidelity=Counter(); fallbacks=0; predictions=0
    rows=rows[:max_matches] if max_matches else rows; i=0
    while i<len(rows):
        date=rows[i]["date"]; j=i
        while j<len(rows) and rows[j]["date"]==date:j+=1
        cutoff=date-timedelta(days=45)
        while global_history and global_history[0][0]<cutoff:global_history.popleft()
        for row in rows[i:j]:
            league=normalize_identity(row.get("league") or "unknown")
            while leagues[league] and leagues[league][0][0]<cutoff:leagues[league].popleft()
            one,ov1=devig_1x2(row.get("odds_home"),row.get("odds_draw"),row.get("odds_away")); two,ov2=devig_two_way(row.get("odds_over25"),row.get("odds_under25"))
            if one and two:f="MARKET_REPLAY"
            elif one:f="DERIVED_REPLAY"
            else:f="INSUFFICIENT"
            fidelity[f]+=1
            if f=="INSUFFICIENT":continue
            base=_rates(leagues[league]) if len(leagues[league])>=MIN_SAMPLE else _rates(global_history); fallbacks+=len(leagues[league])<MIN_SAMPLE
            odds={"implied":one,"implied_over":two[0] if two else None,"implied_under":two[1] if two else None,"ou_line":2.5}
            result=predict({"odds":odds},base,elo_probs=None); outcomes=settle_markets(row["home_score"],row["away_score"]); predictions+=1
            for market,p in result["probabilities"].items():
                y=outcomes[market]
                if y is None:continue
                bp=(one or {}).get(market)
                if market=="over_2_5" and two:bp=two[0]
                if market=="under_2_5" and two:bp=two[1]
                ov=ov1 if market in ("home_win","draw","away_win") else ov2
                summary[market].add(p,y,bp,ov,f); by_league[market][league].add(p,y,fidelity=f); by_season[market][row["season"]].add(p,y,fidelity=f)
                label=next(f"{int(lo*100)}-{int(min(hi,1)*100)}" for lo,hi in BUCKETS if lo<=p<hi); buckets[market][label].add(p,y,fidelity=f)
        for row in rows[i:j]:
            league=normalize_identity(row.get("league") or "unknown"); item=(date,row["home_score"],row["away_score"]); leagues[league].append(item); global_history.append(item)
            history[normalize_identity(row["home"])]+=1; history[normalize_identity(row["away"])]+=1
        i=j
    market_summary={}
    for m in MARKETS:
        value=summary[m].value(); cells=[a for a in buckets[m].values() if a.n]
        value["ece"] = round(sum(a.n*abs(a.pred/a.n-a.actual/a.n) for a in cells)/summary[m].n,4) if summary[m].n else None
        value["mce"] = round(max((abs(a.pred/a.n-a.actual/a.n) for a in cells),default=0),4)
        seasons=sorted(by_season[m])
        value["recent_2_seasons_n"] = sum(by_season[m][s].n for s in seasons[-2:])
        value.update(fidelity="MARKET_REPLAY+DERIVED_REPLAY",recommended_state=_state(summary[m]))
        market_summary[m]=value
    return {"market_summary":market_summary,"calibration_buckets":{m:{b:a.value() for b,a in v.items()} for m,v in buckets.items()},
            "league_market_summary":{m:{l:a.value() for l,a in v.items()} for m,v in by_league.items()},
            "season_market_summary":{m:{s:a.value() for s,a in v.items()} for m,v in by_season.items()},
            "run":{"matches_considered":len(rows),"predictions_generated":predictions,"outcomes_evaluated":sum(a.n for a in summary.values()),"fidelity_counts":dict(fidelity),"history_fallbacks":fallbacks,"runtime_seconds":round(time.perf_counter()-started,2)}}

def _state(a:Agg)->str:
    if a.n<500:return "SHADOW"
    error=abs(a.pred/a.n-a.actual/a.n); skill=a.value().get("skill_vs_base_rate")
    # No row can be FULL_REPLAY until historical ELO/ML state exists. Phase 2A
    # therefore cannot recommend production promotion on its own.
    if error<=.03 and skill is not None and skill>0:return "PROVISIONAL"
    if error<=.06:return "PROVISIONAL"
    return "REJECTED"

def write_artifacts(result:dict, dedup:dict, output:Path, sources:dict):
    output.mkdir(parents=True,exist_ok=True)
    for key in ("market_summary","calibration_buckets","league_market_summary","season_market_summary"):
        (output/f"{key}.json").write_text(json.dumps(result[key],indent=2,sort_keys=True))
    recency={}
    for market,seasons in result["season_market_summary"].items():
        ordered=sorted(seasons)
        recency[market]={
            "all":_combine_summaries(seasons.values()),
            "last_5_seasons":_combine_summaries(seasons[s] for s in ordered[-5:]),
            "last_3_seasons":_combine_summaries(seasons[s] for s in ordered[-3:]),
            "last_2_seasons":_combine_summaries(seasons[s] for s in ordered[-2:]),
            "latest_complete_season":_combine_summaries([seasons[ordered[-2]]]) if len(ordered)>1 else {},
        }
    (output/"recency_market_summary.json").write_text(json.dumps(recency,indent=2,sort_keys=True))
    metadata={**dedup,**result["run"],"sources":sources,"markets_evaluated":list(MARKETS),
              "anti_leakage":{"strictly_before_fixture":True,"same_day_grouping":True,"league_window_days":45,"elo_used":False,"ml_used":False},
              "code_revision":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16],"generated_at":pd.Timestamp.utcnow().isoformat()}
    (output/"replay_metadata.json").write_text(json.dumps(metadata,indent=2,sort_keys=True))

def _combine_summaries(values):
    values=[v for v in values if v.get("n")]
    n=sum(v["n"] for v in values)
    if not n:return {"n":0}
    keys=("predicted","actual","calibration_error","brier","log_loss")
    return {"n":n,**{key:round(sum(v[key]*v["n"] for v in values)/n,4) for key in keys}}
