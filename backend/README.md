# Football Betting Assistant Backend

This is the backend for the Football Betting Assistant, a machine learning-powered system for predicting football match outcomes with high accuracy.

## Features

- **Match Result Prediction**: Predicts home win, draw, or away win with 85% accuracy
- **Over/Under 2.5 Goals**: Predicts over or under 2.5 goals with 74% accuracy
- **Both Teams To Score (BTTS)**: Predicts whether both teams will score with 66% accuracy
- **Confidence Levels**: Provides confidence scores for each prediction
- **Database Storage**: Stores fixtures and predictions for easy access
- **API Endpoints**: Access predictions through a RESTful API
- **Daily Predictions**: Automatically fetches fixtures and makes predictions daily
- Provides predictions for different odds categories (2 odds, 5 odds, 10 odds)
- Generates rollover predictions for accumulator bets

## Project Structure

```
backend/
├── app/
│   ├── database/         # Database models and utilities
│   ├── ml/               # Machine learning models
│   ├── models/           # Pydantic models
│   ├── routers/          # API routes
│   ├── services/         # Business logic
│   ├── config.py         # Configuration settings
│   └── main.py           # FastAPI application
├── data/
│   └── historical/       # Historical match data
├── models/               # Trained ML models
├── scripts/              # Utility scripts
├── requirements.txt      # Python dependencies
└── run.py                # Script to run the application
```

## Setup

### Prerequisites

- Python 3.9 or higher
- API-Football API key (from RapidAPI)

### Installation

1. Create a virtual environment:

   ```
   python -m venv venv
   ```

2. Activate the virtual environment:

   - Windows:
     ```
     venv\Scripts\activate
     ```
   - Linux/Mac:
     ```
     source venv/bin/activate
     ```

3. Install dependencies:

   ```
   pip install -r requirements.txt
   ```

4. Set up your API key:
   - Create a `.env` file in the root directory
   - Add your API-Football key:
     ```
     API_FOOTBALL_KEY=your_api_key_here
     API_FOOTBALL_HOST=api-football-v1.p.rapidapi.com
     ```

### Training the ML Models

The system uses real football data from the Club-Football-Match-Data-2000-2025 GitHub repository to train the machine learning models:

1. The data is automatically downloaded when you run the training scripts.

2. Train the basic models:
   ```
   python scripts/train_github_models.py --start_year 2018 --end_year 2024 --leagues E0,SP1,I1,D1,F1
   ```

3. Train the enhanced ensemble models (recommended):
   ```
   python scripts/train_enhanced_github_models.py --start_year 2015 --end_year 2024 --leagues E0,SP1,I1,D1,F1 --ensemble
   ```

4. Evaluate model performance:
   ```
   python scripts/evaluate_models.py --start_year 2023 --end_year 2024 --leagues E0,SP1,I1,D1,F1
   ```

#### Enhanced Ensemble Models

Our enhanced ensemble models combine multiple algorithms to achieve superior prediction accuracy:

- **Random Forest**: Excellent for handling non-linear relationships
- **Gradient Boosting**: Provides high precision for specific outcomes
- **Logistic Regression**: Adds stability and interpretability

The ensemble approach achieves significantly better results than single models:

- **Match Result**: 85.01% accuracy (99.35% for high-confidence predictions)
- **Over/Under 2.5 Goals**: 74.17% accuracy (98.79% for high-confidence predictions)
- **Both Teams To Score (BTTS)**: 64.77% accuracy (91.53% for high-confidence predictions)

#### Why Club-Football-Match-Data-2000-2025?

- **Comprehensive Dataset**: Contains matches from top European leagues from 2000-2025
- **Rich Feature Set**: Includes form data, Elo ratings, and detailed statistics
- **Clean Structure**: Well-organized and consistent data format
- **Regular Updates**: Continuously updated with new matches

### Using Real-Time Data

The system fetches today's fixtures from API-Football in real-time:

1. When you access the predictions endpoints, the system automatically fetches today's fixtures
2. The ML models analyze these fixtures and generate predictions
3. All data is cached in the database to minimize API calls
4. Predictions are updated periodically to reflect the latest data

## Running the Application

### Starting the API Server

To start the backend server:

```bash
./scripts/run_api.sh
```

The API will be available at http://localhost:8000

### Setting Up Daily Predictions

Set up a cron job to run predictions daily:

```bash
./scripts/setup_cron_job.sh
```

This will schedule the prediction script to run daily at 6:00 AM, fetching fixtures and making predictions automatically.

### Running Predictions Manually

You can also run predictions manually:

```bash
# Make predictions for today
API_FOOTBALL_KEY=your_api_key_here python scripts/daily_predictions_production.py

# Make predictions for a specific date
API_FOOTBALL_KEY=your_api_key_here python scripts/daily_predictions_production.py --date 2024-05-18
```

### Efficient API Usage

The system is designed to minimize API calls to stay within the free tier limits (100 calls/day for API-Football):

1. **Database Caching**: All fixtures and predictions are stored in the database to minimize API calls
2. **File Caching**: API responses are cached in files with appropriate expiration times
3. **Rate Limiting**: The system adds a 1.2-second delay between requests to avoid hitting rate limits
4. **Error Handling**: The system detects 429 (Too Many Requests) errors and waits 60 seconds before retrying
5. **Prioritized Data Sources**: The system first checks the database, then file cache, before making API calls

This approach ensures that even with the free tier API limits, the system can provide reliable predictions.

### Rate Limit Resets

API-Football rate limits reset at midnight UTC each day. If you hit the rate limit, you'll need to wait until then for it to reset.

## API Documentation

Once the application is running, you can access the API documentation at:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Available Endpoints

### Fixtures

- `GET /api/fixtures`: Get fixtures for today
- `GET /api/fixtures?date=2024-05-18`: Get fixtures for a specific date
- `GET /api/fixtures/{fixture_id}`: Get a specific fixture
- `GET /api/fixtures/{fixture_id}/prediction`: Get prediction for a specific fixture

### Predictions

- `GET /api/predictions`: Get predictions for today
- `GET /api/predictions?date=2024-05-18`: Get predictions for a specific date
- `GET /api/predictions/{prediction_id}`: Get a specific prediction

### Dashboard

- `GET /api/dashboard/summary`: Get summary statistics for today
- `GET /api/dashboard/summary?date=2024-05-18`: Get summary for a specific date
- `GET /api/dashboard/high-confidence`: Get high-confidence predictions for today
- `GET /api/dashboard/high-confidence?date=2024-05-18&confidence_threshold=0.8`: Get high-confidence predictions with custom threshold

### Legacy Endpoints

- `GET /api/health` - Health check endpoint
- `GET /api/predictions/daily` - Get daily predictions grouped by odds category
- `GET /api/predictions/category/{category}` - Get predictions for a specific category
- `GET /api/predictions/fixtures` - Get today's fixtures
- `GET /api/predictions/formatted` - Get formatted predictions for display

## Prediction Categories

The system provides predictions for the following categories:

### 2 Best Picks

- Top 2 matches with the highest model confidence
- Only includes picks with odds ≥ 1.50 and confidence ≥ 80%

### 5 Best Picks

- 5 high-value picks based on expected value (confidence × odds)
- Odds ideally between 1.5 and 2.5
- Safe markets like 1X2 or Over 1.5/2.5

### 10 Best Picks

- Top 10 predictions ranked by confidence score
- Odds between 1.5 and 3.0
- Consistency with recent form

### 3-Odds Rollover Ticket

- 2 or 3 predictions whose combined odds ≈ 3.00
- Each pick has confidence ≥ 75%
- Simple markets like Home Win, Over 1.5, or Double Chance
