"""
API endpoints for fixtures.
"""

from typing import List, Optional
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Query

from sqlalchemy.orm import Session

from database import get_db
from fixture import Fixture
from prediction import Prediction
from services.fixture_service import FixtureService as OddsFixtureService
from utils.security import require_api_key

router = APIRouter()

@router.get("/")
def get_fixtures(
    db: Session = Depends(get_db),
    date: Optional[date] = None,
    league_id: Optional[int] = None
):
    """Get fixtures."""
    # Queried directly, as the prediction endpoint below already does. This
    # used to call a db-backed FixtureService that no longer exists anywhere
    # in the project — the name resolved to nothing, so every request here
    # raised NameError and returned a 500. The only FixtureService that does
    # exist takes an api_key and fetches remotely; it is imported above as
    # OddsFixtureService and used by the odds endpoints further down.
    query = db.query(Fixture)

    if league_id:
        query = query.filter(Fixture.league_id == league_id)

    day = date or datetime.now().date()
    start = datetime.combine(day, datetime.min.time())
    end = datetime.combine(day, datetime.max.time())
    query = query.filter(Fixture.date >= start, Fixture.date <= end)

    fixtures = query.order_by(Fixture.date).all()
    return [fixture.to_dict() for fixture in fixtures]

@router.get("/{fixture_id}")
def get_fixture(
    fixture_id: int,
    db: Session = Depends(get_db)
):
    """Get fixture by ID."""
    fixture = db.query(Fixture).filter(Fixture.id == fixture_id).first()

    if not fixture:
        raise HTTPException(status_code=404, detail="Fixture not found")

    return fixture.to_dict()

@router.get("/{fixture_id}/prediction")
def get_fixture_prediction(
    fixture_id: int,
    db: Session = Depends(get_db)
):
    """Get prediction for fixture."""
    # Query prediction directly from database
    prediction = db.query(Prediction).filter(Prediction.fixture_id == fixture_id).first()

    if not prediction:
        raise HTTPException(status_code=404, detail="Prediction not found")

    return prediction.to_dict()


# Fixture Testing Endpoints (via The Odds API)
@router.get("/odds-api/test")
def test_odds_api_connection():
    """Test fixture API connections (football-data.org + The Odds API)."""
    try:
        service = OddsFixtureService()
        is_connected = service.test_connection()
        credit_status = service.get_credit_status()
        return {
            "status": "success" if is_connected else "failed",
            "message": "Fixture API connection test",
            "connected": is_connected,
            "credits_remaining": credit_status.get("remaining", "?"),
            "credits_used": credit_status.get("used", "?"),
            "has_football_data_org": bool(service.fdo_api_key),
            "has_odds_api": bool(service.odds_api_key),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error: {str(e)}",
            "connected": False,
            "timestamp": datetime.now().isoformat()
        }


@router.get("/odds-api/daily")
def get_daily_fixtures_odds_api(
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format (defaults to today)")
):
    """Get daily fixtures from The Odds API."""
    try:
        service = OddsFixtureService()
        fixtures = service.get_daily_fixtures(date)
        return {
            "status": "success",
            "message": f"Retrieved fixtures for {date or 'today'}",
            "count": len(fixtures),
            "credits_remaining": service.remaining_credits,
            "fixtures": fixtures,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to fetch fixtures")


@router.post("/apifootball/sync", dependencies=[Depends(require_api_key)])
def sync_fixtures_from_apifootball(
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format (defaults to today)"),
    db: Session = Depends(get_db)
):
    """Sync fixtures from APIFootball.com to database.

    Not implemented. This called `sync_fixtures_from_apifootball` on a
    db-backed FixtureService that does not exist in the project, so the call
    raised NameError, was swallowed by the except below, and returned a 500
    reading "Failed to sync fixtures" — which described a transient failure
    rather than a method that was never written.

    `APIFootballService.get_daily_fixtures` can fetch the data, but nothing
    maps it onto the Fixture table, and guessing that mapping would risk
    writing wrong rows into the fixture history. Saying so plainly is better
    than a 500 that implies the feature works on a good day.

    The live pipeline does not depend on this: `leagues/` takes its fixtures
    from ESPN and prices them through the bookmaker adapter.
    """
    raise HTTPException(
        status_code=501,
        detail=("Fixture sync is not implemented. Fixtures are ingested by the "
                "leagues pipeline (ESPN), not through this endpoint."),
    )
