#!/bin/bash
# Run FastAPI application

# Install required packages if not already installed
pip install fastapi uvicorn sqlalchemy

# Run the application
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
