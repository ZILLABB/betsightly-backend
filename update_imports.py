"""
Update Imports

This script updates the imports in all Python files in the project.
"""

import os
import re
import logging

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def update_imports(file_path):
    """Update imports in a Python file."""
    try:
        # Read the file
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Replace imports
        new_content = content
        new_content = re.sub(r'from app\.api\.endpoints', 'from api.endpoints', new_content)
        new_content = re.sub(r'from app\.api', 'from api', new_content)
        new_content = re.sub(r'from app\.database', 'from database', new_content)
        new_content = re.sub(r'from app\.models', 'from models', new_content)
        new_content = re.sub(r'from app\.services', 'from services', new_content)
        new_content = re.sub(r'from app\.utils', 'from utils', new_content)
        new_content = re.sub(r'from app\.schemas', 'from schemas', new_content)
        
        # Write the file if changes were made
        if new_content != content:
            with open(file_path, 'w') as f:
                f.write(new_content)
            logger.info(f"Updated imports in {file_path}")
            return True
        
        return False
    
    except Exception as e:
        logger.error(f"Error updating imports in {file_path}: {str(e)}")
        return False

def main():
    """Update imports in all Python files."""
    # Find all Python files
    python_files = []
    for root, dirs, files in os.walk('.'):
        for file in files:
            if file.endswith('.py'):
                python_files.append(os.path.join(root, file))
    
    logger.info(f"Found {len(python_files)} Python files")
    
    # Update imports in each file
    updated_files = 0
    for file_path in python_files:
        if update_imports(file_path):
            updated_files += 1
    
    logger.info(f"Updated imports in {updated_files} files")

if __name__ == "__main__":
    main()
