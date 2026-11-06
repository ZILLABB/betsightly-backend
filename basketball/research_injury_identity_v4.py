"""Stage 4A: injury-to-ESPN athlete identity diagnostics, no fuzzy joins.

The NBA official injury PDF may contain only submitted teams and is not a
full roster source. This crosswalk never guesses team/player identities,
never annotates old matches, and remains DISABLED for model features until
complete source and submission coverage are independently proven.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path

from basketball.research_data import read_games


def _canonical(name:str)->str:
    # Deterministic re-order is allowed only for a single comma in the
    # NBA's 'Surname, Given Names' notation. Never fuzzy/cross-language.
    name=" ".join(str(name).split())
    if name.count(",")==1:
        family,given=(part.strip() for part in name.split(","))
        if family and given:name=f"{given} {family}"
    return name.casefold()


def injury_crosswalk(home:str|Path,*,as_of:datetime|None=None)->dict:
    root=Path(home)
    when=as_of or datetime.now(timezone.utc)
    if when.tzinfo is None:raise ValueError("Injury crosswalk clock needs timezone")
    when=when.astimezone(timezone.utc)
    folder=root/"injuries"
    season=2027
    source=root/"advanced"/f"player_{season}.json"
    blocked={
        "status":"blocked","research_only":True,
        "eligible_for_model_features":False,
        "player_injury_feature_enabled":False,
        "report_completeness_verified":False,
        "unresolved_injury_rows":None,
        "matched_unique_player_rows":0,
    }
    if not source.is_file():
        return {**blocked,"reason":"no_verified_current_season_player_data"}
    manifests=sorted(folder.glob("*.json"),reverse=True)
    if not manifests:
        return {**blocked,"reason":"no_official_injury_snapshot"}
    snapshots=[]
    for path in manifests:
        try:
            report=json.loads(path.read_text(encoding="utf-8"))
            if report.get("source")!="nba:official_injury_report_pdf:v1":
                continue
            published=datetime.fromisoformat(report["published_at"])
            fetched=datetime.fromisoformat(report["downloaded_at"])
            if not all(t.tzinfo is not None for t in (published,fetched)):
                continue
            if published<=when and fetched<=when:
                snapshots.append(report)
        except (OSError,ValueError,KeyError,TypeError):
            continue
    if not snapshots:
        return {**blocked,"reason":"no_snapshot_actually_collected_by_cutoff"}
    recent=max(snapshots,key=lambda r:r["published_at"])
    retrieved=datetime.fromisoformat(recent["downloaded_at"])
    age=(when-retrieved.astimezone(timezone.utc)).total_seconds()/3600
    if age<0 or age>12:
        return {**blocked,"reason":"injury_snapshot_stale",
                "snapshot_age_hours":round(age,2)}
    try:
        players=json.loads(source.read_text(encoding="utf-8"))
        games=read_games(root/"nba_games.jsonl")
        if not isinstance(players,list):raise ValueError("Player list missing")
        # ESPN team ID -> NBA franchise display name, only when same team
        # ID consistently has exactly one known canonical full name.
        teams=defaultdict(set)
        for game in games:
            if game["season"]!=season:continue
            teams[str(game["home_id"])].add(game["home_name"])
            teams[str(game["away_id"])].add(game["away_name"])
        verified_names={
            tid:next(iter(names)) for tid,names in teams.items()
            if len(names)==1
        }
        # A given player name+club must identify exactly one athlete ID.
        athletes=defaultdict(set)
        for p in players:
            team=str(p["team_id"])
            if team not in verified_names:continue
            athletes[(verified_names[team].casefold(),_canonical(p["name"]))].add(
                str(p["athlete_id"]))
        recognized=ambiguous=unknown=0
        statuses={}
        for row in recent.get("parsed_player_rows") or []:
            name=_canonical(row.get("player",""))
            club=str(row.get("team","")).casefold().strip()
            ids=athletes.get((club,name),set())
            if len(ids)==1:
                recognized+=1
                ident=next(iter(ids))
                # Only one report status per uniquely recognized player.
                if ident in statuses:
                    raise ValueError("Duplicate injury-report player identity")
                statuses[ident]=row["status"]
            elif len(ids)>1:ambiguous+=1
            else:unknown+=1
    except (OSError,ValueError,KeyError,TypeError) as exc:
        return {**blocked,"reason":"untrusted_player_or_source_identity"}
    return {
        **blocked,
        "status":"research_only",
        "reason":"incomplete_team_submission_and_injury_semantics",
        "matched_unique_player_rows":recognized,
        "ambiguous_player_rows":ambiguous,
        "unresolved_injury_rows":unknown,
        "recognized_distinct_player_ids":recognized,
        "official_snapshot_published_at":recent["published_at"],
        "official_snapshot_downloaded_at":recent["downloaded_at"],
        "snapshot_age_hours":round(age,2),
        "source":"verified_exact_2027_espn_team_name_and_athlete_id",
        "unused_diagnostic_status_counts":{
            status:sum(value==status for value in statuses.values())
            for status in sorted(set(statuses.values()))
        },
        "note":"No injures-as-absence, expected minutes, roster completeness "
               "or forward game injury feature may be inferred.",
        "commercial_use_review_required":True,
    }
