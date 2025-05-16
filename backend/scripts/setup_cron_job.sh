#!/bin/bash
# Setup cron job for daily predictions

# Get the absolute path to the project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Create the cron job command
CRON_CMD="0 6 * * * cd $PROJECT_DIR && API_FOOTBALL_KEY=f486427076msh6a88663abedebbcp15f9c4jsn3ae4c457ef73 python3 scripts/daily_predictions_production.py --date \$(date +\%Y-\%m-\%d) --leagues 39,140,135,78,61 --output results/predictions_\$(date +\%Y-\%m-\%d).csv >> logs/cron_\$(date +\%Y-\%m-\%d).log 2>&1"

# Check if cron job already exists
EXISTING_CRON=$(crontab -l 2>/dev/null | grep -F "$PROJECT_DIR/scripts/daily_predictions_production.py" || true)

if [ -n "$EXISTING_CRON" ]; then
    echo "Cron job already exists:"
    echo "$EXISTING_CRON"
    echo "Do you want to replace it? (y/n)"
    read -r REPLACE
    if [ "$REPLACE" != "y" ]; then
        echo "Exiting without changes."
        exit 0
    fi
    
    # Remove existing cron job
    crontab -l 2>/dev/null | grep -v "$PROJECT_DIR/scripts/daily_predictions_production.py" | crontab -
fi

# Add new cron job
(crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -

echo "Cron job added successfully!"
echo "The script will run daily at 6:00 AM."
echo "Cron command:"
echo "$CRON_CMD"
