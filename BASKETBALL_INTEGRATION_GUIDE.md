# Basketball Prediction Pipeline - Integration Guide

## 🏀 Overview

This guide explains how the basketball prediction pipeline integrates with your existing BetSightly football system. The basketball module follows the same architectural patterns and reuses existing infrastructure while providing NBA-specific functionality.

## 📁 Project Structure Integration

```
betsightly-backend/
├── basketball/                    # 🆕 NEW: Basketball module
│   ├── __init__.py               # Module initialization
│   ├── data_fetcher.py           # NBA data fetching (free APIs)
│   ├── feature_engineering.py   # Basketball-specific features
│   ├── models.py                 # XGBoost, LightGBM, Neural Network
│   ├── prediction_service.py    # Prediction orchestration
│   ├── train_models.py          # Training script
│   ├── predict_games.py         # Prediction script
│   ├── setup_basketball.py      # Setup automation
│   └── README.md                # Basketball documentation
├── api/
│   └── endpoints/
│       ├── predictions.py       # 🔄 EXISTING: Football predictions
│       └── basketball_predictions.py  # 🆕 NEW: Basketball API
├── utils/
│   └── config.py                # 🔄 MODIFIED: Added basketball settings
├── requirements.txt             # 🔄 MODIFIED: Added nba_api
└── models/
    ├── football/                # 🔄 EXISTING: Football models
    └── basketball/              # 🆕 NEW: Basketball models directory
```

## 🔧 Configuration Integration

### Added to `utils/config.py`:

```python
class BasketballSettings(BaseSettings):
    """Basketball prediction configuration settings."""
    
    # NBA API settings (free)
    NBA_API_ENABLED: bool = Field(True)
    NBA_API_BASE_URL: str = Field("https://stats.nba.com/stats")
    
    # Prediction settings
    MIN_CONFIDENCE_THRESHOLD: float = Field(0.60)
    MAX_PREDICTIONS_PER_CATEGORY: int = Field(8)
    
    # Feature engineering
    TEAM_FORM_GAMES: int = Field(5)
    SEASON_START_MONTH: int = Field(10)
    
    # Model settings
    PREFERRED_MODELS: str = Field("xgboost,lightgbm,neural_network")

# Added to main Settings class:
basketball: BasketballSettings = BasketballSettings()
```

### Environment Variables:

```bash
# Add to your .env file
BASKETBALL_NBA_API_ENABLED=true
BASKETBALL_MIN_CONFIDENCE_THRESHOLD=0.60
BASKETBALL_MAX_PREDICTIONS_PER_CATEGORY=8
BASKETBALL_TEAM_FORM_GAMES=5
BASKETBALL_PREFERRED_MODELS=xgboost,lightgbm,neural_network
```

## 🚀 API Integration

### New Basketball Endpoints:

The basketball API is integrated into your existing FastAPI application:

```python
# In api/api.py - ALREADY INTEGRATED
api_router.include_router(
    basketball_predictions.router, 
    prefix="/basketball-predictions", 
    tags=["basketball-predictions"]
)
```

### Available Endpoints:

```bash
# Basketball predictions (mirrors football structure)
GET  /api/basketball-predictions/
GET  /api/basketball-predictions/summary
GET  /api/basketball-predictions/confidence/{level}
GET  /api/basketball-predictions/models/status
POST /api/basketball-predictions/train

# Existing football predictions (unchanged)
GET  /api/predictions/
GET  /api/predictions/enhanced/
# ... all existing endpoints work as before
```

## 🏗️ Architecture Patterns Reused

### 1. Service Layer Pattern
```python
# Football (existing)
from services.prediction_service_improved import PredictionService

# Basketball (new, same pattern)
from basketball.prediction_service import BasketballPredictionService
```

### 2. Model Factory Pattern
```python
# Football (existing)
from ml.model_factory import model_factory

# Basketball (new, same pattern)
from basketball.models import BasketballModelFactory
```

### 3. Feature Engineering Pattern
```python
# Football (existing)
from ml.feature_engineering import FootballFeatureEngineer

# Basketball (new, same pattern)
from basketball.feature_engineering import BasketballFeatureEngineer
```

### 4. API Response Standardization
Both football and basketball APIs return consistent response formats:

```json
{
  "status": "success",
  "date": "2024-01-15",
  "sport": "football|basketball",
  "league": "Premier League|NBA",
  "count": 10,
  "predictions": [...],
  "metadata": {...}
}
```

## 🔄 Shared Infrastructure

### Database
- **Shared**: Same SQLite database and connection handling
- **Separate**: Basketball predictions stored with sport identifier
- **Compatible**: Uses existing database optimization utilities

### Caching
- **Shared**: Same LRU cache infrastructure
- **Separate**: Basketball cache in `/cache/basketball/`
- **Compatible**: Uses existing cache performance monitoring

### Security
- **Shared**: Same rate limiting, CORS, security headers
- **Consistent**: Basketball endpoints use same security middleware
- **Unified**: Same authentication and validation patterns

### Error Handling
- **Shared**: Same global exception handlers
- **Consistent**: Basketball errors use same error response format
- **Unified**: Same logging and monitoring patterns

## 📊 Data Flow Comparison

### Football Pipeline (Existing):
```
GitHub Dataset → Football Features → Football Models → Football Predictions → API
```

### Basketball Pipeline (New):
```
NBA API → Basketball Features → Basketball Models → Basketball Predictions → API
```

### Unified System:
```
┌─ Football: GitHub → Features → Models → Predictions ─┐
│                                                      ├─ Unified API
└─ Basketball: NBA API → Features → Models → Predictions ─┘
```

## 🛠️ Setup Instructions

### 1. Automated Setup (Recommended):
```bash
# Run the basketball setup script
python basketball/setup_basketball.py

# This will:
# - Install nba_api dependency
# - Create basketball directories
# - Train initial models
# - Test the pipeline
# - Verify API integration
```

### 2. Manual Setup:
```bash
# Install basketball dependencies
pip install nba_api

# Update existing dependencies
pip install -r requirements.txt

# Train basketball models
python basketball/train_models.py

# Test basketball predictions
python basketball/predict_games.py

# Start the server (includes both football and basketball)
python start_production.py
```

### 3. Verification:
```bash
# Test football endpoints (should work as before)
curl http://localhost:8000/api/predictions/

# Test new basketball endpoints
curl http://localhost:8000/api/basketball-predictions/
curl http://localhost:8000/api/basketball-predictions/summary
curl http://localhost:8000/api/basketball-predictions/models/status

# Check API documentation
open http://localhost:8000/docs
```

## 🔍 Testing Integration

### Unit Tests:
```bash
# Test basketball components
python -c "from basketball import *; print('✅ Basketball imports working')"

# Test API integration
curl -s http://localhost:8000/api/basketball-predictions/models/status | jq .
```

### Integration Tests:
```bash
# Test both sports work together
curl http://localhost:8000/api/predictions/ > football.json
curl http://localhost:8000/api/basketball-predictions/ > basketball.json

# Verify both return valid responses
python -c "import json; print('Football:', json.load(open('football.json'))['status'])"
python -c "import json; print('Basketball:', json.load(open('basketball.json'))['status'])"
```

## 📈 Performance Considerations

### Resource Usage:
- **Memory**: Basketball models add ~50-100MB
- **Storage**: Basketball cache and models add ~100-200MB
- **CPU**: Basketball predictions add minimal overhead
- **Network**: NBA API calls are rate-limited and cached

### Optimization:
- **Shared Cache**: Both sports use same caching infrastructure
- **Lazy Loading**: Basketball models only loaded when needed
- **Parallel Processing**: Can generate both sport predictions simultaneously

## 🔧 Maintenance

### Model Updates:
```bash
# Retrain football models (existing)
python ml_pipeline_streamlined.py --train-only --retrain

# Retrain basketball models (new)
python basketball/train_models.py --retrain

# Both can run independently
```

### Data Updates:
```bash
# Football data updates (existing process)
# Basketball data updates (automatic via NBA API)
```

### Monitoring:
```bash
# Check both systems
curl http://localhost:8000/api/health/detailed

# Check specific sport status
curl http://localhost:8000/api/predictions/  # Football
curl http://localhost:8000/api/basketball-predictions/models/status  # Basketball
```

## 🚨 Troubleshooting

### Common Issues:

1. **Import Errors**:
   ```bash
   # Install missing dependencies
   pip install nba_api
   ```

2. **API Conflicts**:
   ```bash
   # Basketball and football APIs are separate - no conflicts
   # Different prefixes: /api/predictions/ vs /api/basketball-predictions/
   ```

3. **Model Training**:
   ```bash
   # Train basketball models if missing
   python basketball/train_models.py --retrain
   ```

4. **NBA API Issues**:
   ```bash
   # NBA API is free but has rate limits
   # System includes automatic rate limiting and retries
   ```

## ✅ Integration Checklist

- [x] Basketball module created with proper structure
- [x] Configuration integrated into existing config system
- [x] API endpoints added to existing FastAPI application
- [x] Same architectural patterns followed
- [x] Shared infrastructure utilized
- [x] Error handling and security consistent
- [x] Documentation and setup scripts provided
- [x] Testing and verification procedures included
- [x] No conflicts with existing football system
- [x] Free data sources and tools only

## 🎯 Next Steps

1. **Run Setup**: Execute `python basketball/setup_basketball.py`
2. **Test Integration**: Verify both football and basketball APIs work
3. **Train Models**: Generate initial basketball predictions
4. **Monitor Performance**: Check system performance with both sports
5. **Customize**: Adjust basketball settings as needed

The basketball prediction pipeline is now fully integrated with your BetSightly system! 🏀⚽
