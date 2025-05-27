"""
Prediction Combination model for storing categorized prediction combinations.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Table
from sqlalchemy.orm import relationship

from database import Base

# Association table for many-to-many relationship between predictions and combinations
prediction_combination_items = Table(
    "prediction_combination_items",
    Base.metadata,
    Column("id", Integer, primary_key=True),
    Column("combination_id", String(50), ForeignKey("prediction_combinations.id")),
    Column("prediction_id", Integer, ForeignKey("predictions.id"))
)

class PredictionCombination(Base):
    """Prediction Combination model for storing categorized prediction combinations."""

    __tablename__ = "prediction_combinations"

    id = Column(String(50), primary_key=True)
    category = Column(String(20), index=True)  # 2_odds, 5_odds, 10_odds, rollover
    combined_odds = Column(Float, default=0)
    combined_confidence = Column(Float, default=0)
    rollover_day = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    predictions = relationship("Prediction", secondary=prediction_combination_items, backref="combinations")

    def __repr__(self):
        return f"<PredictionCombination {self.id}: {self.category}>"

    def to_dict(self):
        """Convert prediction combination to dictionary."""
        return {
            "id": self.id,
            "category": self.category,
            "combined_odds": self.combined_odds,
            "combined_confidence": self.combined_confidence,
            "rollover_day": self.rollover_day,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "predictions": [prediction.to_dict() for prediction in self.predictions]
        }

    @classmethod
    def from_combination_data(cls, combination_data):
        """Create a PredictionCombination instance from combination data."""
        return cls(
            id=combination_data["id"],
            category=combination_data["category"],
            combined_odds=combination_data["combined_odds"],
            combined_confidence=combination_data["combined_confidence"],
            rollover_day=combination_data.get("day")
        )
