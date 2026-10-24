"""NBA Stage 3B: bounded, source-verified ESPN team/player box score ingestion.

No external paid service or basketball model mutation. Dataset release asset
schemas: https://py.sportsdataverse.org/docs/nba/reference/loaders/team
and https://py.sportsdataverse.org/docs/nba/reference/loaders/player
Only *exact ESPN fixture/team IDs* can be joined; no fuzzy matching.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from basketball.research_data import read_games

RELEASE = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download"
ASSETS = {
    "team": ("espn_nba_team_boxscores", "team_box_{season}.parquet"),
    "player": ("espn_nba_player_boxscores", "player_box_{season}.parquet"),
}
TEAM_REQUIRED = frozenset({
    "game_id","season","season_type","team_id","opponent_team_id",
    "team_score","field_goals_attempted","free_throws_attempted",
    "offensive_rebounds","total_turnovers","field_goals_made",
    "three_point_field_goals_made","three_point_field_goals_attempted",
})
PLAYER_REQUIRED = frozenset({
    "game_id","season","season_type","team_id","athlete_id",
    "athlete_display_name","minutes","points","did_not_play",
})
MAX_BYTES = 40_000_000
MAX_ROWS = {"team": 3000, "player": 50000}
MIN_TEAM_COMPLETE_COVERAGE = 0.85
PROVENANCE = "sportsdataverse:espn_nba_boxscores:v1"


def _read_parquet(content: bytes, fields: frozenset) -> list[dict]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("Advanced NBA box scores require python -m pip install pyarrow") from exc
    parquet = pq.ParquetFile(io.BytesIO(content))
    columns = set(parquet.schema.names)
    if not fields.issubset(columns):
        raise ValueError("NBA box-score release missing required columns: " +
                         ",".join(sorted(fields-columns)))
    if parquet.metadata.num_rows <= 0:
        raise ValueError("Empty NBA source parquet file")
    return parquet.read(columns=sorted(fields)).to_pylist()


def _get(url: str, *, opener=urlopen) -> bytes:
    req = Request(url, headers={
        "User-Agent": "BetSightlyPrivateNBAResearch/1.0",
        "Accept": "application/octet-stream",
    })
    try:
        with opener(req, timeout=60) as response:
            declared=int(response.headers.get("Content-Length") or 0)
            if declared > MAX_BYTES:
                raise ValueError("NBA box-score asset exceeds size limit")
            content=response.read(MAX_BYTES+1)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError("NBA box-score release temporarily unavailable") from exc
    if len(content)>MAX_BYTES or len(content)<100:
        raise ValueError("Incomplete or oversized NBA box-score download")
    return content


def _num(value, *, name: str, allow_none: bool=False, maximum:float=1000):
    if allow_none and value is None:
        return None
    if isinstance(value,bool) or value is None:
        raise ValueError("Invalid NBA box score "+name)
    numeric=float(value)
    if not math.isfinite(numeric) or not 0 <= numeric <= maximum:
        raise ValueError("Invalid NBA box score "+name)
    return numeric


def _ident(value, name):
    s=str(value or "").strip()
    if not s.isdecimal() or int(s)<=0:
        raise ValueError("Invalid NBA "+name+" ID")
    return str(int(s))


def normalize_team(row:dict, *, season:int)->dict|None:
    if int(row["season"])!=season:
        raise ValueError("NBA box-score season mismatch")
    if int(row["season_type"])!=2:
        return None
    fga=_num(row["field_goals_attempted"],name="FGA")
    fta=_num(row["free_throws_attempted"],name="FTA")
    orb=_num(row["offensive_rebounds"],name="ORB")
    tov=_num(row["total_turnovers"],name="TOV")
    score=_num(row["team_score"],name="score")
    fgm=_num(row["field_goals_made"],name="FGM")
    tpm=_num(row["three_point_field_goals_made"],name="3PM")
    tpa=_num(row["three_point_field_goals_attempted"],name="3PA")
    if orb>fga or fgm>fga or tpm>tpa or tpm>fgm or tpa>fga:
        raise ValueError("Impossible NBA team shooting or rebounding statistics")
    possessions=fga-orb+tov+0.44*fta  # estimated, not official observed pace
    if not 30 <= possessions <= 180:
        raise ValueError("Unreasonable NBA possessions estimate")
    return {
        "game_id":_ident(row["game_id"],"game"),"season":season,
        "team_id":_ident(row["team_id"],"team"),
        "opponent_team_id":_ident(row["opponent_team_id"],"opponent"),
        "score":int(score),"estimated_possessions":round(possessions,3),
        "estimated_offensive_rating":round(100*score/possessions,4),
        "e_fg":round((fgm+0.5*tpm)/fga,5) if fga>0 else None,
        "three_rate":round(tpa/fga,5) if fga>0 else None,
        "free_throw_rate":round(fta/fga,5) if fga>0 else None,
        "turnovers":tov,"offensive_rebounds":orb,
    }


def normalize_player(row:dict, *, season:int)->dict|None:
    if int(row["season"])!=season:
        raise ValueError("NBA player-box season mismatch")
    if int(row["season_type"])!=2:
        return None
    ident=_ident(row["athlete_id"],"athlete")
    team=_ident(row["team_id"],"team")
    dnp=row["did_not_play"]
    if dnp not in (True,False,None):
        raise ValueError("Invalid DNP flag")
    minutes=_num(row["minutes"],name="minutes",allow_none=True,maximum=70)
    points=_num(row["points"],name="points",allow_none=True,maximum=150)
    if dnp is True:
        if minutes not in (None,0):
            raise ValueError("DNP NBA player cannot record minutes")
        minutes=0.0
        points=0.0
    if minutes is None or points is None:
        return None  # no invented minutes for incomplete match records
    name=str(row["athlete_display_name"] or "").strip()
    if not name:
        raise ValueError("Missing NBA athlete name")
    return {
        "game_id":_ident(row["game_id"],"game"),"season":season,
        "team_id":team,"athlete_id":ident,"name":name[:120],
        "minutes":round(minutes,3),"points":int(points),
        "did_not_play":bool(dnp),
    }


def _atomic_json(path:Path, data:object)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    try:
        tmp.write_text(json.dumps(data,sort_keys=True,separators=(",",":"))+"\n",encoding="utf-8")
        os.replace(tmp,path)
    finally:
        if tmp.exists():tmp.unlink()


def _process(*, kind:str, season:int, fixtures:dict, loader=None,
             opener=urlopen)->tuple[list[dict],dict]:
    if kind not in ASSETS:raise ValueError("Unsupported NBA box-score dataset")
    if not 2017<=season<=2030:raise ValueError("Unsupported box-score season")
    tag, pattern=ASSETS[kind]
    url=f"{RELEASE}/{tag}/{pattern.format(season=season)}"
    raw=_get(url,opener=opener)
    sha=hashlib.sha256(raw).hexdigest()
    data=(loader or _read_parquet)(raw, TEAM_REQUIRED if kind=="team" else PLAYER_REQUIRED)
    if len(data)>MAX_ROWS[kind] or not data:
        raise ValueError("NBA box-score rows exceed bounded season limit")
    accepted, matched, rejected=[],set(),Counter()
    unique=set()
    for original in data:
        try:
            normalized=(normalize_team if kind=="team" else normalize_player)(
                original,season=season)
        except ValueError as exc:
            # Source assets can contain invalid/incomplete numeric rows even
            # for previously finalized fixtures. Exclude those rows, log the
            # data-quality reason, and enforce minimum *paired* game coverage.
            # Never guess possessions or scores to rescue an invalid row.
            if "Unreasonable NBA possessions estimate" in str(exc):
                rejected["unreasonable_possessions_estimate"]+=1
                continue
            if "Impossible NBA team shooting" in str(exc):
                rejected["impossible_team_stat_line"]+=1
                continue
            if str(exc).startswith("Invalid NBA box score "):
                rejected["incomplete_or_invalid_provider_stats"]+=1
                continue
            if kind=="player" and str(exc) in (
                "Invalid NBA athlete ID","Invalid NBA team ID",
                "Missing NBA athlete name"
            ):
                # Published player releases may carry unnamed/non-rostered
                # placeholders; never create fake athlete identifiers.
                rejected["invalid_player_identity"]+=1
                continue
            raise
        if normalized is None:
            rejected["missing_playing_time_or_stat_fields"]+=1
            continue
        fixture=fixtures.get(normalized["game_id"])
        if fixture is None or fixture["season"]!=season or fixture["status"]!="final":
            rejected["nonfinal_or_unmatched_fixture"]+=1
            continue
        team=normalized["team_id"]
        allowed={str(fixture["home_id"]),str(fixture["away_id"])}
        if team not in allowed:
            rejected["invalid_team_membership"]+=1
            continue
        if kind=="team":
            opp=normalized["opponent_team_id"]
            if opp not in allowed or opp==team:
                raise ValueError("NBA box-score opponent ID mismatches fixture")
            actual=fixture["home_score"] if team==str(fixture["home_id"]) else fixture["away_score"]
            if normalized["score"]!=actual:
                raise ValueError("NBA box-score total differs from verified fixture score")
            key=(normalized["game_id"],team)
        else:
            key=(normalized["game_id"],team,normalized["athlete_id"])
        if key in unique:
            raise ValueError("Duplicate NBA box-score primary key")
        unique.add(key)
        accepted.append(normalized)
        matched.add(normalized["game_id"])
    season_final={g["game_id"] for g in fixtures.values()
                  if g["season"]==season and g["status"]=="final"}
    coverage=len(matched)/len(season_final) if season_final else 0
    if kind=="team":
        grouped=Counter(row["game_id"] for row in accepted)
        complete=sum(n==2 for n in grouped.values())
        if any(n!=2 for n in grouped.values()):
            # Incomplete games are filtered, rather than pretending we know
            # a home/away team comparison with only one side's box score.
            accepted=[r for r in accepted if grouped[r["game_id"]]==2]
        coverage=complete/len(season_final) if season_final else 0
        if season_final and coverage<MIN_TEAM_COMPLETE_COVERAGE:
            raise ValueError("Insufficient two-sided NBA team box-score coverage")
    result={
        "season":season,"kind":kind,"source":PROVENANCE,"source_url":url,
        "sha256":sha,"asset_bytes":len(raw),"raw_rows":len(data),
        "accepted_rows":len(accepted),"covered_final_games":(
            len({r["game_id"] for r in accepted})),
        "verified_final_fixture_count":len(season_final),
        "fixture_coverage":round(coverage,4),
        "rejected":dict(rejected),
        "provenance_checked_at":datetime.now(timezone.utc).isoformat(),
        "commercial_use_review_required":True,
    }
    return accepted,result


def fetch_advanced(*, home:Path|str, seasons:list[int],
                   kinds:tuple[str,...]=("team","player"),
                   loader=None,opener=urlopen)->dict:
    """Atomic-per-asset private ingestion; no model or forecast table mutation.

    No new seasons are silently merged without a full validated two-sided
    team score cross-check. Failures do not delete previous asset files.
    """
    root=Path(home)
    fixtures={str(g["game_id"]):g for g in read_games(root/"nba_games.jsonl")}
    if not seasons or len(set(seasons))>11 or any(y<2017 or y>2030 for y in seasons):
        raise ValueError("Select 1-11 NBA season years")
    for kind in kinds:
        if kind not in ASSETS:raise ValueError("Unsupported NBA kind")
    summaries=[]
    for season in sorted(set(seasons)):
        for kind in kinds:
            rows,diagnostics=_process(
                kind=kind,season=season,fixtures=fixtures,loader=loader,opener=opener)
            destination=root/"advanced"/f"{kind}_{season}.json"
            manifest=root/"advanced"/f"{kind}_{season}.manifest.json"
            _atomic_json(destination,rows)
            _atomic_json(manifest,diagnostics)
            summaries.append(diagnostics)
    return {
        "status":"research_only","source_coverage":summaries,
        "files_written":len(summaries),"model_retrained":False,
        "public_publishing_enabled":False,"local_only":True,
        "commercial_use_review_required":True,
    }


def advanced_coverage(home:Path|str)->dict:
    """Read-only completeness; no model files, external calls or writes."""
    root=Path(home)/"advanced"
    rows=[]
    for manifest in sorted(root.glob("*.manifest.json")):
        try:
            item=json.loads(manifest.read_text(encoding="utf-8"))
            season=int(item["season"]);kind=item["kind"]
            if kind in ASSETS and season in range(2017,2031):
                rows.append({
                    "season":season,"kind":kind,
                    "covered_final_games":int(item["covered_final_games"]),
                    "fixture_coverage":item["fixture_coverage"],
                    "source_checked_at":item["provenance_checked_at"],
                })
        except (ValueError,KeyError,TypeError,OSError):
            continue
    return {
        "status":"research_only","assets":rows,
        "team_seasons":sum(r["kind"]=="team" for r in rows),
        "player_seasons":sum(r["kind"]=="player" for r in rows),
        "no_writes":True,"public_publishing_enabled":False,
    }
