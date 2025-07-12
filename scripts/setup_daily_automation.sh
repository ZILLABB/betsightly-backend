#!/bin/bash
"""
Setup Daily Automation for BetSightly
Configures cron jobs for daily result correlation and performance tracking
"""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Project directory
PROJECT_DIR="/home/kali/Desktop/betsightly-backend"
VENV_PATH="$PROJECT_DIR/.venv"
PYTHON_PATH="$VENV_PATH/bin/python"

echo -e "${BLUE}🚀 Setting up BetSightly Daily Automation${NC}"
echo "=================================================="

# Check if virtual environment exists
if [ ! -d "$VENV_PATH" ]; then
    echo -e "${RED}❌ Virtual environment not found at $VENV_PATH${NC}"
    exit 1
fi

# Check if Python script exists
if [ ! -f "$PROJECT_DIR/scripts/daily_result_correlation_runner.py" ]; then
    echo -e "${RED}❌ Daily correlation script not found${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Prerequisites check passed${NC}"

# Create cron job entries
CRON_DAILY_CORRELATION="0 9 * * * cd $PROJECT_DIR && $PYTHON_PATH scripts/daily_result_correlation_runner.py >> logs/daily_correlation.log 2>&1"
CRON_WEEKLY_SUMMARY="0 8 * * 1 cd $PROJECT_DIR && $PYTHON_PATH scripts/daily_result_correlation_runner.py --weekly >> logs/weekly_summary.log 2>&1"

# Create logs directory if it doesn't exist
mkdir -p "$PROJECT_DIR/logs"

echo -e "${YELLOW}📋 Proposed Cron Jobs:${NC}"
echo "1. Daily Result Correlation (9:00 AM daily):"
echo "   $CRON_DAILY_CORRELATION"
echo ""
echo "2. Weekly Performance Summary (8:00 AM Mondays):"
echo "   $CRON_WEEKLY_SUMMARY"
echo ""

# Function to add cron job
add_cron_job() {
    local job="$1"
    local description="$2"
    
    # Check if job already exists
    if crontab -l 2>/dev/null | grep -q "$job"; then
        echo -e "${YELLOW}⚠️  $description already exists in crontab${NC}"
        return 0
    fi
    
    # Add job to crontab
    (crontab -l 2>/dev/null; echo "$job") | crontab -
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ Added $description to crontab${NC}"
        return 0
    else
        echo -e "${RED}❌ Failed to add $description to crontab${NC}"
        return 1
    fi
}

# Ask user for confirmation
echo -e "${BLUE}❓ Do you want to add these cron jobs? (y/n):${NC}"
read -r response

if [[ "$response" =~ ^[Yy]$ ]]; then
    echo -e "${BLUE}📅 Adding cron jobs...${NC}"
    
    add_cron_job "$CRON_DAILY_CORRELATION" "Daily Result Correlation"
    add_cron_job "$CRON_WEEKLY_SUMMARY" "Weekly Performance Summary"
    
    echo ""
    echo -e "${GREEN}🎉 Automation setup complete!${NC}"
    echo ""
    echo -e "${BLUE}📊 Current crontab:${NC}"
    crontab -l
    
    echo ""
    echo -e "${YELLOW}📋 What happens now:${NC}"
    echo "• Daily at 9:00 AM: Fetch match results and correlate with predictions"
    echo "• Weekly on Mondays at 8:00 AM: Generate performance summary"
    echo "• Logs will be saved to: $PROJECT_DIR/logs/"
    echo ""
    echo -e "${BLUE}🔧 Manual testing:${NC}"
    echo "Test daily correlation:"
    echo "  cd $PROJECT_DIR && $PYTHON_PATH scripts/daily_result_correlation_runner.py --verbose"
    echo ""
    echo "Test weekly summary:"
    echo "  cd $PROJECT_DIR && $PYTHON_PATH scripts/daily_result_correlation_runner.py --weekly --verbose"
    
else
    echo -e "${YELLOW}⏭️  Skipping cron job setup${NC}"
    echo ""
    echo -e "${BLUE}🔧 Manual setup instructions:${NC}"
    echo "To add cron jobs manually, run:"
    echo "  crontab -e"
    echo ""
    echo "Then add these lines:"
    echo "  $CRON_DAILY_CORRELATION"
    echo "  $CRON_WEEKLY_SUMMARY"
fi

echo ""
echo -e "${GREEN}✅ Setup script completed${NC}"
