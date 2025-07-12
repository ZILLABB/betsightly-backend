# BetSightly API Documentation

## Overview

BetSightly provides advanced football and basketball prediction APIs powered by machine learning models with explainability features.

## Base URL

```
http://localhost:8000
```

## Authentication

Currently, the API does not require authentication. Rate limiting is applied to prevent abuse.

## API Endpoints

### Health Check

#### GET `/api/health/`

Check the health status of the API.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2023-05-01T12:00:00Z",
  "version": "1.0.0",
  "database": "connected",
  "ml_models": "loaded"
}
```

### Football Predictions

#### GET `/api/predictions/`

Get football match predictions with categorization by odds.

**Parameters:**
- `date` (optional): Date in YYYY-MM-DD format. Defaults to today.
- `category` (optional): Filter by category (`2_odds`, `5_odds`, `10_odds`, `rollover`)
- `limit` (optional): Maximum predictions per category (1-100, default: 10)
- `best_only` (optional): Return only highest confidence predictions (default: false)
- `format` (optional): Response format (`detailed`, `simple`, default: `detailed`)
- `advanced` (optional): Use advanced ML models (default: false)

**Example Request:**
```bash
GET /api/predictions/?date=2023-05-01&category=2_odds&limit=5
```

**Response:**
```json
{
  "status": "success",
  "date": "2023-05-01",
  "categories": {
    "2_odds": [
      {
        "fixture": {
          "id": 12345,
          "home_team": "Manchester United",
          "away_team": "Liverpool",
          "date": "2023-05-01T15:00:00Z",
          "league": "Premier League"
        },
        "prediction": {
          "type": "Match Result",
          "prediction": "Home Win",
          "confidence": 75.5,
          "odds": 1.8,
          "explanation": "Home team has better recent form"
        }
      }
    ]
  },
  "summary": {
    "total_predictions": 5,
    "high_confidence_count": 3
  }
}
```

#### GET `/api/predictions/enhanced/`

Get enhanced predictions with explainability and meta-model stacking.

**Parameters:**
- `date` (optional): Date in YYYY-MM-DD format
- `include_explanations` (optional): Include SHAP/LIME explanations (default: true)
- `use_meta_stacking` (optional): Use meta-model stacking (default: true)
- `explanation_detail` (optional): Detail level (`human`, `technical`, `both`, default: `human`)

**Example Request:**
```bash
GET /api/predictions/enhanced/?include_explanations=true&use_meta_stacking=true
```

**Response:**
```json
{
  "status": "success",
  "date": "2023-05-01",
  "predictions": [
    {
      "fixture": {
        "id": 12345,
        "home_team": "Manchester United",
        "away_team": "Liverpool",
        "competition": "Premier League"
      },
      "predictions": {
        "match_result": {
          "prediction": "Home Win",
          "confidence": 75.5,
          "probabilities": [0.755, 0.145, 0.1],
          "method": "meta_stacking",
          "base_models": ["xgboost", "lightgbm", "neural_network"]
        },
        "over_under": {
          "prediction": "Over 2.5",
          "confidence": 68.2,
          "method": "meta_stacking"
        },
        "btts": {
          "prediction": "Yes",
          "confidence": 62.1,
          "method": "meta_stacking"
        }
      },
      "explanations": {
        "match_result": {
          "human_readable": "Home team has significantly better recent form and home advantage",
          "technical": {
            "feature_importance": {
              "home_form": 0.35,
              "away_form": 0.25,
              "h2h_record": 0.20,
              "home_advantage": 0.20
            }
          }
        }
      }
    }
  ],
  "summary": {
    "total_fixtures": 1,
    "high_confidence_predictions": 2,
    "average_confidence": 68.6,
    "meta_stacking_success_rate": 100.0
  },
  "meta_stacking_used": true,
  "explanations_included": true
}
```

#### GET `/api/predictions/{prediction_id}`

Get details for a specific prediction.

**Response:**
```json
{
  "id": 123,
  "fixture_id": 12345,
  "prediction_type": "Match Result",
  "prediction": "Home Win",
  "confidence": 75.5,
  "odds": 1.8,
  "created_at": "2023-05-01T10:00:00Z"
}
```

### Basketball Predictions

#### GET `/api/basketball-predictions/`

Get basketball match predictions (similar structure to football).

**Parameters:**
- `date` (optional): Date in YYYY-MM-DD format
- `league` (optional): Filter by league (NBA, EuroLeague, etc.)
- `limit` (optional): Maximum predictions (1-100, default: 10)

### Betting Codes

#### GET `/api/betting-codes/`

Get betting codes for predictions.

#### POST `/api/betting-codes/`

Create a new betting code.

### Fixtures

#### GET `/api/fixtures/`

Get fixture data.

**Parameters:**
- `date` (optional): Date in YYYY-MM-DD format
- `league` (optional): League ID or name

### Dashboard

#### GET `/api/dashboard/`

Get dashboard data including statistics and summaries.

## Response Formats

### Success Response
```json
{
  "status": "success",
  "data": { ... },
  "timestamp": "2023-05-01T12:00:00Z"
}
```

### Error Response
```json
{
  "status": "error",
  "message": "Error description",
  "code": "ERROR_CODE",
  "timestamp": "2023-05-01T12:00:00Z"
}
```

## Error Codes

- `400` - Bad Request: Invalid parameters
- `404` - Not Found: Resource not found
- `422` - Validation Error: Invalid input data
- `429` - Too Many Requests: Rate limit exceeded
- `500` - Internal Server Error: Server error

## Rate Limiting

- **Standard endpoints**: 100 requests per minute
- **Enhanced endpoints**: 50 requests per minute
- **Training endpoints**: 10 requests per hour

## Prediction Categories

### 2_odds (Safe Bets)
- Odds range: 1.0 - 2.0
- Minimum confidence: 50%
- Maximum predictions: 10

### 5_odds (Balanced Risk)
- Odds range: 2.0 - 5.0
- Minimum confidence: 40%
- Maximum predictions: 5

### 10_odds (High Reward)
- Odds range: 5.0 - 10.0
- Minimum confidence: 30%
- Maximum predictions: 3

### Rollover
- Odds range: 1.0 - 1.5
- Minimum confidence: 60%
- Target combined odds: 10.0

## Machine Learning Models

### Available Models
- **XGBoost**: Gradient boosting for match results
- **LightGBM**: Alternative gradient boosting
- **Neural Networks**: Deep learning models
- **LSTM**: Time series predictions
- **Meta-Stacking**: Combines multiple models

### Explainability Features
- **SHAP**: For tree-based models (XGBoost, LightGBM)
- **LIME**: For neural network models
- **Feature Importance**: Key factors in predictions
- **Human-readable explanations**: Plain English summaries

## Data Sources

- **Football-Data.org**: Primary football data
- **API-Football**: Secondary football data
- **NBA API**: Basketball data
- **Historical datasets**: Training data from GitHub

## Caching

- **Predictions**: Cached for 1 hour
- **Fixtures**: Cached for 24 hours
- **Team statistics**: Cached for 7 days
- **Historical data**: Cached for 30 days

## Examples

### Get today's safe bets
```bash
curl "http://localhost:8000/api/predictions/?category=2_odds&best_only=true"
```

### Get enhanced predictions with explanations
```bash
curl "http://localhost:8000/api/predictions/enhanced/?include_explanations=true"
```

### Get basketball predictions
```bash
curl "http://localhost:8000/api/basketball-predictions/?date=2023-05-01"
```

## SDKs and Libraries

Currently, no official SDKs are available. The API follows REST conventions and can be used with any HTTP client.

## Support

For API support, please check the logs or contact the development team.

## Changelog

### v1.0.0 (Current)
- Initial release with football predictions
- Enhanced predictions with explainability
- Basketball predictions support
- Meta-model stacking
- SHAP/LIME explanations
- Comprehensive API documentation
