"""Stage 4 one-command private bootstrap with bounded independent source checks.

Never deploys, never changes the locked v1 model/ledger, never retries
forever or treats missing 2027 advanced assets as verified.
"""
from __future__ import annotations

import json
from datetime import datetime,timezone
from pathlib import Path

from basketball.research_automation import exclusive_local_run
from basketball.research_advanced_data import fetch_advanced
from basketball.research_current_advanced_v4 import refresh_current_advanced
from basketball.research_advanced_model import build_candidate
from basketball.research_injury_reports import capture_injury
from basketball.research_stage4_operations import stage4_report


def bootstrap_stage4(
    home:str|Path,*,now:datetime|None=None,
    historical_fetcher=fetch_advanced,
    current_fetcher=refresh_current_advanced,
    builder=build_candidate,
    injury_fetcher=capture_injury,
)->dict:
    root=Path(home)
    timestamp=now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("Timezone-aware research clock required")
    with exclusive_local_run(root):
        historical=[]
        for season in (2024,2025,2026):
            for kind in ("team","player"):
                file=root/"advanced"/f"{kind}_{season}.json"
                manifest=root/"advanced"/f"{kind}_{season}.manifest.json"
                if file.is_file() and manifest.is_file():
                    # Presence only; the original signed source manifest is
                    # verified downstream again during feature joins.
                    try:
                        meta=json.loads(manifest.read_text(encoding="utf-8"))
                        if (meta["season"]==season and meta["kind"]==kind and
                                meta["fixture_coverage"]>=0.85 and
                                meta["accepted_rows"]>0):
                            historical.append({
                                "season":season,"kind":kind,
                                "status":"already_present",
                            })
                            continue
                    except (ValueError,KeyError,TypeError,OSError):
                        pass
                try:
                    outcome=historical_fetcher(
                        home=root,seasons=[season],kinds=(kind,))
                    info=outcome["source_coverage"][0]
                    if info["season"]!=season or info["kind"]!=kind:
                        raise ValueError("Incorrect historical asset identity")
                    historical.append({
                        "season":season,"kind":kind,"status":"verified",
                        "coverage":info["fixture_coverage"],
                    })
                except (RuntimeError,ValueError,OSError,TimeoutError) as exc:
                    historical.append({
                        "season":season,"kind":kind,
                        "status":"unavailable","reason":type(exc).__name__,
                    })
        missing=[r for r in historical if r["status"]=="unavailable"]
        shadow=root/"advanced"/"shadow_model.joblib"
        model={"status":"already_present"}
        if not shadow.is_file():
            if missing:
                model={"status":"blocked",
                       "reason":"missing_historical_training_sources"}
            else:
                try:
                    model=builder(root)
                except (RuntimeError,ValueError,OSError) as exc:
                    model={"status":"blocked",
                           "reason":type(exc).__name__}
        try:
            current=current_fetcher(root,season=2027,now=timestamp)
        except (RuntimeError,ValueError,OSError) as exc:
            current={"status":"blocked",
                     "reason":type(exc).__name__}
        try:
            official=injury_fetcher(root,now=timestamp)
            injury={"status":official["status"],
                    "parsed_player_rows":official["player_rows"],
                    "extraction_status":official["extraction"]["status"]}
        except (RuntimeError,ValueError,OSError,ImportError) as exc:
            injury={"status":"unavailable",
                    "reason":type(exc).__name__}
        status="configured" if (not missing and
            shadow.is_file() and current.get("status")=="ready") else "partial"
        report=stage4_report(root,now=timestamp)
        return {
            "status":status,"phase":"stage4_private_setup",
            "historical_assets":historical,
            "historical_source_errors":len(missing),
            "advanced_model":model,
            "current_2027_assets":current,
            "official_injury_archive":injury,
            "stage4_readiness":{
                "market_support":report["market_support"],
                "blockers":report["blockers"],
                "forward_forecasts":report["probability_markets"]["forecast_count"],
            },
            "existing_v1_modified":False,
            "public_publishing_enabled":False,
            "bookmaker_lines_verified":False,
            "research_only":True,
        }
