#!/usr/bin/env python3
"""
N8N Workflow Import Helper
Automatically imports BetSightly monitoring workflows into N8N
"""

import json
import requests
import os
from pathlib import Path

# N8N Configuration
N8N_BASE_URL = "http://localhost:5678"
WORKFLOWS_DIR = "n8n_workflows"

# Workflow files to import
WORKFLOW_FILES = [
    "betsightly_system_monitor.json",
    "betsightly_performance_alerts.json", 
    "betsightly_daily_summary.json"
]

def check_n8n_connection():
    """Check if N8N is running and accessible"""
    try:
        response = requests.get(f"{N8N_BASE_URL}/healthz", timeout=5)
        if response.status_code == 200:
            print("✅ N8N is running and accessible")
            return True
        else:
            print(f"❌ N8N returned status code: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Cannot connect to N8N: {e}")
        return False

def import_workflow(workflow_file):
    """Import a single workflow file into N8N"""
    workflow_path = Path(WORKFLOWS_DIR) / workflow_file
    
    if not workflow_path.exists():
        print(f"❌ Workflow file not found: {workflow_path}")
        return False
    
    try:
        # Read workflow file
        with open(workflow_path, 'r') as f:
            workflow_data = json.load(f)
        
        print(f"📥 Importing workflow: {workflow_file}")
        
        # Import workflow via N8N API
        response = requests.post(
            f"{N8N_BASE_URL}/api/v1/workflows/import",
            json=workflow_data,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if response.status_code in [200, 201]:
            print(f"✅ Successfully imported: {workflow_file}")
            return True
        else:
            print(f"❌ Failed to import {workflow_file}: {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error importing {workflow_file}: {e}")
        return False

def main():
    """Main function to import all workflows"""
    print("🚀 BetSightly N8N Workflow Import Tool")
    print("=" * 50)
    
    # Check N8N connection
    if not check_n8n_connection():
        print("\n❌ Please ensure N8N is running on http://localhost:5678")
        print("Run: ./start_n8n.sh")
        return
    
    # Import workflows
    success_count = 0
    total_count = len(WORKFLOW_FILES)
    
    print(f"\n📦 Importing {total_count} workflows...")
    
    for workflow_file in WORKFLOW_FILES:
        if import_workflow(workflow_file):
            success_count += 1
        print()  # Add spacing
    
    # Summary
    print("=" * 50)
    print(f"📊 Import Summary: {success_count}/{total_count} workflows imported")
    
    if success_count == total_count:
        print("🎉 All workflows imported successfully!")
        print("\n📋 Next Steps:")
        print("1. Open N8N Dashboard: http://localhost:5678")
        print("2. Configure Telegram credentials for each workflow")
        print("3. Activate the workflows")
        print("4. Test the monitoring system")
    else:
        print("⚠️  Some workflows failed to import. Check the errors above.")
    
    print("\n🔗 N8N Dashboard: http://localhost:5678")

if __name__ == "__main__":
    main()
