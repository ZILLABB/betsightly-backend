#!/usr/bin/env python3
"""
N8N Setup Script for BetSightly
Automates the setup and configuration of N8N workflows
"""

import os
import json
import asyncio
import httpx
from pathlib import Path
import time
import subprocess
import sys

class N8NSetup:
    def __init__(self):
        self.n8n_url = "http://localhost:5678"
        self.workflows_dir = Path("n8n_workflows")
        self.credentials = {}
        
    def check_n8n_running(self):
        """Check if N8N is running"""
        try:
            response = httpx.get(f"{self.n8n_url}/healthz", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def start_n8n(self):
        """Start N8N if not running"""
        if self.check_n8n_running():
            print("✅ N8N is already running")
            return True
        
        print("🚀 Starting N8N...")
        try:
            # Start N8N in background
            subprocess.Popen(
                ["n8n", "start"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            # Wait for N8N to start
            for i in range(30):  # Wait up to 30 seconds
                if self.check_n8n_running():
                    print("✅ N8N started successfully")
                    return True
                time.sleep(1)
                print(f"⏳ Waiting for N8N to start... ({i+1}/30)")
            
            print("❌ Failed to start N8N")
            return False
            
        except Exception as e:
            print(f"❌ Error starting N8N: {str(e)}")
            return False
    
    def setup_credentials(self):
        """Setup Telegram credentials"""
        print("\n📱 Setting up Telegram credentials...")
        
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        
        if not bot_token:
            print("⚠️  TELEGRAM_BOT_TOKEN not found in environment variables")
            bot_token = input("Enter your Telegram Bot Token: ").strip()
        
        if not chat_id:
            print("⚠️  TELEGRAM_CHAT_ID not found in environment variables")
            chat_id = input("Enter your Telegram Chat ID: ").strip()
        
        if bot_token and chat_id:
            self.credentials = {
                "telegram_bot_token": bot_token,
                "telegram_chat_id": chat_id
            }
            print("✅ Telegram credentials configured")
            return True
        else:
            print("❌ Missing Telegram credentials")
            return False
    
    async def import_workflow(self, workflow_file):
        """Import a workflow into N8N"""
        try:
            with open(workflow_file, 'r') as f:
                workflow_data = json.load(f)
            
            # Update credentials in workflow
            for node in workflow_data.get("nodes", []):
                if node.get("type") == "n8n-nodes-base.telegram":
                    if "credentials" in node:
                        node["credentials"]["telegramApi"]["name"] = "BetSightly Bot"
                
                # Update chat ID in parameters
                if "parameters" in node and "chatId" in node["parameters"]:
                    node["parameters"]["chatId"] = self.credentials.get("telegram_chat_id", "")
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.n8n_url}/rest/workflows",
                    json=workflow_data,
                    timeout=30
                )
                
                if response.status_code in [200, 201]:
                    print(f"✅ Imported workflow: {workflow_data['name']}")
                    return True
                else:
                    print(f"❌ Failed to import workflow: {workflow_data['name']} - {response.text}")
                    return False
                    
        except Exception as e:
            print(f"❌ Error importing workflow {workflow_file}: {str(e)}")
            return False
    
    async def setup_telegram_credential(self):
        """Setup Telegram credential in N8N"""
        try:
            credential_data = {
                "name": "BetSightly Bot",
                "type": "telegramApi",
                "data": {
                    "accessToken": self.credentials["telegram_bot_token"]
                }
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.n8n_url}/rest/credentials",
                    json=credential_data,
                    timeout=30
                )
                
                if response.status_code in [200, 201]:
                    print("✅ Telegram credential created in N8N")
                    return True
                else:
                    print(f"❌ Failed to create Telegram credential: {response.text}")
                    return False
                    
        except Exception as e:
            print(f"❌ Error creating Telegram credential: {str(e)}")
            return False
    
    async def import_all_workflows(self):
        """Import all BetSightly workflows"""
        print("\n📊 Importing N8N workflows...")
        
        workflow_files = [
            "betsightly_daily_summary.json",
            "betsightly_performance_alerts.json",
            "betsightly_system_monitor.json"
        ]
        
        success_count = 0
        for workflow_file in workflow_files:
            workflow_path = self.workflows_dir / workflow_file
            if workflow_path.exists():
                if await self.import_workflow(workflow_path):
                    success_count += 1
            else:
                print(f"⚠️  Workflow file not found: {workflow_file}")
        
        print(f"\n✅ Successfully imported {success_count}/{len(workflow_files)} workflows")
        return success_count == len(workflow_files)
    
    async def test_integration(self):
        """Test the N8N integration"""
        print("\n🧪 Testing N8N integration...")

        try:
            # Test BetSightly API health endpoint
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.get("http://localhost:8000/api/health", timeout=10)
                    if response.status_code == 200:
                        print("✅ BetSightly API is responding")
                    else:
                        print("⚠️  BetSightly API health check failed")
                except Exception as e:
                    print(f"⚠️  BetSightly API not running: {str(e)}")
                    print("   You can start it later with: python -m uvicorn main:app --reload")

            # Test N8N health
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.get(f"{self.n8n_url}/healthz", timeout=5)
                    if response.status_code == 200:
                        print("✅ N8N is responding")
                    else:
                        print("⚠️  N8N health check failed")
                except Exception as e:
                    print(f"⚠️  N8N connection failed: {str(e)}")

            # Test N8N webhook (if N8N is running)
            test_data = {
                "message": "🧪 Test message from BetSightly setup script",
                "alert_type": "test",
                "timestamp": "2025-01-15T10:00:00Z"
            }

            async with httpx.AsyncClient() as client:
                try:
                    response = await client.post(
                        f"{self.n8n_url}/webhook/telegram-alert",
                        json=test_data,
                        timeout=10
                    )

                    if response.status_code == 200:
                        print("✅ N8N webhook test successful")
                        print("📱 Check your Telegram for the test message!")
                    else:
                        print(f"⚠️  N8N webhook test failed: {response.status_code}")
                except Exception as e:
                    print(f"⚠️  N8N webhook test failed: {str(e)}")
                    print("   This is normal if workflows aren't activated yet")

        except Exception as e:
            print(f"❌ Integration test failed: {str(e)}")
    
    def create_env_file(self):
        """Create .env file with N8N configuration"""
        env_content = f"""# N8N Configuration for BetSightly
N8N_BASE_URL=http://localhost:5678
TELEGRAM_BOT_TOKEN={self.credentials.get('telegram_bot_token', 'YOUR_BOT_TOKEN')}
TELEGRAM_CHAT_ID={self.credentials.get('telegram_chat_id', 'YOUR_CHAT_ID')}

# N8N Environment Variables
N8N_BASIC_AUTH_ACTIVE=false
N8N_HOST=0.0.0.0
N8N_PORT=5678
N8N_PROTOCOL=http
WEBHOOK_URL=http://localhost:5678/
"""
        
        with open(".env.n8n", "w") as f:
            f.write(env_content)
        
        print("✅ Created .env.n8n configuration file")
    
    def print_setup_instructions(self):
        """Print final setup instructions"""
        print("\n" + "="*60)
        print("🎉 N8N SETUP COMPLETE!")
        print("="*60)
        print("\n📋 NEXT STEPS:")
        print("\n1. 🌐 Open N8N Dashboard:")
        print("   http://localhost:5678")
        print("\n2. 🔧 Configure Workflows:")
        print("   - All workflows have been imported")
        print("   - Activate each workflow in the N8N interface")
        print("   - Verify Telegram credentials are working")
        print("\n3. 📱 Test Telegram Integration:")
        print("   curl -X POST http://localhost:8000/api/n8n/test-alert")
        print("\n4. 📊 Monitor Your System:")
        print("   - Daily summaries at 8 AM")
        print("   - Performance alerts every hour")
        print("   - System monitoring every 5 minutes")
        print("\n5. 🔗 Useful Endpoints:")
        print("   - Health: http://localhost:8000/api/n8n/health")
        print("   - Dashboard: http://localhost:8000/api/analytics/dashboard")
        print("   - Alerts: http://localhost:8000/api/analytics/alerts")
        print("\n" + "="*60)
        print("🚀 Your BetSightly system now has enterprise-grade monitoring!")
        print("="*60)

async def main():
    """Main setup function"""
    print("🚀 BetSightly N8N Setup Script")
    print("="*40)
    
    setup = N8NSetup()
    
    # Check if N8N is installed
    try:
        subprocess.run(["n8n", "--version"], capture_output=True, check=True)
        print("✅ N8N is installed")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ N8N is not installed. Please install it first:")
        print("   npm install -g n8n")
        sys.exit(1)
    
    # Start N8N
    if not setup.start_n8n():
        print("❌ Failed to start N8N. Please start it manually and run this script again.")
        sys.exit(1)
    
    # Setup credentials
    if not setup.setup_credentials():
        print("❌ Failed to setup credentials. Please check your Telegram bot configuration.")
        sys.exit(1)
    
    # Wait a bit for N8N to fully initialize
    print("⏳ Waiting for N8N to fully initialize...")
    await asyncio.sleep(5)
    
    # Setup Telegram credential in N8N
    await setup.setup_telegram_credential()
    
    # Import workflows
    await setup.import_all_workflows()
    
    # Create environment file
    setup.create_env_file()
    
    # Test integration
    await setup.test_integration()
    
    # Print final instructions
    setup.print_setup_instructions()

if __name__ == "__main__":
    asyncio.run(main())
