#!/usr/bin/env python3
"""
N8N Workflow Import Helper

This script provides guidance for importing N8N workflows.
"""

import os
import json
from pathlib import Path

def check_workflow_files():
    """Check available workflow files."""
    workflow_dir = Path("n8n_workflows")
    
    if not workflow_dir.exists():
        print("❌ n8n_workflows directory not found")
        return []
    
    workflow_files = list(workflow_dir.glob("*.json"))
    
    print("📁 **Available Workflow Files:**")
    print("=" * 40)
    
    workflows = []
    for file_path in workflow_files:
        try:
            with open(file_path, 'r') as f:
                workflow_data = json.load(f)
                name = workflow_data.get('name', file_path.stem)
                
                # Get trigger information
                trigger_info = "Manual trigger"
                nodes = workflow_data.get('nodes', [])
                for node in nodes:
                    if node.get('type') == 'n8n-nodes-base.cron':
                        cron_expr = node.get('parameters', {}).get('rule', {}).get('interval', [{}])[0].get('expression', '')
                        if cron_expr == '0 8 * * *':
                            trigger_info = "Daily at 8 AM"
                        elif cron_expr == '0 * * * *':
                            trigger_info = "Every hour"
                        elif cron_expr == '*/5 * * * *':
                            trigger_info = "Every 5 minutes"
                        else:
                            trigger_info = f"Cron: {cron_expr}"
                        break
                
                workflows.append({
                    'file': file_path.name,
                    'name': name,
                    'trigger': trigger_info,
                    'path': str(file_path)
                })
                
                print(f"✅ **{name}**")
                print(f"   📄 File: {file_path.name}")
                print(f"   ⏰ Trigger: {trigger_info}")
                print()
                
        except Exception as e:
            print(f"⚠️  Error reading {file_path.name}: {str(e)}")
    
    return workflows

def show_import_instructions():
    """Show step-by-step import instructions."""
    print("\n🔄 **How to Import Workflows in N8N:**")
    print("=" * 50)
    print("1. **Open N8N Dashboard**: http://localhost:5678")
    print("2. **Click 'Workflows'** in the left sidebar")
    print("3. **Click the '+' button** to create new workflow")
    print("4. **Click the '...' menu** (three dots) in top right")
    print("5. **Select 'Import from file'**")
    print("6. **Choose a workflow file** from the list above")
    print("7. **Repeat for all 3 workflow files**")
    
    print("\n✅ **After Importing Each Workflow:**")
    print("1. **Open the workflow**")
    print("2. **Click 'Active' toggle** to enable it")
    print("3. **Click 'Save'** to save the workflow")
    print("4. **Verify the trigger** is set correctly")

def show_workflow_details():
    """Show detailed information about each workflow."""
    print("\n📊 **Workflow Details:**")
    print("=" * 40)
    
    workflows_info = {
        "betsightly_daily_summary.json": {
            "name": "Daily Summary",
            "description": "Sends daily performance summary at 8 AM",
            "features": [
                "📊 Total predictions count",
                "🎯 Overall accuracy percentage", 
                "🏆 Best performing model",
                "📈 Performance trends",
                "💰 ROI analysis"
            ]
        },
        "betsightly_performance_alerts.json": {
            "name": "Performance Alerts", 
            "description": "Monitors performance every hour and sends alerts",
            "features": [
                "🚨 Accuracy drop alerts",
                "⚠️  Performance threshold monitoring",
                "📉 Trend analysis alerts",
                "🔧 Recommended actions"
            ]
        },
        "betsightly_system_monitor.json": {
            "name": "System Monitor",
            "description": "Continuous health monitoring every 5 minutes", 
            "features": [
                "🔍 API health checks",
                "💾 Database status monitoring",
                "🖥️  Resource usage tracking",
                "🚨 System failure alerts"
            ]
        }
    }
    
    for filename, info in workflows_info.items():
        print(f"🔄 **{info['name']}**")
        print(f"   📄 File: {filename}")
        print(f"   📝 Description: {info['description']}")
        print(f"   ✨ Features:")
        for feature in info['features']:
            print(f"      {feature}")
        print()

def main():
    print("🚀 **N8N Workflow Import Helper**")
    print("=" * 50)
    
    # Check workflow files
    workflows = check_workflow_files()
    
    if not workflows:
        print("❌ No workflow files found")
        return
    
    # Show import instructions
    show_import_instructions()
    
    # Show workflow details
    show_workflow_details()
    
    print("\n🎯 **Quick Checklist:**")
    print("□ Import betsightly_daily_summary.json")
    print("□ Import betsightly_performance_alerts.json") 
    print("□ Import betsightly_system_monitor.json")
    print("□ Activate all 3 workflows")
    print("□ Test with: python complete_n8n_setup_final.py")
    
    print("\n🌐 **Quick Links:**")
    print(f"• N8N Dashboard: http://localhost:5678")
    print(f"• BetSightly API: http://localhost:8000")
    print(f"• Workflow Files: {os.path.abspath('n8n_workflows')}")

if __name__ == "__main__":
    main()
