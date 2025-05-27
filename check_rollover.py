"""
Check Rollover Information

This script checks for rollover information in the API endpoints.
"""

import requests
import json

def check_endpoint(url, description):
    """Check an endpoint for rollover information."""
    print(f"\n{description} ({url}):")
    try:
        response = requests.get(url)
        data = response.json()
        
        # Check if 'rollover' is a top-level key
        if isinstance(data, dict) and 'rollover' in data:
            print("- Contains 'rollover' as a top-level key")
            rollover_data = data['rollover']
            if rollover_data:
                print(f"- Rollover data: {json.dumps(rollover_data, indent=2)[:200]}...")
            else:
                print("- Rollover data is empty")
        
        # Check if 'rollover' is in categories
        if isinstance(data, dict) and 'categories' in data and isinstance(data['categories'], dict):
            if 'rollover' in data['categories']:
                print("- Contains 'rollover' in categories")
                rollover_category = data['categories']['rollover']
                if rollover_category:
                    print(f"- Rollover category: {json.dumps(rollover_category, indent=2)[:200]}...")
                else:
                    print("- Rollover category is empty")
        
        # Check for rollover_day field
        rollover_day_found = False
        if isinstance(data, dict):
            # Check in top-level items
            for key, value in data.items():
                if isinstance(value, list) and value:
                    for item in value:
                        if isinstance(item, dict) and 'rollover_day' in item:
                            rollover_day_found = True
                            print(f"- Contains 'rollover_day' field in {key}")
                            print(f"  Value: {item['rollover_day']}")
            
            # Check in categories
            if 'categories' in data and isinstance(data['categories'], dict):
                for category_key, category in data['categories'].items():
                    if isinstance(category, dict) and 'predictions' in category and isinstance(category['predictions'], list):
                        for prediction in category['predictions']:
                            if isinstance(prediction, dict) and 'rollover_day' in prediction:
                                rollover_day_found = True
                                print(f"- Contains 'rollover_day' field in categories.{category_key}")
                                print(f"  Value: {prediction['rollover_day']}")
        
        if not rollover_day_found:
            print("- No 'rollover_day' field found")
        
        # Check response structure
        print(f"- Response structure: {type(data).__name__}")
        if isinstance(data, dict):
            print(f"- Top-level keys: {list(data.keys())}")
        elif isinstance(data, list):
            print(f"- List length: {len(data)}")
            if data and isinstance(data[0], dict):
                print(f"- First item keys: {list(data[0].keys())}")
    
    except Exception as e:
        print(f"- Error: {str(e)}")

def main():
    """Check all endpoints for rollover information."""
    print("=" * 80)
    print("CHECKING FOR ROLLOVER INFORMATION")
    print("=" * 80)
    
    # Check endpoints
    check_endpoint("http://localhost:8000/api/predictions/best", "Best Predictions Endpoint")
    check_endpoint("http://localhost:8000/api/predictions/categories", "Categories Endpoint")
    check_endpoint("http://localhost:8000/api/predictions/category/rollover", "Rollover Category Endpoint")
    check_endpoint("http://localhost:8000/api/predictions/best/rollover", "Best Rollover Endpoint")
    check_endpoint("http://localhost:8000/api/predictions?categorized=true", "Legacy Categorized Endpoint")

if __name__ == "__main__":
    main()
