"""
Test API

This script tests the API endpoints of the Football Betting Assistant.
"""

import os
import sys
import json
import logging
import requests
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# API base URL
BASE_URL = "http://localhost:8000/api"

def test_health():
    """Test the health check endpoint."""
    url = f"{BASE_URL}/health"
    
    try:
        response = requests.get(url)
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"Health check successful: {data}")
            return True
        else:
            logger.error(f"Health check failed: {response.status_code}")
            return False
    
    except Exception as e:
        logger.error(f"Error testing health check: {str(e)}")
        return False

def test_daily_predictions():
    """Test the daily predictions endpoint."""
    url = f"{BASE_URL}/predictions/daily"
    
    try:
        logger.info("Fetching daily predictions...")
        response = requests.get(url)
        
        if response.status_code == 200:
            data = response.json()
            
            # Print summary
            logger.info("Daily predictions fetched successfully")
            logger.info(f"2 odds: {len(data.get('2_odds', []))} predictions")
            logger.info(f"5 odds: {len(data.get('5_odds', []))} predictions")
            logger.info(f"10 odds: {len(data.get('10_odds', []))} predictions")
            logger.info(f"Rollover: {len(data.get('rollover', []))} predictions")
            
            # Save to file
            output_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 
                                      f"predictions_{datetime.now().strftime('%Y-%m-%d')}.json")
            
            with open(output_file, "w") as f:
                json.dump(data, f, indent=2)
            
            logger.info(f"Predictions saved to {output_file}")
            
            return True
        else:
            logger.error(f"Failed to fetch daily predictions: {response.status_code}")
            return False
    
    except Exception as e:
        logger.error(f"Error testing daily predictions: {str(e)}")
        return False

def test_formatted_predictions():
    """Test the formatted predictions endpoint."""
    url = f"{BASE_URL}/predictions/formatted"
    
    try:
        logger.info("Fetching formatted predictions...")
        response = requests.get(url)
        
        if response.status_code == 200:
            data = response.json()
            
            # Print formatted predictions
            logger.info("Formatted predictions fetched successfully")
            
            logger.info("\n🔹 Best 2 Picks:")
            for i, pred in enumerate(data.get("2_odds", [])):
                logger.info(pred)
            
            logger.info("\n🔹 Best 5 Picks:")
            for i, pred in enumerate(data.get("5_odds", [])):
                logger.info(pred)
            
            logger.info("\n🔹 Best 10 Picks:")
            for i, pred in enumerate(data.get("10_odds", [])):
                logger.info(pred)
            
            logger.info("\n🔁 3-Odds Rollover Ticket:")
            for i, pred in enumerate(data.get("rollover", {}).get("predictions", [])):
                logger.info(pred)
            
            combined_odds = data.get("rollover", {}).get("combined_odds", 0)
            logger.info(f"Combined Odds ≈ {combined_odds} {'✅' if 2.9 <= combined_odds <= 3.1 else ''}")
            
            return True
        else:
            logger.error(f"Failed to fetch formatted predictions: {response.status_code}")
            return False
    
    except Exception as e:
        logger.error(f"Error testing formatted predictions: {str(e)}")
        return False

def main():
    """Main function to test all endpoints."""
    logger.info("Testing Football Betting Assistant API...")
    
    # Test health check
    if not test_health():
        logger.error("Health check failed. Make sure the server is running.")
        return
    
    # Test daily predictions
    test_daily_predictions()
    
    # Test formatted predictions
    test_formatted_predictions()
    
    logger.info("API tests completed")

if __name__ == "__main__":
    main()
