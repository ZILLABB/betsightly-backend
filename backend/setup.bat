@echo off
echo Setting up Football Betting Assistant Backend...

:: Create virtual environment
echo Creating virtual environment...
python -m venv venv

:: Activate virtual environment
call venv\Scripts\activate

:: Install dependencies
echo Installing dependencies...
pip install -r requirements.txt

:: Create necessary directories
echo Creating directories...
if not exist cache mkdir cache
if not exist data mkdir data
if not exist data\historical mkdir data\historical
if not exist models mkdir models

echo Setup completed successfully!
echo.
echo To start the backend server, run: start_backend.bat
echo.

pause
