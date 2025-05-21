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

5. Start the development server
   ```bash
   uvicorn app.main:app --reload
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
