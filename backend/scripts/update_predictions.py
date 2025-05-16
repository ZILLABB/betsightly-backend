#!/usr/bin/env python3
"""
Update predictions in the database with prediction types, odds, and confidence.
"""

import os
import sys
import sqlite3
import logging

# Add parent directory to path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(backend_dir)
os.chdir(backend_dir)  # Change to backend directory to ensure .env is found

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Database file
DB_FILE = os.path.join(backend_dir, "football_predictions.db")

def update_predictions():
    """Update predictions in the database with prediction types, odds, and confidence."""
    try:
        # Connect to database
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Get all predictions
        cursor.execute('''
            SELECT id, btts_pred, btts_yes_pred, over_under_pred, over_2_5_pred, 
                   match_result_pred, home_win_pred, draw_pred, away_win_pred
            FROM predictions
        ''')
        predictions = cursor.fetchall()
        
        logger.info(f"Found {len(predictions)} predictions to update")
        
        # Update each prediction
        updated_count = 0
        for pred in predictions:
            pred_id = pred[0]
            btts_pred = pred[1]
            btts_yes_pred = pred[2]
            over_under_pred = pred[3]
            over_2_5_pred = pred[4]
            match_result_pred = pred[5]
            home_win_pred = pred[6]
            draw_pred = pred[7]
            away_win_pred = pred[8]
            
            prediction_type = None
            odds = 0.0
            confidence = 0.0
            
            # Assign prediction type, odds, and confidence based on prediction values
            if btts_pred == 'YES' and btts_yes_pred >= 0.7:
                prediction_type = 'btts'
                odds = 1.8  # Typical BTTS odds
                confidence = btts_yes_pred
            elif over_under_pred == 'OVER' and over_2_5_pred >= 0.7:
                prediction_type = 'over_2_5'
                odds = 1.9  # Typical over 2.5 odds
                confidence = over_2_5_pred
            elif match_result_pred == 'HOME' and home_win_pred >= 0.7:
                prediction_type = 'home_win'
                odds = 2.0  # Typical home win odds
                confidence = home_win_pred
            elif match_result_pred == 'DRAW' and draw_pred >= 0.7:
                prediction_type = 'draw'
                odds = 3.5  # Typical draw odds
                confidence = draw_pred
            elif match_result_pred == 'AWAY' and away_win_pred >= 0.7:
                prediction_type = 'away_win'
                odds = 3.0  # Typical away win odds
                confidence = away_win_pred
            
            # If we have a prediction type, update the prediction
            if prediction_type:
                logger.info(f"Updating prediction {pred_id} to {prediction_type} with odds {odds} and confidence {confidence}")
                cursor.execute('''
                    UPDATE predictions 
                    SET prediction_type = ?, odds = ?, confidence = ? 
                    WHERE id = ?
                ''', (prediction_type, odds, confidence, pred_id))
                updated_count += 1
            
        # Commit changes
        conn.commit()
        
        # Verify updates
        cursor.execute('''
            SELECT prediction_type, odds, confidence, COUNT(*) 
            FROM predictions 
            GROUP BY prediction_type, odds, confidence
        ''')
        types = cursor.fetchall()
        logger.info(f"Prediction types after update: {types}")
        
        # Close connection
        conn.close()
        
        logger.info(f"Successfully updated {updated_count} predictions")
        return True
    
    except Exception as e:
        logger.error(f"Error updating predictions: {str(e)}")
        return False

if __name__ == "__main__":
    update_predictions()
