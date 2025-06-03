#!/bin/bash
# Setup cron jobs for daily cache generation and weekly training

# Get the absolute path to the project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Create log directory
mkdir -p "$PROJECT_DIR/logs"

# Daily prediction cache generation (6 AM UTC every day)
DAILY_CACHE_CMD="0 6 * * * cd $PROJECT_DIR && python3 scripts/daily_cache_scheduler.py --task cache >> logs/daily_cache_\$(date +\%Y-\%m-\%d).log 2>&1"

# Weekly model training with GitHub data (Sundays at 2 AM UTC)
WEEKLY_TRAINING_CMD="0 2 * * 0 cd $PROJECT_DIR && python3 scripts/daily_cache_scheduler.py --task training >> logs/weekly_training_\$(date +\%Y-\%m-\%d).log 2>&1"

# Daily cache maintenance (Midnight UTC)
DAILY_MAINTENANCE_CMD="0 0 * * * cd $PROJECT_DIR && python3 scripts/daily_cache_scheduler.py --task maintenance >> logs/maintenance_\$(date +\%Y-\%m-\%d).log 2>&1"

# System health check (Every 6 hours)
HEALTH_CHECK_CMD="0 */6 * * * cd $PROJECT_DIR && python3 scripts/daily_cache_scheduler.py --task health >> logs/health_check_\$(date +\%Y-\%m-\%d).log 2>&1"

# Check if cron jobs already exist
EXISTING_CACHE=$(crontab -l 2>/dev/null | grep -F "daily_cache_scheduler.py" || true)

if [ -n "$EXISTING_CACHE" ]; then
    echo "BetSightly cron jobs already exist:"
    echo "$EXISTING_CACHE"
    echo "Do you want to replace them? (y/n)"
    read -r REPLACE
    if [ "$REPLACE" != "y" ]; then
        echo "Exiting without changes."
        exit 0
    fi

    # Remove existing BetSightly cron jobs
    crontab -l 2>/dev/null | grep -v "daily_cache_scheduler.py" | crontab -
fi

# Add new cron jobs
(crontab -l 2>/dev/null; echo "$DAILY_CACHE_CMD") | crontab -
(crontab -l 2>/dev/null; echo "$WEEKLY_TRAINING_CMD") | crontab -
(crontab -l 2>/dev/null; echo "$DAILY_MAINTENANCE_CMD") | crontab -
(crontab -l 2>/dev/null; echo "$HEALTH_CHECK_CMD") | crontab -

echo "✅ BetSightly cron jobs added successfully!"
echo ""
echo "📅 Scheduled tasks:"
echo "  - Daily prediction caching: 6:00 AM UTC (every day)"
echo "  - Weekly model training: Sundays at 2:00 AM UTC (GitHub data)"
echo "  - Daily cache maintenance: Midnight UTC"
echo "  - System health checks: Every 6 hours"
echo ""
echo "📊 Training data sources:"
echo "  - Football: GitHub dataset (50,000+ matches) + live results"
echo "  - Basketball: GitHub dataset + recent games"
echo ""
echo "📁 Logs will be saved to: $PROJECT_DIR/logs/"
echo ""
echo "🔧 To view current cron jobs: crontab -l"
echo "🗑️  To remove cron jobs: crontab -e"
