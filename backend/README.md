# Football Betting Assistant Backend

This is the backend for the Football Betting Assistant, a machine learning-powered system for predicting football match outcomes.

## Features

- Fetches today's football fixtures from API-Football
- Uses machine learning models to predict match outcomes
- Provides predictions for different odds categories (2 odds, 5 odds, 10 odds)
- Generates rollover predictions for accumulator bets
- RESTful API for accessing predictions

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

The system uses real football data from the schochastics/football-data GitHub repository to train the machine learning models:

1. Fetch historical data:

   ```
   python scripts/fetch_football_data_github.py
   ```

   This script downloads and processes football match data from the schochastics/football-data GitHub repository, which contains over 1.2 million matches from 207 domestic leagues and 20 tournaments. The data is in Parquet format, which is very fast to load and process.

2. Train the models:
   ```
   python scripts/train_ml_models.py
   ```
   This script trains machine learning models (Random Forest, XGBoost) on the historical data to predict match outcomes, over/under goals, and both teams to score.

#### Why schochastics/football-data?

- **Comprehensive Dataset**: Contains 1.2M+ matches from 207 domestic leagues + 20 tournaments
- **Clean Parquet Format**: Very fast to load with Python using pandas or pyarrow
- **Structured and Ready-to-Train**: Almost no cleaning needed
- **Complete Features**: Includes all key features like team names, goals, dates, match types

### Using Real-Time Data

The system fetches today's fixtures from API-Football in real-time:

1. When you access the predictions endpoints, the system automatically fetches today's fixtures
2. The ML models analyze these fixtures and generate predictions
3. All data is cached in the database to minimize API calls
4. Predictions are updated periodically to reflect the latest data

## Running the Application

To start the backend server:

```
python start_server.py
```

The API will be available at http://localhost:8000

### Efficient API Usage

The system is designed to minimize API calls to stay within the free tier limits (100 calls/day for API-Football):

1. **Database Caching**: All fixtures and predictions are stored in the database to minimize API calls
2. **File Caching**: API responses are cached in files with appropriate expiration times
3. **Rate Limiting**: The system tracks API calls and implements delays to avoid hitting rate limits
4. **Prioritized Data Sources**: The system first checks the database, then file cache, before making API calls

This approach ensures that even with the free tier API limits, the system can provide reliable predictions.

## API Documentation

Once the application is running, you can access the API documentation at:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Available Endpoints

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
