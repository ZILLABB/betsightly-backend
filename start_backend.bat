@echo off
echo Starting Football Betting Assistant Backend...

:: Activate virtual environment if it exists
if exist venv\Scripts\activate (
    call venv\Scripts\activate
) else (
    echo Virtual environment not found. Creating one...
    python -m venv venv
    call venv\Scripts\activate
    pip install -r requirements.txt
)

:: Create cache directory if it doesn't exist
if not exist cache mkdir cache

:: Run the application
python run.py

pause
