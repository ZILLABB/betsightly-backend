"""Write safe diagnostics for current ESPN fixtures that do not match SportyBet."""
import json, sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from leagues import sportybet
from leagues.engine import run_pipeline

def similarity(a,b): return SequenceMatcher(None,sportybet._norm(a),sportybet._norm(b)).ratio()

board=sportybet.fetch_board(); _,fixtures=run_pipeline(days_ahead=7)
entries=[e for _,e in sportybet._board_entries(board)]; counts=Counter(); aliases=[]
for fixture in fixtures:
    match=fixture.get("_sportybet_match") or {}
    if match.get("status")=="MATCHED":
        counts["matched"]+=1
        if match.get("league_diagnostic"): counts["competition_mismatch"]+=1
        continue
    status=match.get("status")
    if status=="KICKOFF_MISMATCH": counts["kickoff_mismatch"]+=1; continue
    names=(fixture["home"]["name"]+" "+fixture["away"]["name"]).lower()
    if any(x in names for x in (" u19"," u20"," u21"," u23","reserve"," ii")):
        counts["youth_reserve_mismatch"]+=1; continue
    timed=[]
    for entry in entries:
        delta=sportybet._kickoff_delta_minutes(entry,fixture.get("commence_time", ""))
        if delta is None or delta>sportybet.KICKOFF_TOLERANCE_MINUTES: continue
        score=(similarity(fixture["home"]["name"],entry.get("home",""))+
               similarity(fixture["away"]["name"],entry.get("away","")))/2
        if score>=.65: timed.append((score,entry,delta))
    timed.sort(key=lambda x:x[0],reverse=True)
    if not timed: counts["missing_from_sportybet"]+=1; continue
    top=timed[0]
    if len(timed)>1 and top[0]-timed[1][0]<.03: category="ambiguous"
    elif top[0]>=.78: category="alias_candidate"
    else: category="team_name_mismatch"
    counts[category]+=1
    if category=="alias_candidate":
        aliases.append({"espn_home":fixture["home"]["name"],"espn_away":fixture["away"]["name"],
                        "sportybet_home":top[1].get("home"),"sportybet_away":top[1].get("away"),
                        "league":fixture.get("league"),"sportybet_competition":top[1].get("competition"),
                        "kickoff_delta_minutes":round(top[2],1),"name_score":round(top[0],3)})
output={"snapshot":sportybet.board_metadata(board),"espn_total":len(fixtures),"counts":dict(counts),
        "safe_alias_candidates":sorted(aliases,key=lambda x:x["name_score"],reverse=True)}
(ROOT/"data/replay/current_coverage.json").write_text(json.dumps(output,indent=2))
print(json.dumps({"espn_total":len(fixtures),"counts":counts,"alias_candidates":len(aliases)},default=dict,indent=2))
