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

router = APIRouter()

@router.get("/")
def get_fixtures(
    db: Session = Depends(get_db),
    date: Optional[date] = None,
    league_id: Optional[int] = None
):
    """Get fixtures."""
    fixture_service = FixtureService(db)

    if date and league_id:
        # Get fixtures by date and league
        fixtures = fixture_service.get_fixtures_by_league(
            league_id=league_id,
            date=datetime.combine(date, datetime.min.time())
        )
    elif date:
        # Get fixtures by date
        fixtures = fixture_service.get_fixtures_by_date(
            date=datetime.combine(date, datetime.min.time())
        )
    elif league_id:
        # Get fixtures by league
        fixtures = fixture_service.get_fixtures_by_league(league_id=league_id)
    else:
        # Get today's fixtures
        fixtures = fixture_service.get_fixtures_by_date(
            date=datetime.now()
        )

    return [fixture.to_dict() for fixture in fixtures]

@router.get("/{fixture_id}")
def get_fixture(
    fixture_id: int,
    db: Session = Depends(get_db)
):
    """Get fixture by ID."""
    fixture_service = FixtureService(db)
    fixture = fixture_service.get_fixture_by_id(fixture_id)

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


@router.post("/apifootball/sync")
def sync_fixtures_from_apifootball(
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format (defaults to today)"),
    db: Session = Depends(get_db)
):
    """Sync fixtures from APIFootball.com to database."""
    try:
        fixture_service = FixtureService(db)
        fixtures = fixture_service.sync_fixtures_from_apifootball(date)

        return {
            "status": "success",
            "message": f"Synced fixtures from APIFootball.com for {date or 'today'}",
            "count": len(fixtures),
            "fixtures": [fixture.to_dict() for fixture in fixtures],
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Failed to sync fixtures"
        )
