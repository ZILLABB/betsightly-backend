"""Read-only source-to-archive NBA completeness audit, never a prediction."""
from datetime import datetime, timedelta, timezone
from basketball.research_private_bundle import inspect_bundle

def audit_nba_coverage(archive, source_games, *, now, season, manifests):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NBA_COVERAGE_CLOCK_UNAWARE")
    inspect_bundle(archive)
    matches=[m for m in manifests if isinstance(m,dict) and m.get("season")==season]
    if len(matches)!=1 or not isinstance(source_games,list):
        raise ValueError("NBA_COVERAGE_SOURCE_PROVENANCE_MISSING")
    quality=matches[0].get("quality",{})
    valid=quality.get("rejected_regular_rows")==0 and quality.get(
        "not_a_complete_provider_schedule") is False
    clock=now.astimezone(timezone.utc)
    archived={str(g["game_id"]):g for g in archive["fixtures"]}
    money={str(r["game_id"]) for r in archive["records"]["moneyline"]}
    score={str(r["game_id"]) for r in archive["records"]["opening_score"]}
    source_ids=set()
    imminent=[]; seven=[]
    for g in source_games:
        if g.get("season")!=season:
            continue
        gid=str(g["game_id"])
        if gid in source_ids:
            raise ValueError("NBA_COVERAGE_DUPLICATE_SOURCE")
        source_ids.add(gid)
        if g.get("status")!="scheduled" or g.get("postseason"):
            continue
        tip=datetime.fromisoformat(g["start_utc"].replace("Z","+00:00"))
        if tip.tzinfo is None:
            raise ValueError("NBA_COVERAGE_TIPOFF_UNAWARE")
        tip=tip.astimezone(timezone.utc)
        if clock+timedelta(minutes=10)<tip<=clock+timedelta(days=7):
            seven.append((gid,g))
            if tip<=clock+timedelta(hours=48):
                imminent.append((gid,g))
    missing=[]; unsigned=[]
    for gid,g in imminent:
        prior=archived.get(gid)
        if prior and any(prior[k]!=g[k] for k in
                          ("season","home_id","away_id","start_utc")):
            raise ValueError("NBA_COVERAGE_SOURCE_ARCHIVE_IDENTITY_CONFLICT")
        if not prior:
            missing.append(gid)
        if gid not in money or gid not in score:
            unsigned.append(gid)
    return {
        "status":"source_to_archive_48h_coverage","research_only":True,
        "not_bookable":True,"season":season,
        "manifest_accepted":bool(valid),
        "next_48h_source_fixtures":len(imminent),
        "next_48h_missing_archive":len(missing),
        "next_48h_missing_original_model":len(unsigned),
        "next_7d_source_fixtures":len(seven),
        "next_7d_not_archived":sum(gid not in archived for gid,_ in seven),
        "next_48h_original_coverage_complete":bool(valid and not unsigned),
        "missing_archive_examples":sorted(missing)[:15],
        "withheld_model_examples":sorted(unsigned)[:15],
        "independent_schedule_agreement_proven":False,
        "full_season_prediction_coverage_proven":False,
    }
