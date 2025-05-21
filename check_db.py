#!/usr/bin/env python3
"""
Check the database content.
"""

import os
import sys
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.fixture import Fixture
from app.models.prediction import Prediction

def check_db():
    """Check database content."""
    db = SessionLocal()
    try:
        # Count fixtures and predictions
        fixture_count = db.query(Fixture).count()
        prediction_count = db.query(Prediction).count()
        
        print(f"Database content:")
        print(f"- Fixtures: {fixture_count}")
        print(f"- Predictions: {prediction_count}")
        
        # Get today's fixtures
        today = datetime.now().date()
        today_fixtures = db.query(Fixture).filter(
            Fixture.date >= datetime(today.year, today.month, today.day, 0, 0, 0),
            Fixture.date < datetime(today.year, today.month, today.day + 1, 0, 0, 0)
        ).all()
        
        print(f"\nToday's fixtures ({len(today_fixtures)}):")
        for fixture in today_fixtures:
            print(f"- {fixture.home_team} vs {fixture.away_team} ({fixture.league_name})")
        
        # Get latest predictions
        latest_predictions = db.query(Prediction).order_by(Prediction.created_at.desc()).limit(5).all()
        
        print(f"\nLatest predictions ({len(latest_predictions)}):")
        for prediction in latest_predictions:
            fixture = db.query(Fixture).filter(Fixture.fixture_id == prediction.fixture_id).first()
            if fixture:
                print(f"- {fixture.home_team} vs {fixture.away_team}: {prediction.match_result_pred} ({prediction.home_win_pred:.2f}/{prediction.draw_pred:.2f}/{prediction.away_win_pred:.2f})")
    
    finally:
        db.close()

if __name__ == "__main__":
    check_db()
