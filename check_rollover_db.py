"""
Check Rollover Predictions in Database

This script checks if there are any rollover predictions in the database.
"""

import sqlite3

def check_rollover_db():
    """Check if there are any rollover predictions in the database."""
    try:
        # Connect to the database
        conn = sqlite3.connect('real_predictions.db')
        cursor = conn.cursor()
        
        # Check prediction_combinations table
        cursor.execute('SELECT * FROM prediction_combinations WHERE category = "rollover" LIMIT 5')
        rows = cursor.fetchall()
        
        print(f'Found {len(rows)} rollover predictions in prediction_combinations table')
        for row in rows:
            print(row)
        
        # Get table schema
        cursor.execute("PRAGMA table_info(prediction_combinations)")
        columns = cursor.fetchall()
        print("\nColumns in prediction_combinations table:")
        for column in columns:
            print(f"- {column[1]} ({column[2]})")
        
        # Check if there are any predictions with rollover_day not null
        cursor.execute('SELECT * FROM prediction_combinations WHERE rollover_day IS NOT NULL LIMIT 5')
        rows = cursor.fetchall()
        
        print(f'\nFound {len(rows)} predictions with rollover_day not null')
        for row in rows:
            print(row)
        
        # Close the connection
        conn.close()
    
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    check_rollover_db()
