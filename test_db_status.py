#!/usr/bin/env python3
"""
Quick database status check script.
"""

import sqlite3
import os

def check_database_status():
    """Check the current status of the database."""
    db_file = "football.db"
    
    if not os.path.exists(db_file):
        print(f"❌ Database file {db_file} does not exist")
        return
    
    print(f"✅ Database file {db_file} exists")
    
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        print(f"📊 Tables: {[t[0] for t in tables]}")
        
        # Check fixtures
        cursor.execute("SELECT COUNT(*) FROM fixtures")
        fixture_count = cursor.fetchone()[0]
        print(f"🏟️  Fixtures count: {fixture_count}")
        
        # Check predictions
        cursor.execute("SELECT COUNT(*) FROM predictions")
        pred_count = cursor.fetchone()[0]
        print(f"🔮 Predictions count: {pred_count}")
        
        # Check recent fixtures
        if fixture_count > 0:
            cursor.execute("SELECT date, home_team, away_team FROM fixtures ORDER BY date DESC LIMIT 3")
            recent_fixtures = cursor.fetchall()
            print("📅 Recent fixtures:")
            for fixture in recent_fixtures:
                print(f"   {fixture[0]}: {fixture[1]} vs {fixture[2]}")
        
        # Check recent predictions
        if pred_count > 0:
            cursor.execute("SELECT fixture_id, prediction_type, confidence FROM predictions ORDER BY created_at DESC LIMIT 3")
            recent_predictions = cursor.fetchall()
            print("🎯 Recent predictions:")
            for pred in recent_predictions:
                print(f"   Fixture {pred[0]}: {pred[1]} (confidence: {pred[2]})")
        
        conn.close()
        print("✅ Database connection successful")
        
    except Exception as e:
        print(f"❌ Database error: {str(e)}")

if __name__ == "__main__":
    check_database_status()
