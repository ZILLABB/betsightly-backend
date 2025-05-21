#!/bin/bash
# Daily predictions script
# Run this script daily to fetch fixtures and make predictions

# Set environment variables
export API_FOOTBALL_KEY="f486427076msh6a88663abedebbcp15f9c4jsn3ae4c457ef73"

# Get current date
DATE=$(date +%Y-%m-%d)

# Set leagues
LEAGUES="39,140,135,78,61"

# Set output file
OUTPUT_DIR="predictions"
mkdir -p $OUTPUT_DIR
OUTPUT_FILE="$OUTPUT_DIR/predictions_$DATE.csv"

# Run prediction script
echo "Running predictions for $DATE..."
python3 scripts/predict_with_github_models.py --date $DATE --leagues $LEAGUES --output $OUTPUT_FILE

# Check database
echo "Checking database content..."
python3 scripts/check_db.py

echo "Daily predictions completed."
