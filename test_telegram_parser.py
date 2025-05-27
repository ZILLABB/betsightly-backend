"""
Test Telegram Parser

This script tests the Telegram message parser to ensure it correctly extracts
betting information.
"""

import sys
import logging

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def main():
    """Test the Telegram message parser."""
    try:
        # Import the parser function
        from telegram_bot import parse_betting_info
        
        # Test messages
        test_messages = [
            """
            Code: ABC123
            Match: Manchester United vs Liverpool
            Prediction: Manchester United to win
            Odds: 2.5
            Bookmaker: Bet365
            Date: 23/05/2023
            Time: 19:30
            """,
            
            """
            Today's top pick:
            Code: XYZ789
            Match: Real Madrid vs Barcelona
            Prediction: Over 2.5 goals
            Odds: 1.85
            Bookmaker: 1xBet
            Date: 24/05/2023
            Time: 20:45
            """,
            
            """
            🔥 HOT TIP 🔥
            Code: BTT456
            Match: Bayern Munich vs Dortmund
            Prediction: BTTS: Yes
            Odds: 1.75
            Bookmaker: Betway
            Date: 25/05/2023
            Time: 18:00
            """
        ]
        
        # Parse each message
        for i, message in enumerate(test_messages):
            logger.info(f"Testing message {i+1}:")
            logger.info("-" * 50)
            logger.info(message)
            logger.info("-" * 50)
            
            # Parse message
            betting_info = parse_betting_info(message)
            
            # Print results
            logger.info("Parsed information:")
            for key, value in betting_info.items():
                if key == "match_datetime" and value:
                    logger.info(f"  {key}: {value.strftime('%d/%m/%Y %H:%M')}")
                else:
                    logger.info(f"  {key}: {value}")
            
            logger.info("=" * 50)
        
        logger.info("All tests completed.")
    
    except ImportError:
        logger.error("Could not import parse_betting_info function from telegram_bot module.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error testing Telegram parser: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
