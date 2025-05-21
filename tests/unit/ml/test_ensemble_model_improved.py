"""
Test Ensemble Model Improved

This module contains tests for the improved ensemble model.
"""

import os
import sys
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Add the parent directory to the path so we can import the app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from app.ml.ensemble_model_improved import (
    MatchResultModel, 
    OverUnderModel, 
    BTTSModel, 
    ImprovedEnsembleModel
)

@pytest.fixture
def sample_data():
    """Create sample data for testing."""
    # Create sample features
    features_data = []
    
    for i in range(100):
        match_date = datetime.now() - timedelta(days=i)
        
        features_data.append({
            "match_id": f"match_{i}",
            "date": match_date,
            "home_team": f"Home Team {i % 10}",
            "away_team": f"Away Team {i % 8}",
            "competition_name": f"League {i % 5}",
            "season": 2023
        })
    
    features_df = pd.DataFrame(features_data)
    
    # Create sample results
    results_data = []
    
    for i in range(100):
        # Generate random results
        home_score = np.random.randint(0, 5)
        away_score = np.random.randint(0, 4)
        
        # Determine match result
        if home_score > away_score:
            match_result = "H"
        elif home_score < away_score:
            match_result = "A"
        else:
            match_result = "D"
        
        # Determine over/under
        over_2_5 = 1 if home_score + away_score > 2.5 else 0
        
        # Determine BTTS
        btts = 1 if home_score > 0 and away_score > 0 else 0
        
        results_data.append({
            "match_id": f"match_{i}",
            "match_result": match_result,
            "over_2_5": over_2_5,
            "btts": btts,
            "home_score": home_score,
            "away_score": away_score
        })
    
    results_df = pd.DataFrame(results_data)
    
    # Create historical data
    historical_data = []
    
    for i in range(100):
        match_date = datetime.now() - timedelta(days=i)
        
        # Generate random scores
        home_score = np.random.randint(0, 5)
        away_score = np.random.randint(0, 4)
        
        historical_data.append({
            "match_id": f"match_{i}",
            "date": match_date,
            "competition_name": f"League {i % 5}",
            "season": 2023,
            "home_team": f"Home Team {i % 10}",
            "away_team": f"Away Team {i % 8}",
            "home_score": home_score,
            "away_score": away_score
        })
    
    historical_df = pd.DataFrame(historical_data)
    
    return features_df, results_df, historical_df

@pytest.fixture
def sample_fixture_data():
    """Create sample fixture data for testing."""
    return {
        "fixture": {
            "id": 12345,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "status": {
                "short": "NS"
            }
        },
        "league": {
            "id": 39,
            "name": "Premier League",
            "season": 2023
        },
        "teams": {
            "home": {
                "id": 33,
                "name": "Manchester United"
            },
            "away": {
                "id": 40,
                "name": "Liverpool"
            }
        }
    }

def test_match_result_model_init():
    """Test MatchResultModel initialization."""
    model = MatchResultModel()
    assert model.model_name == "match_result_ensemble"
    assert model.model is None
    assert model.feature_scaler is None
    assert model.feature_names is None

def test_over_under_model_init():
    """Test OverUnderModel initialization."""
    model = OverUnderModel()
    assert model.model_name == "over_under_ensemble"
    assert model.model is None
    assert model.feature_scaler is None
    assert model.feature_names is None

def test_btts_model_init():
    """Test BTTSModel initialization."""
    model = BTTSModel()
    assert model.model_name == "btts_ensemble"
    assert model.model is None
    assert model.feature_scaler is None
    assert model.feature_names is None

def test_improved_ensemble_model_init():
    """Test ImprovedEnsembleModel initialization."""
    model = ImprovedEnsembleModel()
    assert isinstance(model.match_result_model, MatchResultModel)
    assert isinstance(model.over_under_model, OverUnderModel)
    assert isinstance(model.btts_model, BTTSModel)

@pytest.mark.skip(reason="This test requires training models which is time-consuming")
def test_improved_ensemble_model_train(sample_data):
    """Test ImprovedEnsembleModel training."""
    features_df, results_df, historical_df = sample_data
    
    model = ImprovedEnsembleModel()
    result = model.train(features_df, results_df, historical_df)
    
    assert result["status"] == "success"
    assert "match_result_accuracy" in result
    assert "over_under_accuracy" in result
    assert "btts_accuracy" in result

@pytest.mark.skip(reason="This test requires trained models")
def test_improved_ensemble_model_predict(sample_fixture_data, sample_data):
    """Test ImprovedEnsembleModel prediction."""
    _, _, historical_df = sample_data
    
    model = ImprovedEnsembleModel()
    result = model.predict(sample_fixture_data, historical_df)
    
    assert result["status"] == "success"
    assert "predictions" in result
    assert len(result["predictions"]) > 0

def test_preprocess_data(sample_data):
    """Test data preprocessing."""
    features_df, results_df, _ = sample_data
    
    model = ImprovedEnsembleModel()
    
    # Merge data
    data = pd.merge(features_df, results_df, on="match_id")
    
    # Preprocess data
    X, y_match_result, y_over_under, y_btts = model._preprocess_data(data)
    
    assert isinstance(X, pd.DataFrame)
    assert isinstance(y_match_result, pd.Series)
    assert isinstance(y_over_under, pd.Series)
    assert isinstance(y_btts, pd.Series)
    
    assert len(X) == len(y_match_result) == len(y_over_under) == len(y_btts)
    assert "match_id" not in X.columns
    assert "date" not in X.columns
    assert "home_team" not in X.columns
    assert "away_team" not in X.columns
