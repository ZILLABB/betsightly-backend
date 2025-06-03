#!/usr/bin/env python3
"""
Production Monitoring and Health Check System

This script provides comprehensive monitoring for the BetSightly backend in production.
"""

import os
import sys
import time
import psutil
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path

# Add project root to path
sys.path.append('.')

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class ProductionMonitor:
    """Production monitoring system."""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.alerts = []
        self.metrics = {}
        
        # Create logs directory if it doesn't exist
        Path('logs').mkdir(exist_ok=True)
    
    def check_api_health(self) -> Dict[str, Any]:
        """Check API health and response times."""
        logger.info("🏥 Checking API health...")
        
        endpoints = [
            '/api/health',
            '/api/predictions/',
            '/api/betting-codes/',
            '/api/punters/',
            '/api/bookmakers/'
        ]
        
        results = {}
        
        for endpoint in endpoints:
            try:
                start_time = time.time()
                response = requests.get(f"{self.base_url}{endpoint}", timeout=10)
                response_time = time.time() - start_time
                
                results[endpoint] = {
                    'status_code': response.status_code,
                    'response_time': response_time,
                    'healthy': response.status_code == 200,
                    'timestamp': datetime.now().isoformat()
                }
                
                if response.status_code != 200:
                    self.alerts.append(f"API endpoint {endpoint} returned {response.status_code}")
                
                if response_time > 2.0:
                    self.alerts.append(f"API endpoint {endpoint} slow response: {response_time:.2f}s")
                
            except Exception as e:
                results[endpoint] = {
                    'status_code': 0,
                    'response_time': 0,
                    'healthy': False,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                }
                self.alerts.append(f"API endpoint {endpoint} failed: {str(e)}")
        
        return results
    
    def check_system_resources(self) -> Dict[str, Any]:
        """Check system resource usage."""
        logger.info("💻 Checking system resources...")
        
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            resources = {
                'cpu_percent': cpu_percent,
                'memory_percent': memory.percent,
                'memory_available_gb': memory.available / (1024**3),
                'disk_percent': disk.percent,
                'disk_free_gb': disk.free / (1024**3),
                'timestamp': datetime.now().isoformat()
            }
            
            # Check thresholds
            if cpu_percent > 80:
                self.alerts.append(f"High CPU usage: {cpu_percent:.1f}%")
            
            if memory.percent > 85:
                self.alerts.append(f"High memory usage: {memory.percent:.1f}%")
            
            if disk.percent > 90:
                self.alerts.append(f"Low disk space: {disk.percent:.1f}% used")
            
            return resources
            
        except Exception as e:
            self.alerts.append(f"Failed to check system resources: {str(e)}")
            return {}
    
    def check_database_health(self) -> Dict[str, Any]:
        """Check database health and performance."""
        logger.info("🗄️  Checking database health...")
        
        try:
            from database import get_db
            
            db = next(get_db())
            start_time = time.time()
            
            # Test basic query
            result = db.execute("SELECT COUNT(*) FROM predictions").fetchone()
            predictions_count = result[0] if result else 0
            
            # Test table sizes
            tables_info = {}
            tables = ['predictions', 'fixtures', 'betting_codes', 'punters', 'bookmakers']
            
            for table in tables:
                try:
                    count_result = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                    tables_info[table] = count_result[0] if count_result else 0
                except Exception as e:
                    tables_info[table] = f"Error: {str(e)}"
            
            query_time = time.time() - start_time
            
            db.close()
            
            database_health = {
                'query_time': query_time,
                'predictions_count': predictions_count,
                'tables_info': tables_info,
                'healthy': query_time < 1.0,
                'timestamp': datetime.now().isoformat()
            }
            
            if query_time > 1.0:
                self.alerts.append(f"Slow database query: {query_time:.2f}s")
            
            return database_health
            
        except Exception as e:
            self.alerts.append(f"Database health check failed: {str(e)}")
            return {'healthy': False, 'error': str(e)}
    
    def check_ml_models(self) -> Dict[str, Any]:
        """Check ML models availability and performance."""
        logger.info("🤖 Checking ML models...")
        
        try:
            from services.quick_prediction_service import quick_prediction_service
            
            start_time = time.time()
            result = quick_prediction_service.get_predictions_for_date("2024-01-01")
            prediction_time = time.time() - start_time
            
            models_health = {
                'prediction_time': prediction_time,
                'service_available': result is not None,
                'status': result.get('status') if result else 'unknown',
                'timestamp': datetime.now().isoformat()
            }
            
            if prediction_time > 5.0:
                self.alerts.append(f"Slow ML prediction: {prediction_time:.2f}s")
            
            if not result or result.get('status') == 'error':
                self.alerts.append("ML prediction service not working properly")
            
            return models_health
            
        except Exception as e:
            self.alerts.append(f"ML models check failed: {str(e)}")
            return {'service_available': False, 'error': str(e)}
    
    def check_external_apis(self) -> Dict[str, Any]:
        """Check external API connectivity."""
        logger.info("🌐 Checking external APIs...")
        
        apis_health = {}
        
        # Check Football Data API
        football_key = os.getenv('FOOTBALL_DATA_API_KEY')
        if football_key:
            try:
                response = requests.get(
                    'https://api.football-data.org/v4/competitions',
                    headers={'X-Auth-Token': football_key},
                    timeout=10
                )
                apis_health['football_data'] = {
                    'status_code': response.status_code,
                    'healthy': response.status_code in [200, 429],  # 429 = rate limited but working
                    'timestamp': datetime.now().isoformat()
                }
            except Exception as e:
                apis_health['football_data'] = {
                    'healthy': False,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                }
                self.alerts.append(f"Football Data API check failed: {str(e)}")
        
        return apis_health
    
    def check_log_files(self) -> Dict[str, Any]:
        """Check log files for errors and warnings."""
        logger.info("📋 Checking log files...")
        
        log_files = ['logs/monitor.log', 'logs/app.log', 'server.log']
        log_analysis = {}
        
        for log_file in log_files:
            if os.path.exists(log_file):
                try:
                    with open(log_file, 'r') as f:
                        lines = f.readlines()
                    
                    # Count recent errors (last 1000 lines)
                    recent_lines = lines[-1000:] if len(lines) > 1000 else lines
                    error_count = sum(1 for line in recent_lines if 'ERROR' in line)
                    warning_count = sum(1 for line in recent_lines if 'WARNING' in line)
                    
                    log_analysis[log_file] = {
                        'total_lines': len(lines),
                        'recent_errors': error_count,
                        'recent_warnings': warning_count,
                        'file_size_mb': os.path.getsize(log_file) / (1024*1024)
                    }
                    
                    if error_count > 10:
                        self.alerts.append(f"High error count in {log_file}: {error_count}")
                    
                except Exception as e:
                    log_analysis[log_file] = {'error': str(e)}
        
        return log_analysis
    
    def generate_health_report(self) -> Dict[str, Any]:
        """Generate comprehensive health report."""
        logger.info("📊 Generating health report...")
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'overall_health': 'healthy',
            'alerts': self.alerts,
            'checks': {}
        }
        
        # Run all health checks
        checks = [
            ('api_health', self.check_api_health),
            ('system_resources', self.check_system_resources),
            ('database_health', self.check_database_health),
            ('ml_models', self.check_ml_models),
            ('external_apis', self.check_external_apis),
            ('log_files', self.check_log_files)
        ]
        
        for check_name, check_func in checks:
            try:
                report['checks'][check_name] = check_func()
            except Exception as e:
                report['checks'][check_name] = {'error': str(e)}
                self.alerts.append(f"Health check {check_name} failed: {str(e)}")
        
        # Determine overall health
        if self.alerts:
            report['overall_health'] = 'degraded' if len(self.alerts) < 5 else 'unhealthy'
        
        return report
    
    def save_report(self, report: Dict[str, Any]) -> str:
        """Save health report to file."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = f"logs/health_report_{timestamp}.json"
        
        try:
            import json
            with open(report_file, 'w') as f:
                json.dump(report, f, indent=2)
            
            logger.info(f"📄 Health report saved to: {report_file}")
            return report_file
            
        except Exception as e:
            logger.error(f"Failed to save health report: {e}")
            return ""
    
    def send_alerts(self, report: Dict[str, Any]):
        """Send alerts if there are issues."""
        if not self.alerts:
            return
        
        alert_message = f"""
🚨 BetSightly Production Alert

Time: {report['timestamp']}
Overall Health: {report['overall_health']}

Alerts ({len(self.alerts)}):
{chr(10).join(f"- {alert}" for alert in self.alerts)}

Please check the system immediately.
"""
        
        # Log alerts
        logger.warning(alert_message)
        
        # In production, you would send this via email, Slack, etc.
        # For now, just log it
        
    def monitor_continuously(self, interval: int = 300):
        """Run continuous monitoring."""
        logger.info(f"🔄 Starting continuous monitoring (interval: {interval}s)")
        
        while True:
            try:
                self.alerts = []  # Reset alerts
                report = self.generate_health_report()
                
                # Save report
                self.save_report(report)
                
                # Send alerts if needed
                if self.alerts:
                    self.send_alerts(report)
                else:
                    logger.info("✅ All systems healthy")
                
                # Wait for next check
                time.sleep(interval)
                
            except KeyboardInterrupt:
                logger.info("Monitoring stopped by user")
                break
            except Exception as e:
                logger.error(f"Monitoring error: {e}")
                time.sleep(60)  # Wait 1 minute before retrying

def main():
    """Main monitoring function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Production monitoring for BetSightly")
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL for API")
    parser.add_argument("--continuous", action="store_true", help="Run continuous monitoring")
    parser.add_argument("--interval", type=int, default=300, help="Monitoring interval in seconds")
    
    args = parser.parse_args()
    
    monitor = ProductionMonitor(args.url)
    
    if args.continuous:
        monitor.monitor_continuously(args.interval)
    else:
        # Run single health check
        report = monitor.generate_health_report()
        report_file = monitor.save_report(report)
        
        print(f"\n{'='*50}")
        print("HEALTH CHECK SUMMARY")
        print(f"{'='*50}")
        print(f"Overall Health: {report['overall_health']}")
        print(f"Alerts: {len(monitor.alerts)}")
        print(f"Report saved to: {report_file}")
        
        if monitor.alerts:
            print("\nAlerts:")
            for alert in monitor.alerts:
                print(f"  ⚠️  {alert}")
        else:
            print("\n✅ All systems healthy!")

if __name__ == '__main__':
    main()
