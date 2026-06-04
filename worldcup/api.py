"""
World Cup 2026 — API Endpoints

Provides:
- GET /api/worldcup/fixtures       — all matches with odds
- GET /api/worldcup/predictions    — all predictions
- GET /api/worldcup/predictions/{match_id} — single match prediction
- GET /api/worldcup/teams          — team list with form stats
- GET /api/worldcup/value-bets     — best value bets across all matches
- POST /api/worldcup/refresh       — re-fetch odds + regenerate predictions
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)
DATA_DIR = Path(__file__).parent / "data"

router = APIRouter(prefix="/api/worldcup", tags=["World Cup 2026"])


def _load_json(filename: str) -> list | dict:
    """Load a JSON file from the data directory."""
    path = DATA_DIR / filename
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


@router.get("/fixtures")
async def get_fixtures():
    """Get all World Cup fixtures with odds."""
    fixtures = _load_json("wc_fixtures.json")
    if not fixtures:
        raise HTTPException(404, "No fixtures data. Run the data collection script first.")

    # Load team IDs for logos
    team_map = _load_json("wc_team_ids.json")

    # Enrich with team logos
    for fx in fixtures:
        home_info = team_map.get(fx["home_team"], {})
        away_info = team_map.get(fx["away_team"], {})
        fx["home_team_logo"] = home_info.get("logo")
        fx["away_team_logo"] = away_info.get("logo")

    return {
        "status": "success",
        "total": len(fixtures),
        "tournament": "FIFA World Cup 2026",
        "start_date": "2026-06-11",
        "fixtures": fixtures,
    }


@router.get("/predictions")
async def get_predictions(
    min_confidence: float = Query(0.0, description="Minimum confidence filter"),
    risk_level: Optional[str] = Query(None, description="Filter: low, medium, high"),
    date: Optional[str] = Query(None, description="Filter by date (YYYY-MM-DD)"),
):
    """Get all match predictions."""
    predictions = _load_json("wc_predictions.json")
    if not predictions:
        raise HTTPException(404, "No predictions. Run the prediction model first.")

    # Load team logos
    team_map = _load_json("wc_team_ids.json")
    for p in predictions:
        home_info = team_map.get(p["home_team"], {})
        away_info = team_map.get(p["away_team"], {})
        p["home_team_logo"] = home_info.get("logo")
        p["away_team_logo"] = away_info.get("logo")

    # Apply filters
    filtered = predictions
    if min_confidence > 0:
        filtered = [p for p in filtered if p["confidence"] >= min_confidence]
    if risk_level:
        filtered = [p for p in filtered if p["risk_level"] == risk_level]
    if date:
        filtered = [p for p in filtered if p["commence_time"].startswith(date)]

    return {
        "status": "success",
        "total": len(filtered),
        "predictions": filtered,
    }


@router.get("/predictions/{match_id}")
async def get_prediction(match_id: str):
    """Get prediction for a single match."""
    predictions = _load_json("wc_predictions.json")
    for p in predictions:
        if p["match_id"] == match_id:
            # Add team logos
            team_map = _load_json("wc_team_ids.json")
            p["home_team_logo"] = team_map.get(p["home_team"], {}).get("logo")
            p["away_team_logo"] = team_map.get(p["away_team"], {}).get("logo")
            return {"status": "success", "prediction": p}

    raise HTTPException(404, f"Match {match_id} not found")


@router.get("/teams")
async def get_teams():
    """Get all World Cup teams with form stats."""
    team_map = _load_json("wc_team_ids.json")
    histories = _load_json("wc_team_histories.json")

    if not team_map:
        raise HTTPException(404, "No team data available.")

    from worldcup.model import compute_team_features

    teams = []
    for name, info in team_map.items():
        matches = histories.get(name, [])
        features = compute_team_features(matches)
        teams.append({
            "name": name,
            "api_football_id": info.get("id"),
            "logo": info.get("logo"),
            "form": features,
            "recent_results": [
                {
                    "opponent": m["opponent"],
                    "result": m["result"],
                    "score": f"{m['goals_for']}-{m['goals_against']}",
                    "date": m["date"],
                    "league": m["league"],
                }
                for m in matches[:5]  # Last 5 for display
            ],
        })

    # Sort by form score
    teams.sort(key=lambda t: t["form"]["form_score"], reverse=True)

    return {
        "status": "success",
        "total": len(teams),
        "teams": teams,
    }


@router.get("/value-bets")
async def get_value_bets(min_edge: float = Query(0.0, description="Minimum edge filter")):
    """Get best value bets across all matches."""
    predictions = _load_json("wc_predictions.json")
    if not predictions:
        raise HTTPException(404, "No predictions available.")

    team_map = _load_json("wc_team_ids.json")

    value_bets = []
    for p in predictions:
        for vb in p.get("value_bets", []):
            if vb["edge"] >= min_edge:
                value_bets.append({
                    "match": f"{p['home_team']} vs {p['away_team']}",
                    "match_id": p["match_id"],
                    "commence_time": p["commence_time"],
                    "home_team_logo": team_map.get(p["home_team"], {}).get("logo"),
                    "away_team_logo": team_map.get(p["away_team"], {}).get("logo"),
                    **vb,
                })

    # Sort by expected value
    value_bets.sort(key=lambda x: x["expected_value"], reverse=True)

    return {
        "status": "success",
        "total": len(value_bets),
        "value_bets": value_bets,
    }


@router.post("/refresh")
async def refresh_predictions():
    """Re-fetch odds and regenerate predictions."""
    try:
        from worldcup.fetch_data import fetch_odds
        from worldcup.model import generate_all_predictions

        fixtures = fetch_odds()
        predictions = generate_all_predictions()

        return {
            "status": "success",
            "fixtures_updated": len(fixtures),
            "predictions_generated": len(predictions),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error refreshing predictions: {e}", exc_info=True)
        raise HTTPException(500, f"Refresh failed: {str(e)}")
