"""Stage 4A resilient current-season team/player advanced refresh.

Each asset is independently verified and only that exact asset is replaced.
Partial availability is reported explicitly; never fake player data or use
last season's team efficiencies for same-season prospective forecasts.
"""
from __future__ import annotations

import json
from datetime import datetime,timezone
from pathlib import Path
from basketball.research_advanced_data import fetch_advanced,MIN_TEAM_COMPLETE_COVERAGE


def refresh_current_advanced(home:str|Path,*,season:int,
                             now:datetime|None=None,
                             fetcher=fetch_advanced)->dict:
    instant=now or datetime.now(timezone.utc)
    if instant.tzinfo is None:raise ValueError("Timezone-aware research clock required")
    if not 2027<=season<=2030:raise ValueError("Current research season must be >=2027")
    root=Path(home)
    outcomes={}
    for kind in ("team","player"):
        try:
            result=fetcher(home=root,seasons=[season],kinds=(kind,))
            report=result["source_coverage"][0]
            if report["season"]!=season or report["kind"]!=kind:
                raise ValueError("Current NBA advanced asset identity mismatch")
            outcomes[kind]={
                "status":"verified",
                "fixture_coverage":report["fixture_coverage"],
                "accepted_rows":report["accepted_rows"],
                "checked_at":report["provenance_checked_at"],
            }
        except (RuntimeError,ValueError,OSError,TimeoutError) as exc:
            # A newly completed NBA fixture can precede the box-score
            # publisher's next release. Never replace a previously accepted
            # file with a partially populated newer snapshot.
            coverage_error=isinstance(exc,ValueError) and str(exc) in (
                "Insufficient two-sided NBA team box-score coverage",
                "Insufficient current NBA player box-score coverage",
            )
            outcomes[kind]={
                "status":"unavailable",
                "reason":("insufficient_current_fixture_coverage"
                          if coverage_error else type(exc).__name__),
            }
            if coverage_error:
                outcomes[kind]["minimum_fixture_coverage"]=MIN_TEAM_COMPLETE_COVERAGE
                manifest=root/"advanced"/f"{kind}_{season}.manifest.json"
                if manifest.is_file():
                    try:
                        old=json.loads(manifest.read_text(encoding="utf-8"))
                        if old.get("season")==season and old.get("kind")==kind:
                            outcomes[kind]["last_accepted_snapshot"]={
                                "covered_final_games":int(old["covered_final_games"]),
                                "source_checked_at":str(old["provenance_checked_at"]),
                            }
                    except (OSError,ValueError,TypeError,KeyError):
                        pass
    count=sum(v["status"]=="verified" for v in outcomes.values())
    return {
        "status":"ready" if count==2 else "partial" if count else "blocked",
        "season":season,
        "assets":outcomes,
        "successful_assets":count,
        "model_retrained":False,
        "old_season_substitution":False,
        "player_availability_inferred":False,
        "source_rights_review_required":True,
        "research_only":True,
        "public_publishing_enabled":False,
    }
