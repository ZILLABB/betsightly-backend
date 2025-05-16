"""
Models package.
"""

from sqlalchemy.orm import relationship

# Import models
from app.models.fixture import Fixture
from app.models.prediction import Prediction

# Set up relationships after both classes are defined
Fixture.predictions = relationship("Prediction", back_populates="fixture", cascade="all, delete-orphan")
Prediction.fixture = relationship("Fixture", back_populates="predictions")