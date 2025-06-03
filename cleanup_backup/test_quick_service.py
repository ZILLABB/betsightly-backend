#!/usr/bin/env python3
"""
Test Quick Prediction Service
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_service():
    print("Testing Quick Prediction Service...")
    
    try:
        from services.quick_prediction_service import QuickPredictionService
        
        # Create service
        service = QuickPredictionService()
        print(f"Service created: {len(service.models)} models loaded")
        
        # Test prediction
        result = service.get_predictions_for_date()
        print(f"Prediction result: {result}")
        
        return True
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_service()
