"""Source-specific gap audit for private NBA advanced team/player fixtures.

Read-only, exact game/team IDs; distinguishes publisher lag from models.
Never fills missing player stats, extrapolates an unavailable NBA box score,
or rewrites accepted prior snapshots.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from basketball.research_data import read_games
from basketball.research_advanced_data import MIN_TEAM_COMPLETE_COVERAGE


def report(home, *, season=2027):
    root = Path(home)
    file = root / "nba_games.jsonl"
    finals = {str(g["game_id"]): g for g in read_games(file)
              if g["season"] == season and g["status"] == "final"
              and not g["postseason"]} if file.is_file() else {}
    result = {"status": "research_only", "season": season,
              "verified_final_games": len(finals), "assets": {},
              "no_writes": True, "source_rights_review_required": True}
    for kind in ("team", "player"):
        path = root / "advanced" / f"{kind}_{season}.json"
        manifest_path = root / "advanced" / f"{kind}_{season}.manifest.json"
        if not path.is_file():
            result["assets"][kind] = {"status": "missing", "complete_games": 0,
                                      "missing_games": len(finals)}
            continue
        if path.stat().st_size > 20_000_000:
            result["assets"][kind] = {"status": "invalid_asset_size"}
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(data, list) or not isinstance(manifest, dict):
                raise ValueError("Invalid accepted NBA advanced source")
            if (manifest.get("season") != season or manifest.get("kind") != kind
                or not isinstance(manifest.get("covered_final_games"), int)):
                raise ValueError("Advanced manifest identity mismatch")
            sides = defaultdict(set)
            for row in data:
                gid = str(row["game_id"])
                game = finals.get(gid)
                if not game:
                    continue
                ident = str(row["team_id"])
                if ident not in {str(game["home_id"]), str(game["away_id"])}:
                    raise ValueError("Advanced row has wrong team identity")
                sides[gid].add(ident)
            covered = {gid for gid, side in sides.items() if len(side) == 2}
            if len(covered) != manifest["covered_final_games"]:
                raise ValueError("Accepted manifest and exact-side count disagree")
            missing = [g for gid, g in sorted(finals.items(),
                      key=lambda item: (item[1]["date"], item[0]))
                      if gid not in covered]
            ratio = (len(covered) / len(finals)) if finals else None
            result["assets"][kind] = {
                "status": ("no_finals" if not finals else
                           "threshold_met" if ratio >= MIN_TEAM_COMPLETE_COVERAGE
                           else "source_lag"),
                "complete_games": len(covered),
                "missing_games": len(missing),
                "current_fixture_coverage": round(ratio, 4) if ratio is not None else None,
                "minimum_coverage": MIN_TEAM_COMPLETE_COVERAGE,
                "last_accepted_at": manifest.get("provenance_checked_at"),
                "missing_game_samples": [{
                    "game_id": str(g["game_id"]), "date": g["date"],
                    "home": g["home_name"], "away": g["away_name"],
                } for g in missing[:12]],
                "publisher_coverage_is_not_model_accuracy": True,
            }
        except (ValueError, TypeError, KeyError, OSError, json.JSONDecodeError) as exc:
            result["assets"][kind] = {
                "status": "invalid_saved_asset",
                "reason": type(exc).__name__,
            }
    return result
