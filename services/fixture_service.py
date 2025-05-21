"""
Fixture service for managing football match fixtures.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.models.fixture import Fixture
from app.models.prediction import Prediction

class FixtureService:
    """Service for managing football match fixtures."""

    def __init__(self, db: Session):
        """Initialize with database session."""
        self.db = db

    def get_fixture_by_id(self, fixture_id: int) -> Optional[Fixture]:
        """Get a fixture by ID."""
        return self.db.query(Fixture).filter(Fixture.fixture_id == fixture_id).first()

    def get_fixtures_by_date(self, date: datetime) -> List[Fixture]:
        """Get fixtures by date."""
        start_date = datetime(date.year, date.month, date.day, 0, 0, 0)
        end_date = start_date + timedelta(days=1)
        return self.db.query(Fixture).filter(
            Fixture.date >= start_date,
            Fixture.date < end_date
        ).all()

    def get_fixtures_by_league(self, league_id: int, date: Optional[datetime] = None) -> List[Fixture]:
        """Get fixtures by league."""
        query = self.db.query(Fixture).filter(Fixture.league_id == league_id)

        if date:
            start_date = datetime(date.year, date.month, date.day, 0, 0, 0)
            end_date = start_date + timedelta(days=1)
            query = query.filter(
                Fixture.date >= start_date,
                Fixture.date < end_date
            )

        return query.all()

    def create_fixture(self, fixture_data: Dict[str, Any]) -> Fixture:
        """Create a new fixture."""
        fixture = Fixture.from_api(fixture_data)
        self.db.add(fixture)
        self.db.commit()
        self.db.refresh(fixture)
        return fixture

    def update_fixture(self, fixture_id: int, fixture_data: Dict[str, Any]) -> Optional[Fixture]:
        """Update an existing fixture."""
        fixture = self.get_fixture_by_id(fixture_id)
        if not fixture:
            return None

        for key, value in fixture_data.items():
            if hasattr(fixture, key):
                setattr(fixture, key, value)

        self.db.commit()
        self.db.refresh(fixture)
        return fixture

    def delete_fixture(self, fixture_id: int) -> bool:
        """Delete a fixture."""
        fixture = self.get_fixture_by_id(fixture_id)
        if not fixture:
            return False

        self.db.delete(fixture)
        self.db.commit()
        return True

    def create_or_update_fixtures(self, fixtures_data: List[Dict[str, Any]]) -> List[Fixture]:
        """Create or update fixtures from API data."""
        fixtures = []

        for fixture_data in fixtures_data:
            # Convert date string to datetime if needed
            if "date" in fixture_data and isinstance(fixture_data["date"], str):
                try:
                    fixture_data["date"] = datetime.fromisoformat(fixture_data["date"].replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    # If date conversion fails, use current time
                    fixture_data["date"] = datetime.utcnow()

            existing_fixture = self.get_fixture_by_id(fixture_data["fixture_id"])

            if existing_fixture:
                # Update existing fixture
                for key, value in fixture_data.items():
                    if hasattr(existing_fixture, key):
                        setattr(existing_fixture, key, value)
                fixtures.append(existing_fixture)
            else:
                # Create new fixture
                try:
                    fixture = Fixture.from_api(fixture_data)
                except Exception as e:
                    # If from_api fails, create fixture directly
                    fixture = Fixture(
                        fixture_id=fixture_data["fixture_id"],
                        date=fixture_data["date"],
                        league_id=fixture_data["league_id"],
                        league_name=fixture_data["league_name"],
                        home_team_id=fixture_data["home_team_id"],
                        home_team=fixture_data["home_team"],
                        away_team_id=fixture_data["away_team_id"],
                        away_team=fixture_data["away_team"],
                        home_odds=fixture_data.get("home_odds", 0),
                        draw_odds=fixture_data.get("draw_odds", 0),
                        away_odds=fixture_data.get("away_odds", 0)
                    )
                self.db.add(fixture)
                fixtures.append(fixture)

        self.db.commit()
        for fixture in fixtures:
            self.db.refresh(fixture)

        return fixtures
