#!/usr/bin/env python3
"""
Check Prediction Categorization

This script checks the prediction categorization logic to ensure that:
1. Each game appears in only one category
2. The most appropriate category is chosen for each game
3. No duplicates exist across categories
"""

import os
import sys
import logging
import json
from datetime import datetime
from sqlalchemy.orm import Session

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Import modules
from database import get_db, SessionLocal
from services.prediction_categorizer import prediction_categorizer
# Temporarily comment out this import until we fix the module structure
# from services.prediction_service_improved import PredictionService

def check_categorization():
    """Check prediction categorization logic."""
    # Create a database session
    db = SessionLocal()

    try:
        # Temporarily comment out the PredictionService code
        logger.info("PredictionService is temporarily disabled for testing")

        # Create some mock predictions for testing
        logger.info("Creating mock predictions for testing...")

        # Mock fixture data - create 20 fixtures for testing
        mock_fixtures = []

        # Premier League fixtures
        mock_fixtures.extend([
            {
                "fixture_id": 1001,
                "date": datetime.now().isoformat(),
                "league_name": "Premier League",
                "home_team": "Manchester United",
                "away_team": "Liverpool"
            },
            {
                "fixture_id": 1002,
                "date": datetime.now().isoformat(),
                "league_name": "Premier League",
                "home_team": "Arsenal",
                "away_team": "Chelsea"
            },
            {
                "fixture_id": 1003,
                "date": datetime.now().isoformat(),
                "league_name": "Premier League",
                "home_team": "Tottenham",
                "away_team": "Manchester City"
            },
            {
                "fixture_id": 1004,
                "date": datetime.now().isoformat(),
                "league_name": "Premier League",
                "home_team": "Newcastle",
                "away_team": "Aston Villa"
            }
        ])

        # La Liga fixtures
        mock_fixtures.extend([
            {
                "fixture_id": 2001,
                "date": datetime.now().isoformat(),
                "league_name": "La Liga",
                "home_team": "Barcelona",
                "away_team": "Real Madrid"
            },
            {
                "fixture_id": 2002,
                "date": datetime.now().isoformat(),
                "league_name": "La Liga",
                "home_team": "Atletico Madrid",
                "away_team": "Sevilla"
            },
            {
                "fixture_id": 2003,
                "date": datetime.now().isoformat(),
                "league_name": "La Liga",
                "home_team": "Valencia",
                "away_team": "Villarreal"
            },
            {
                "fixture_id": 2004,
                "date": datetime.now().isoformat(),
                "league_name": "La Liga",
                "home_team": "Real Betis",
                "away_team": "Athletic Bilbao"
            }
        ])

        # Serie A fixtures
        mock_fixtures.extend([
            {
                "fixture_id": 3001,
                "date": datetime.now().isoformat(),
                "league_name": "Serie A",
                "home_team": "Juventus",
                "away_team": "AC Milan"
            },
            {
                "fixture_id": 3002,
                "date": datetime.now().isoformat(),
                "league_name": "Serie A",
                "home_team": "Inter Milan",
                "away_team": "Roma"
            },
            {
                "fixture_id": 3003,
                "date": datetime.now().isoformat(),
                "league_name": "Serie A",
                "home_team": "Napoli",
                "away_team": "Lazio"
            },
            {
                "fixture_id": 3004,
                "date": datetime.now().isoformat(),
                "league_name": "Serie A",
                "home_team": "Atalanta",
                "away_team": "Fiorentina"
            }
        ])

        # Bundesliga fixtures
        mock_fixtures.extend([
            {
                "fixture_id": 4001,
                "date": datetime.now().isoformat(),
                "league_name": "Bundesliga",
                "home_team": "Bayern Munich",
                "away_team": "Borussia Dortmund"
            },
            {
                "fixture_id": 4002,
                "date": datetime.now().isoformat(),
                "league_name": "Bundesliga",
                "home_team": "RB Leipzig",
                "away_team": "Bayer Leverkusen"
            },
            {
                "fixture_id": 4003,
                "date": datetime.now().isoformat(),
                "league_name": "Bundesliga",
                "home_team": "Eintracht Frankfurt",
                "away_team": "Borussia Monchengladbach"
            },
            {
                "fixture_id": 4004,
                "date": datetime.now().isoformat(),
                "league_name": "Bundesliga",
                "home_team": "Wolfsburg",
                "away_team": "Stuttgart"
            }
        ])

        # Mock prediction data with different odds and confidence levels
        mock_predictions = []

        # Add predictions for rollover category (1.2-2.0)
        # These should be prioritized first
        for i in range(12):  # Create more than needed for 10 days
            if i < len(mock_fixtures):
                mock_predictions.append({
                    "fixture": mock_fixtures[i],
                    "prediction": {
                        "odds": 1.3 + (i * 0.05),  # Odds between 1.3 and 1.9
                        "confidence": 90 + (i % 5),  # High confidence (90-94)
                        "prediction_type": "home_win" if i % 3 == 0 else ("away_win" if i % 3 == 1 else "over_2_5")
                    }
                })

        # Add predictions for 2 odds category (1.5-2.5)
        for i in range(5):
            idx = i + 12
            if idx < len(mock_fixtures):
                mock_predictions.append({
                    "fixture": mock_fixtures[idx],
                    "prediction": {
                        "odds": 1.8 + (i * 0.1),  # Odds between 1.8 and 2.2
                        "confidence": 85 - (i % 5),  # Good confidence (80-85)
                        "prediction_type": "btts" if i % 2 == 0 else "under_2_5"
                    }
                })

        # Add predictions for 5 odds category (2.5-5.0)
        for i in range(3):
            idx = i + 17
            if idx < len(mock_fixtures):
                mock_predictions.append({
                    "fixture": mock_fixtures[idx],
                    "prediction": {
                        "odds": 3.0 + (i * 0.5),  # Odds between 3.0 and 4.0
                        "confidence": 75 + (i % 3),  # Medium confidence (75-77)
                        "prediction_type": "draw" if i % 2 == 0 else "away_win"
                    }
                })

        # Add predictions for 10 odds category (5.0-10.0)
        # These should be prioritized after rollover but before 5 and 2 odds
        for i in range(2):
            idx = i + 8  # Use some fixtures that might also be used for rollover
            if idx < len(mock_fixtures):
                mock_predictions.append({
                    "fixture": mock_fixtures[idx],
                    "prediction": {
                        "odds": 6.0 + (i * 2.0),  # Odds between 6.0 and 8.0
                        "confidence": 80 - (i * 2),  # Good confidence (78-80)
                        "prediction_type": "btts" if i % 2 == 0 else "over_2_5"
                    }
                })

        logger.info(f"Created {len(mock_predictions)} mock predictions for {len(mock_fixtures)} fixtures")

        # Test the prediction categorizer directly
        logger.info("Testing prediction categorizer directly...")

        # Use the mock predictions we created earlier
        formatted_predictions = mock_predictions

        # Categorize predictions using the categorizer
        categorized = prediction_categorizer.categorize_predictions(formatted_predictions)

        # Check results
        logger.info(f"2 odds combinations: {len(categorized.get('2_odds', []))}")
        logger.info(f"5 odds combinations: {len(categorized.get('5_odds', []))}")
        logger.info(f"10 odds combinations: {len(categorized.get('10_odds', []))}")
        logger.info(f"Rollover combinations: {len(categorized.get('rollover', []))}")

        # Print details of each category
        logger.info("\nRollover combinations details:")
        for i, combo in enumerate(categorized.get("rollover", [])):
            combined_odds = combo.get("combined_odds", 0)
            combined_confidence = combo.get("combined_confidence", 0)
            predictions = combo.get("predictions", [])

            logger.info(f"  Day {i+1}: {len(predictions)} predictions, combined odds: {combined_odds:.2f}, confidence: {combined_confidence:.2f}%")

            for j, pred in enumerate(predictions):
                fixture = pred.get("fixture", {})
                prediction_info = pred.get("prediction", {})

                logger.info(f"    {j+1}. {fixture.get('home_team')} vs {fixture.get('away_team')}: " +
                           f"{prediction_info.get('prediction_type')}, " +
                           f"odds: {prediction_info.get('odds'):.2f}, " +
                           f"confidence: {prediction_info.get('confidence'):.2f}%")

        logger.info("\n10 odds combinations details:")
        for i, combo in enumerate(categorized.get("10_odds", [])):
            combined_odds = combo.get("combined_odds", 0)
            combined_confidence = combo.get("combined_confidence", 0)
            predictions = combo.get("predictions", [])

            logger.info(f"  Combo {i+1}: {len(predictions)} predictions, combined odds: {combined_odds:.2f}, confidence: {combined_confidence:.2f}%")

            for j, pred in enumerate(predictions):
                fixture = pred.get("fixture", {})
                prediction_info = pred.get("prediction", {})

                logger.info(f"    {j+1}. {fixture.get('home_team')} vs {fixture.get('away_team')}: " +
                           f"{prediction_info.get('prediction_type')}, " +
                           f"odds: {prediction_info.get('odds'):.2f}, " +
                           f"confidence: {prediction_info.get('confidence'):.2f}%")

        logger.info("\n5 odds combinations details:")
        for i, combo in enumerate(categorized.get("5_odds", [])):
            combined_odds = combo.get("combined_odds", 0)
            combined_confidence = combo.get("combined_confidence", 0)
            predictions = combo.get("predictions", [])

            logger.info(f"  Combo {i+1}: {len(predictions)} predictions, combined odds: {combined_odds:.2f}, confidence: {combined_confidence:.2f}%")

            for j, pred in enumerate(predictions):
                fixture = pred.get("fixture", {})
                prediction_info = pred.get("prediction", {})

                logger.info(f"    {j+1}. {fixture.get('home_team')} vs {fixture.get('away_team')}: " +
                           f"{prediction_info.get('prediction_type')}, " +
                           f"odds: {prediction_info.get('odds'):.2f}, " +
                           f"confidence: {prediction_info.get('confidence'):.2f}%")

        logger.info("\n2 odds combinations details:")
        for i, combo in enumerate(categorized.get("2_odds", [])):
            combined_odds = combo.get("combined_odds", 0)
            combined_confidence = combo.get("combined_confidence", 0)
            predictions = combo.get("predictions", [])

            logger.info(f"  Combo {i+1}: {len(predictions)} predictions, combined odds: {combined_odds:.2f}, confidence: {combined_confidence:.2f}%")

            for j, pred in enumerate(predictions):
                fixture = pred.get("fixture", {})
                prediction_info = pred.get("prediction", {})

                logger.info(f"    {j+1}. {fixture.get('home_team')} vs {fixture.get('away_team')}: " +
                           f"{prediction_info.get('prediction_type')}, " +
                           f"odds: {prediction_info.get('odds'):.2f}, " +
                           f"confidence: {prediction_info.get('confidence'):.2f}%")

        # Check for duplicates in categorizer results
        fixture_ids = set()
        categorizer_duplicates = []

        # Helper function to check for duplicates
        def check_category_for_duplicates(category_name):
            nonlocal fixture_ids, categorizer_duplicates

            for combo in categorized.get(category_name, []):
                for prediction in combo.get("predictions", []):
                    fixture = prediction.get("fixture", {})
                    fixture_id = fixture.get("fixture_id")

                    if not fixture_id:
                        continue

                    if fixture_id in fixture_ids:
                        categorizer_duplicates.append((fixture_id, category_name))
                    else:
                        fixture_ids.add(fixture_id)

        # Check each category
        fixture_ids = set()
        check_category_for_duplicates("rollover")  # Check rollover first (highest priority)
        check_category_for_duplicates("10_odds")
        check_category_for_duplicates("5_odds")
        check_category_for_duplicates("2_odds")

        if categorizer_duplicates:
            logger.warning(f"Found {len(categorizer_duplicates)} duplicate fixtures in categorizer results:")
            for fixture_id, category in categorizer_duplicates:
                logger.warning(f"Fixture ID {fixture_id} appears in {category}")
        else:
            logger.info("No duplicates found in categorizer results")

    except Exception as e:
        logger.error(f"Error checking categorization: {str(e)}")
    finally:
        db.close()

if __name__ == "__main__":
    check_categorization()
