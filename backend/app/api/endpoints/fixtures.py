"""
API endpoints for fixtures.
"""

from typing import List, Optional
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Query

from sqlalchemy.orm import Session

from app.database import get_db
from app.models.fixture import Fixture
from app.models.prediction import Prediction
from app.services.fixture_service import FixtureService
from app.services.prediction_service_improved import PredictionService

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
    prediction_service = PredictionService(db)
    prediction = prediction_service.get_prediction_by_fixture_id(fixture_id)

    if not prediction:
        raise HTTPException(status_code=404, detail="Prediction not found")

    return prediction.to_dict()
