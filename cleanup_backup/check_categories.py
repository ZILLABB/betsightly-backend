"""
Check Categories API Response

This script checks the structure of the /api/predictions/categories endpoint response.
"""

import requests
import json

def check_categories():
    """Check the structure of the categories API response."""
    try:
        # Get the categories response
        response = requests.get('http://localhost:8000/api/predictions/categories')
        data = response.json()
        
        # Print the date
        print(f"Date: {data.get('date', 'Not provided')}")
        
        # Print the categories
        categories = data.get('categories', {})
        print(f"\nCategories: {list(categories.keys())}")
        
        # Check each category
        for category_key, category in categories.items():
            print(f"\n{category.get('name', 'Unknown')} ({category_key}):")
            print(f"- Description: {category.get('description', 'Not provided')}")
            print(f"- Target Odds: {category.get('target_odds', 'Not provided')}")
            
            predictions = category.get('predictions', [])
            print(f"- Number of Predictions: {len(predictions)}")
            
            if predictions:
                prediction = predictions[0]
                print(f"- Best Combined Odds: {prediction.get('combined_odds', 'Not provided')}")
                print(f"- Best Combined Confidence: {prediction.get('combined_confidence', 'Not provided')}")
                
                individual_predictions = prediction.get('predictions', [])
                print(f"- Number of Individual Predictions: {len(individual_predictions)}")
                
                print("- Matches:")
                for individual in individual_predictions:
                    fixture = individual.get('fixture', {})
                    home_team = fixture.get('home_team', 'Unknown')
                    away_team = fixture.get('away_team', 'Unknown')
                    prediction_type = individual.get('prediction_type', 'Unknown')
                    odds = individual.get('odds', 'Unknown')
                    confidence = individual.get('confidence', 'Unknown')
                    
                    print(f"  • {home_team} vs {away_team}: {prediction_type} (Odds: {odds}, Confidence: {confidence})")
    
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    check_categories()
