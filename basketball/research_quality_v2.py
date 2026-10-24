"""Stage 3A NBA dataset coverage and verified feature-availability audit.

Read-only private snapshot audit. Never infers possessions, injuries, travel
miles or betting odds when none of those inputs exists in normalized games.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from basketball.research_data import read_games
from basketball.research_features import quality_report


def audit_games(games: list[dict], manifest: list[dict] | None = None) -> dict:
    base=quality_report(games)
    seasons=defaultdict(lambda: {
        "final":0,"scheduled":0,"other":0,"missing_valid_tipoff":0,
        "teams":set(),"source_counts":Counter(),
    })
    for game in games:
        row=seasons[str(game["season"])]
        row[game["status"] if game["status"] in ("final","scheduled") else "other"]+=1
        row["teams"].update((str(game["home_id"]),str(game["away_id"])))
        row["source_counts"][game["source"]]+=1
        kickoff=game.get("start_utc")
        try:
            parsed=datetime.fromisoformat(str(kickoff).replace("Z","+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("No timezone")
        except (ValueError,TypeError):
            row["missing_valid_tipoff"]+=1
    summary={
        year: {
            **{k:v for k,v in data.items()
               if k not in ("teams","source_counts")},
            "distinct_team_ids":len(data["teams"]),
            "by_source":dict(sorted(data["source_counts"].items())),
        }
        for year,data in sorted(seasons.items())
    }
    manifest = manifest or []
    excluded = {}
    for entry in manifest:
        if not isinstance(entry, dict) or "season" not in entry:
            continue
        quality = entry.get("quality")
        excluded[str(entry["season"])] = (
            quality if isinstance(quality, dict) and
            isinstance(quality.get("rejected_regular_rows"), int) and
            quality["rejected_regular_rows"] >= 0 else None
        )
    # Older manifests predate the exclusion audit. Never turn missing
    # provenance into a false measurement of zero rejected fixtures.
    audited = {
        season: record for season, record in excluded.items()
        if record is not None
    }
    missing = [
        season for season in sorted(seasons)
        if str(season) not in audited
    ]
    return {
        "status":"research_only","phase":"stage_3a_dataset_audit",
        "games":base["games"],
        "completed_regular_games":base["completed_regular_games"],
        "v1_eligible_training_rows":base["eligible_model_rows"],
        "seasons":summary,
        "season_source_audits": excluded,
        "source_audit_provenance": (
            "complete" if not missing else
            "partial" if audited else "not_recorded"
        ),
        "source_audited_seasons": sorted(audited),
        "source_unaudited_seasons": missing,
        "source_rejected_regular_rows_known": sum(
            item["rejected_regular_rows"] for item in audited.values()
        ),
        "source_rejected_regular_rows": (
            sum(item["rejected_regular_rows"] for item in audited.values())
            if len(audited) == len(seasons) else None
        ),
        "source_rejected_regular_rows_note": (
            "null means one or more season source manifests predate the "
            "exclusion audit; it does not establish zero rejected rows"
        ),
        "unavailable_inputs":{
            "true_possessions_and_pace":"requires validated box-score possessions",
            "offensive_defensive_rating":"requires validated possessions",
            "injuries_and_lineups":"requires separate timestamped verified feed",
            "travel_distance":"requires venue identity and neutral-site validation",
            "historical_bookmaker_prices":"not collected",
        },
        "no_writes":True,
        "commercial_use_review_required":True,
        "public_publishing_enabled":False,
    }


def audit_home(home:str|Path) -> dict:
    root=Path(home)
    games=read_games(root/"nba_games.jsonl")
    manifests=[]
    latest=root/"current_season_refresh.json"
    historical=root/"source_manifest.json"
    if historical.is_file():
        payload=json.loads(historical.read_text(encoding="utf-8"))
        if isinstance(payload,list):
            manifests.extend(payload)
    if latest.is_file():
        payload=json.loads(latest.read_text(encoding="utf-8"))
        if isinstance(payload,dict):
            recent=payload.get("source_manifest") or []
            if isinstance(recent,list):
                by_season = {
                    m.get("season"): m for m in manifests
                    if isinstance(m, dict) and "season" in m
                }
                for record in recent:
                    if not isinstance(record, dict) or "season" not in record:
                        continue
                    prior = by_season.get(record["season"])
                    # Prefer latest source metadata once it includes the new
                    # audit; retain older validated quality if the latest
                    # local record still predates that feature.
                    prior_quality = ((prior or {}).get("quality") or {})
                    current_quality = record.get("quality") or {}
                    if (not isinstance(current_quality.get("rejected_regular_rows"), int)
                            and isinstance(prior_quality.get("rejected_regular_rows"), int)):
                        record = {**record, "quality": prior_quality}
                    by_season[record["season"]] = record
                manifests = list(by_season.values())
    return audit_games(games, manifests)
