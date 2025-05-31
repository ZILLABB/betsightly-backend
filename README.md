# BetSightly Backend

This repository contains the backend code for the BetSightly application, a sports prediction platform.

## Getting Started

### Prerequisites

- Python 3.9+
- pip

### Installation

1. Clone the repository

   ```bash
   git clone https://github.com/ZILLABB/betsightly-backend.git
   cd betsightly-backend
   ```

2. Create a virtual environment

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies

   ```bash
   pip install -r requirements.txt
   ```

4. Create a `.env` file based on `.env.example`

   ```bash
   cp .env.example .env
   # Edit .env with your API keys and configuration
   ```

   **⚠️ IMPORTANT**: You must set the following environment variables:
   - `FOOTBALL_DATA_KEY`: Your Football-Data.org API key
   - `API_FOOTBALL_KEY`: Your API-Football API key

5. Test the installation

   ```bash
   python test_fixes.py
   ```

6. Start the development server
   ```bash
   python start_production.py --reload
   ```

   Or use the traditional method:
   ```bash
   uvicorn main:app --reload
   ```

## Project Structure

```
betsightly-backend/
├── app/                  # Main application code
│   ├── api/              # API endpoints
│   ├── ml/               # Machine learning models
│   ├── models/           # Database models
│   ├── schemas/          # Pydantic schemas
│   ├── services/         # Business logic
│   └── utils/            # Utility functions
├── cache/                # Cache files
├── data/                 # Data files
├── models/               # Trained ML models
├── scripts/              # Utility scripts
└── tests/                # Test files
```

## API Documentation

When the server is running, you can access the API documentation at:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Health Monitoring

The application includes comprehensive health check endpoints:

- Basic health: `GET /api/health/`
- Detailed health: `GET /api/health/detailed`
- Readiness check: `GET /api/health/ready`
- Liveness check: `GET /api/health/live`

## Security & Performance Improvements

This version includes several critical fixes:

### Security Fixes ✅
- Removed all hardcoded API keys
- Implemented secure environment variable loading
- Restricted CORS configuration
- Added comprehensive error handling

### Performance Improvements ✅
- Database query optimization with proper indexing
- Caching for frequently accessed data
- Optimized database session handling
- N+1 query prevention

### Stability Improvements ✅
- Fixed uninitialized model factory issues
- Proper database session lifecycle management
- Comprehensive error handling and logging
- Health checks for all critical components

## Development

### Running Tests

```bash
pytest
```

### Database Migrations

The application uses SQLite by default. The database is automatically created and migrated on startup.

## Deployment

The application can be deployed using Docker:

```bash
docker build -t betsightly-backend .
docker run -p 8000:8000 -d betsightly-backend
```

## Environment Variables

- `API_FOOTBALL_KEY`: API key for the Football API
- `API_FOOTBALL_HOST`: Host for the Football API
- `DEBUG`: Enable debug mode (True/False)
- `ENVIRONMENT`: Environment (development/production)
- `DATABASE_URL`: Database connection string
- `FOOTBALL_DATA_KEY`: API key for Football Data API

## License

This project is proprietary and confidential.
