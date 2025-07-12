#!/usr/bin/env python3
"""
BetSightly Railway Migration Script
Automates the migration from Render.com to Railway
"""

import os
import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime

class RailwayMigrator:
    def __init__(self):
        self.project_name = "betsightly-backend"
        self.backup_dir = Path("migration_backup")
        self.env_vars = {}
        
    def log(self, message, level="INFO"):
        """Log migration progress."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {level}: {message}")
        
    def check_prerequisites(self):
        """Check if all prerequisites are met."""
        self.log("🔍 Checking prerequisites...")
        
        # Check if Railway CLI is installed
        try:
            result = subprocess.run(["railway", "--version"], capture_output=True, text=True)
            if result.returncode == 0:
                self.log(f"✅ Railway CLI found: {result.stdout.strip()}")
            else:
                self.log("❌ Railway CLI not found. Install with: npm install -g @railway/cli", "ERROR")
                return False
        except FileNotFoundError:
            self.log("❌ Railway CLI not found. Install with: npm install -g @railway/cli", "ERROR")
            return False
            
        # Check if logged in to Railway
        try:
            result = subprocess.run(["railway", "whoami"], capture_output=True, text=True)
            if result.returncode == 0:
                self.log(f"✅ Logged in to Railway as: {result.stdout.strip()}")
            else:
                self.log("❌ Not logged in to Railway. Run: railway login", "ERROR")
                return False
        except:
            self.log("❌ Railway authentication failed. Run: railway login", "ERROR")
            return False
            
        # Check if .env file exists
        if Path(".env").exists():
            self.log("✅ Environment file found")
        else:
            self.log("⚠️  No .env file found. Will need to set variables manually", "WARNING")
            
        return True
        
    def backup_current_setup(self):
        """Backup current configuration and data."""
        self.log("💾 Creating backup of current setup...")
        
        # Create backup directory
        self.backup_dir.mkdir(exist_ok=True)
        
        # Backup database
        if Path("real_predictions.db").exists():
            import shutil
            shutil.copy2("real_predictions.db", self.backup_dir / f"real_predictions_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
            self.log("✅ Database backed up")
            
        # Backup environment variables
        if Path(".env").exists():
            import shutil
            shutil.copy2(".env", self.backup_dir / f"env_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.env")
            self.log("✅ Environment variables backed up")
            
        # Create migration log
        with open(self.backup_dir / "migration_log.txt", "w") as f:
            f.write(f"Migration started: {datetime.now()}\n")
            f.write(f"Source: Render.com\n")
            f.write(f"Target: Railway\n")
            
        self.log("✅ Backup completed")
        
    def load_environment_variables(self):
        """Load environment variables from .env file."""
        self.log("📋 Loading environment variables...")
        
        if not Path(".env").exists():
            self.log("⚠️  No .env file found", "WARNING")
            return
            
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    self.env_vars[key] = value
                    
        self.log(f"✅ Loaded {len(self.env_vars)} environment variables")
        
    def create_railway_project(self):
        """Create new Railway project."""
        self.log("🚀 Creating Railway project...")
        
        try:
            # Create new project
            result = subprocess.run(
                ["railway", "new", self.project_name],
                capture_output=True,
                text=True,
                input="y\n"  # Confirm project creation
            )
            
            if result.returncode == 0:
                self.log("✅ Railway project created successfully")
            else:
                self.log(f"❌ Failed to create project: {result.stderr}", "ERROR")
                return False
                
        except Exception as e:
            self.log(f"❌ Error creating project: {str(e)}", "ERROR")
            return False
            
        return True
        
    def setup_database(self):
        """Set up PostgreSQL database on Railway."""
        self.log("🗄️  Setting up PostgreSQL database...")
        
        try:
            # Add PostgreSQL service
            result = subprocess.run(
                ["railway", "add", "postgresql"],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                self.log("✅ PostgreSQL database added")
            else:
                self.log(f"❌ Failed to add database: {result.stderr}", "ERROR")
                return False
                
        except Exception as e:
            self.log(f"❌ Error setting up database: {str(e)}", "ERROR")
            return False
            
        return True
        
    def set_environment_variables(self):
        """Set environment variables on Railway."""
        self.log("⚙️  Setting environment variables...")
        
        # Essential variables for Railway
        railway_vars = {
            "ENVIRONMENT": "production",
            "DEBUG": "false",
            "PORT": "8000",
            **self.env_vars
        }
        
        for key, value in railway_vars.items():
            try:
                result = subprocess.run(
                    ["railway", "variables", "set", f"{key}={value}"],
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    self.log(f"✅ Set {key}")
                else:
                    self.log(f"⚠️  Failed to set {key}: {result.stderr}", "WARNING")
                    
            except Exception as e:
                self.log(f"⚠️  Error setting {key}: {str(e)}", "WARNING")
                
        self.log("✅ Environment variables configured")
        
    def deploy_application(self):
        """Deploy the application to Railway."""
        self.log("🚀 Deploying application to Railway...")
        
        try:
            # Deploy the application
            result = subprocess.run(
                ["railway", "up"],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                self.log("✅ Application deployed successfully")
                self.log("🌐 Getting deployment URL...")
                
                # Get the deployment URL
                url_result = subprocess.run(
                    ["railway", "domain"],
                    capture_output=True,
                    text=True
                )
                
                if url_result.returncode == 0:
                    self.log(f"🔗 Deployment URL: {url_result.stdout.strip()}")
                    
            else:
                self.log(f"❌ Deployment failed: {result.stderr}", "ERROR")
                return False
                
        except Exception as e:
            self.log(f"❌ Error during deployment: {str(e)}", "ERROR")
            return False
            
        return True
        
    def test_deployment(self):
        """Test the deployed application."""
        self.log("🧪 Testing deployment...")
        
        try:
            # Get the deployment URL
            result = subprocess.run(
                ["railway", "domain"],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                url = result.stdout.strip()
                
                # Test health endpoint
                import requests
                response = requests.get(f"{url}/api/health", timeout=30)
                
                if response.status_code == 200:
                    self.log("✅ Health check passed")
                    self.log(f"📊 Response: {response.json()}")
                else:
                    self.log(f"⚠️  Health check failed: {response.status_code}", "WARNING")
                    
            else:
                self.log("❌ Could not get deployment URL", "ERROR")
                return False
                
        except Exception as e:
            self.log(f"⚠️  Error testing deployment: {str(e)}", "WARNING")
            
        return True
        
    def migrate(self):
        """Run the complete migration process."""
        self.log("🚀 Starting BetSightly migration to Railway...")
        
        # Step 1: Check prerequisites
        if not self.check_prerequisites():
            self.log("❌ Prerequisites not met. Aborting migration.", "ERROR")
            return False
            
        # Step 2: Backup current setup
        self.backup_current_setup()
        
        # Step 3: Load environment variables
        self.load_environment_variables()
        
        # Step 4: Create Railway project
        if not self.create_railway_project():
            return False
            
        # Step 5: Set up database
        if not self.setup_database():
            return False
            
        # Step 6: Set environment variables
        self.set_environment_variables()
        
        # Step 7: Deploy application
        if not self.deploy_application():
            return False
            
        # Step 8: Test deployment
        self.test_deployment()
        
        self.log("🎉 Migration completed successfully!")
        self.log("📋 Next steps:")
        self.log("   1. Test all functionality on the new deployment")
        self.log("   2. Update DNS records to point to Railway")
        self.log("   3. Monitor performance for 24-48 hours")
        self.log("   4. Cancel Render.com subscription")
        
        return True

def main():
    """Main migration function."""
    print("🚀 BetSightly Railway Migration Tool")
    print("=" * 50)
    
    migrator = RailwayMigrator()
    
    # Confirm migration
    response = input("Are you ready to migrate to Railway? (y/N): ")
    if response.lower() != 'y':
        print("Migration cancelled.")
        return
        
    # Run migration
    success = migrator.migrate()
    
    if success:
        print("\n🎉 Migration completed successfully!")
        print("Your BetSightly backend is now running on Railway!")
    else:
        print("\n❌ Migration failed. Check the logs above.")
        print("Your original deployment on Render.com is still active.")

if __name__ == "__main__":
    main()
