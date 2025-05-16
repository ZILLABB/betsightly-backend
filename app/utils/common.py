"""
Common Utilities

This module contains common utility functions used throughout the application.
"""

import os
import sys
import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Union

# Set up logging
def setup_logging(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Set up logging.
    
    Args:
        name: Logger name
        level: Logging level
        
    Returns:
        Logger instance
    """
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    
    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Add formatter to console handler
    console_handler.setFormatter(formatter)
    
    # Add console handler to logger
    logger.addHandler(console_handler)
    
    return logger

def ensure_directory_exists(directory: str) -> bool:
    """
    Ensure a directory exists.
    
    Args:
        directory: Directory path
        
    Returns:
        True if successful, False otherwise
    """
    try:
        os.makedirs(directory, exist_ok=True)
        return True
    except Exception as e:
        logging.error(f"Error creating directory {directory}: {str(e)}")
        return False

def load_json_file(file_path: str) -> Union[Dict[str, Any], List[Any], None]:
    """
    Load JSON from a file.
    
    Args:
        file_path: Path to the JSON file
        
    Returns:
        JSON data or None if file doesn't exist or is invalid
    """
    try:
        # Check if file exists
        if not os.path.exists(file_path):
            return None
        
        # Load JSON
        with open(file_path, "r") as f:
            data = json.load(f)
        
        return data
    
    except Exception as e:
        logging.error(f"Error loading JSON file {file_path}: {str(e)}")
        return None

def save_json_file(file_path: str, data: Union[Dict[str, Any], List[Any]]) -> bool:
    """
    Save JSON to a file.
    
    Args:
        file_path: Path to the JSON file
        data: JSON data
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Ensure directory exists
        ensure_directory_exists(os.path.dirname(file_path))
        
        # Save JSON
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)
        
        return True
    
    except Exception as e:
        logging.error(f"Error saving JSON file {file_path}: {str(e)}")
        return False

def format_date(date: Union[str, datetime]) -> str:
    """
    Format a date as YYYY-MM-DD.
    
    Args:
        date: Date string or datetime object
        
    Returns:
        Formatted date string
    """
    try:
        # Convert string to datetime
        if isinstance(date, str):
            date = datetime.strptime(date, "%Y-%m-%d")
        
        # Format datetime
        return date.strftime("%Y-%m-%d")
    
    except Exception as e:
        logging.error(f"Error formatting date {date}: {str(e)}")
        return str(date)

def parse_date(date_str: str) -> Union[datetime, None]:
    """
    Parse a date string.
    
    Args:
        date_str: Date string
        
    Returns:
        Datetime object or None if invalid
    """
    try:
        # Try different formats
        formats = [
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%d-%m-%Y",
            "%d/%m/%Y",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ"
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        
        # If we get here, none of the formats worked
        logging.error(f"Error parsing date {date_str}: Unknown format")
        return None
    
    except Exception as e:
        logging.error(f"Error parsing date {date_str}: {str(e)}")
        return None

def calculate_odds(probability: float) -> float:
    """
    Calculate odds from probability.
    
    Args:
        probability: Probability (0.0 to 1.0)
        
    Returns:
        Odds
    """
    try:
        # Ensure probability is valid
        probability = max(0.01, min(0.99, probability))
        
        # Calculate odds
        return round(1.0 / probability, 2)
    
    except Exception as e:
        logging.error(f"Error calculating odds: {str(e)}")
        return 1.0

def calculate_probability(odds: float) -> float:
    """
    Calculate probability from odds.
    
    Args:
        odds: Odds
        
    Returns:
        Probability (0.0 to 1.0)
    """
    try:
        # Ensure odds are valid
        odds = max(1.01, odds)
        
        # Calculate probability
        return round(1.0 / odds, 2)
    
    except Exception as e:
        logging.error(f"Error calculating probability: {str(e)}")
        return 0.5
