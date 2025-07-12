# 🚨 **N8N + Telegram Integration for BetSightly**

## 🎯 **COMPLETE ALERT SYSTEM SETUP**

### **✅ What N8N Can Do for BetSightly:**

#### **🚨 TELEGRAM ALERTS**
- **Real-time failure/success notifications**
- **Performance drop alerts** (accuracy below thresholds)
- **Daily prediction summaries**
- **Weekly performance reports**
- **Model training completion alerts**
- **System health monitoring**

#### **🔄 AUTOMATION WORKFLOWS**
- **Automated data pipeline monitoring**
- **Scheduled health checks**
- **Error recovery workflows**
- **Performance optimization triggers**
- **Database backup notifications**
- **API endpoint monitoring**

---

## 🛠️ **STEP-BY-STEP SETUP GUIDE**

### **🚀 STEP 1: Start N8N**
```bash
# Start N8N (will run on http://localhost:5678)
n8n start

# Or run in background
nohup n8n start > n8n.log 2>&1 &
```

### **📱 STEP 2: Create Telegram Bot**
1. **Message @BotFather on Telegram**
2. **Send `/newbot`**
3. **Choose bot name**: `BetSightly Alert Bot`
4. **Choose username**: `@betsightly_alerts_bot`
5. **Copy the Bot Token** (e.g., `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### **🔑 STEP 3: Get Your Chat ID**
```bash
# Send a message to your bot first, then:
curl https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates

# Look for "chat":{"id":YOUR_CHAT_ID} in the response
```

### **🌐 STEP 4: Create N8N Workflows**

#### **📊 Workflow 1: Daily Prediction Summary**
```json
{
  "name": "BetSightly Daily Summary",
  "nodes": [
    {
      "name": "Schedule Daily",
      "type": "n8n-nodes-base.cron",
      "parameters": {
        "rule": {
          "hour": 8,
          "minute": 0
        }
      }
    },
    {
      "name": "Get Analytics",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "url": "http://localhost:8000/api/analytics/dashboard?days=1",
        "method": "GET"
      }
    },
    {
      "name": "Send to Telegram",
      "type": "n8n-nodes-base.telegram",
      "parameters": {
        "chatId": "YOUR_CHAT_ID",
        "text": "🎯 **BetSightly Daily Summary**\n\n📊 Predictions: {{$json.total_predictions}}\n✅ Accuracy: {{$json.overall_accuracy}}%\n🏆 Best Model: {{$json.best_model}}\n📈 Performance: {{$json.performance_trend}}"
      }
    }
  ]
}
```

#### **🚨 Workflow 2: Performance Alert System**
```json
{
  "name": "BetSightly Performance Alerts",
  "nodes": [
    {
      "name": "Check Every Hour",
      "type": "n8n-nodes-base.cron",
      "parameters": {
        "rule": {
          "minute": 0
        }
      }
    },
    {
      "name": "Check Performance",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "url": "http://localhost:8000/api/analytics/alerts",
        "method": "GET"
      }
    },
    {
      "name": "Filter Alerts",
      "type": "n8n-nodes-base.if",
      "parameters": {
        "conditions": {
          "boolean": [
            {
              "value1": "={{$json.has_alerts}}",
              "value2": true
            }
          ]
        }
      }
    },
    {
      "name": "Send Alert",
      "type": "n8n-nodes-base.telegram",
      "parameters": {
        "chatId": "YOUR_CHAT_ID",
        "text": "🚨 **PERFORMANCE ALERT**\n\n⚠️ {{$json.alert_type}}\n📉 Current Accuracy: {{$json.current_accuracy}}%\n🎯 Threshold: {{$json.threshold}}%\n🔧 Action Required: {{$json.recommendation}}"
      }
    }
  ]
}
```

#### **✅ Workflow 3: Success/Failure Monitoring**
```json
{
  "name": "BetSightly System Monitor",
  "nodes": [
    {
      "name": "Check Every 5 Minutes",
      "type": "n8n-nodes-base.cron",
      "parameters": {
        "rule": {
          "minute": "*/5"
        }
      }
    },
    {
      "name": "Health Check",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "url": "http://localhost:8000/health",
        "method": "GET",
        "options": {
          "timeout": 10000
        }
      }
    },
    {
      "name": "Check Status",
      "type": "n8n-nodes-base.if",
      "parameters": {
        "conditions": {
          "number": [
            {
              "value1": "={{$json.status_code}}",
              "operation": "notEqual",
              "value2": 200
            }
          ]
        }
      }
    },
    {
      "name": "Send Failure Alert",
      "type": "n8n-nodes-base.telegram",
      "parameters": {
        "chatId": "YOUR_CHAT_ID",
        "text": "🔴 **SYSTEM FAILURE**\n\n❌ BetSightly API is DOWN\n⏰ Time: {{DateTime.now().toISO()}}\n🔧 Please check the system immediately!"
      }
    }
  ]
}
```

---

## 🎯 **ADVANCED N8N USE CASES FOR BETSIGHTLY**

### **📈 1. AUTOMATED REPORTING**
- **Weekly performance summaries**
- **Monthly model comparison reports**
- **Seasonal trend analysis**
- **ROI calculations and reports**

### **🔄 2. DATA PIPELINE AUTOMATION**
- **Automated data fetching from Football-Data.org**
- **Model retraining triggers**
- **Database cleanup and optimization**
- **Backup and recovery workflows**

### **🎯 3. PREDICTION WORKFLOW AUTOMATION**
- **Automated daily prediction generation**
- **Result correlation scheduling**
- **Performance analysis triggers**
- **Model selection optimization**

### **🚨 4. ADVANCED MONITORING**
- **API endpoint monitoring**
- **Database performance tracking**
- **Memory and CPU usage alerts**
- **Disk space monitoring**

### **📊 5. BUSINESS INTELLIGENCE**
- **Automated dashboard updates**
- **KPI tracking and alerts**
- **Trend analysis and forecasting**
- **Competitive analysis automation**

---

## 🛠️ **IMPLEMENTATION STEPS**

### **🔧 1. Create BetSightly Health Endpoint**
```python
# Add to your FastAPI app
@app.get("/health")
async def health_check():
    try:
        # Check database connection
        db_status = await check_database()
        
        # Check recent predictions
        recent_predictions = await get_recent_predictions(hours=1)
        
        # Check model performance
        performance = await get_current_performance()
        
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "database": db_status,
            "recent_predictions": len(recent_predictions),
            "performance": performance,
            "uptime": get_uptime()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }
```

### **📱 2. Enhanced Telegram Notifications**
```python
# Add to your analytics service
async def send_telegram_alert(message: str, alert_type: str = "info"):
    """Send alert to Telegram via N8N webhook"""
    webhook_url = "http://localhost:5678/webhook/betsightly-alerts"
    
    payload = {
        "message": message,
        "alert_type": alert_type,
        "timestamp": datetime.now().isoformat(),
        "system": "BetSightly"
    }
    
    async with httpx.AsyncClient() as client:
        await client.post(webhook_url, json=payload)
```

### **🔄 3. Automated Workflows**
```python
# Trigger N8N workflows from your code
async def trigger_n8n_workflow(workflow_name: str, data: dict):
    """Trigger N8N workflow with data"""
    webhook_url = f"http://localhost:5678/webhook/{workflow_name}"
    
    async with httpx.AsyncClient() as client:
        response = await client.post(webhook_url, json=data)
        return response.status_code == 200
```

---

## 🎉 **WHAT YOU'LL GET**

### **📱 TELEGRAM NOTIFICATIONS**
- **🎯 Daily Summary**: "Today's predictions: 15, Accuracy: 87%, Best model: XGBoost"
- **🚨 Performance Alert**: "Warning: Accuracy dropped to 75% (threshold: 80%)"
- **✅ Success**: "Daily correlation completed successfully - 12/15 predictions correct"
- **❌ Failure**: "System error: API endpoint not responding"
- **📊 Weekly Report**: "Week summary: 105 predictions, 89% accuracy, +5% improvement"

### **🔄 AUTOMATED WORKFLOWS**
- **Health monitoring** every 5 minutes
- **Performance checks** every hour
- **Daily summaries** at 8 AM
- **Weekly reports** on Sundays
- **Instant failure alerts**

### **📈 BUSINESS INTELLIGENCE**
- **Trend analysis** and forecasting
- **Model performance tracking**
- **ROI calculations**
- **Competitive benchmarking**

---

## 🚀 **GETTING STARTED**

### **🔧 Quick Setup (5 minutes)**
1. **Start N8N**: `n8n start`
2. **Open browser**: `http://localhost:5678`
3. **Create Telegram bot** with @BotFather
4. **Import workflows** (copy-paste JSON above)
5. **Configure credentials** (Bot token, Chat ID)
6. **Activate workflows**

### **📱 Test Your Setup**
```bash
# Test health endpoint
curl http://localhost:8000/health

# Test N8N webhook
curl -X POST http://localhost:5678/webhook/test \
  -H "Content-Type: application/json" \
  -d '{"message": "Test alert from BetSightly!"}'
```

---

## 🎯 **SUMMARY**

**🎉 YES! N8N is perfect for BetSightly alerts!**

✅ **Real-time Telegram notifications** for all events  
✅ **Automated monitoring** and health checks  
✅ **Performance alerts** when accuracy drops  
✅ **Daily/weekly summaries** automatically  
✅ **Failure detection** and instant alerts  
✅ **Business intelligence** and reporting automation  

**Your BetSightly system will now have enterprise-grade monitoring and alerting that keeps you informed 24/7!** 🚀

---

## 🚀 **QUICK START GUIDE**

### **⚡ 1-Minute Setup**
```bash
# 1. Start N8N
./start_n8n.sh

# 2. Run setup script (in another terminal)
python3 scripts/setup_n8n.py

# 3. Test integration
curl -X POST http://localhost:8000/api/n8n/test-alert
```

### **📱 Create Telegram Bot (2 minutes)**
1. **Open Telegram** and message **@BotFather**
2. **Send**: `/newbot`
3. **Bot Name**: `BetSightly Alert Bot`
4. **Username**: `@your_betsightly_bot`
5. **Copy the token** (looks like: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)
6. **Get your Chat ID**:
   - Send a message to your bot
   - Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   - Find your chat ID in the response

### **🔧 Environment Setup**
```bash
# Create .env file with your credentials
echo "TELEGRAM_BOT_TOKEN=your_bot_token_here" >> .env
echo "TELEGRAM_CHAT_ID=your_chat_id_here" >> .env
```

---

## 📊 **WHAT YOU'LL RECEIVE**

### **📱 Daily Messages (8 AM)**
```
🎯 BetSightly Daily Summary
📅 Date: 2025-01-15

📊 Today's Performance:
• Total Predictions: 12
• Accuracy: 87.5%
• Successful: 10
• Failed: 2

🏆 Best Performing Model:
• Model: xgboost_match_result
• Accuracy: 92.3%

📈 Trend: Improving
• Compared to yesterday: +5.2%

💰 ROI Analysis:
• Potential ROI: 15.5%
• Risk Level: Low

🔗 Dashboard: http://localhost:3000/dashboard
```

### **🚨 Performance Alerts**
```
🚨 PERFORMANCE ALERT

⚠️ Alert Type: Accuracy Below Threshold
📉 Current Accuracy: 75.2%
🎯 Threshold: 80.0%
📊 Sample Size: 15 predictions

🔍 Details:
• Worst Model: pytorch_over_under_2_5 (68.1%)
• Best Model: xgboost_match_result (89.4%)
• Trend: Declining

🔧 Recommended Actions:
• Review recent predictions for patterns
• Check data quality and sources
• Consider model retraining
```

### **🔴 System Failures**
```
🔴 SYSTEM FAILURE DETECTED
⚠️ BetSightly API is DOWN

⏰ Time: 2025-01-15 14:30:25
🚨 Status: unhealthy
❌ Error: Database connection failed

🔧 IMMEDIATE ACTIONS REQUIRED:
1. Check server status
2. Verify database connection
3. Review system logs
4. Restart services if necessary
```

---

## 🎯 **ADVANCED FEATURES**

### **🤖 Automated Workflows Available**
1. **Daily Summary** - 8 AM every day
2. **Performance Monitoring** - Every hour
3. **System Health Check** - Every 5 minutes
4. **Weekly Reports** - Sundays at 9 AM
5. **Emergency Alerts** - Immediate when critical issues occur

### **📊 Custom Alerts You Can Add**
- **High-value bet opportunities** (accuracy > 90%)
- **Model training completion** notifications
- **Data pipeline failures**
- **Unusual betting patterns** detected
- **ROI threshold** achievements

### **🔄 Integration Possibilities**
- **Discord** notifications
- **Slack** team alerts
- **Email** reports
- **SMS** critical alerts
- **Webhook** integrations with other tools

---

## 🛠️ **TROUBLESHOOTING**

### **❌ Common Issues**

#### **N8N Won't Start**
```bash
# Check if port 5678 is in use
lsof -i :5678

# Kill existing N8N process
pkill -f n8n

# Restart N8N
./start_n8n.sh
```

#### **Telegram Not Working**
```bash
# Test bot token
curl https://api.telegram.org/bot<YOUR_TOKEN>/getMe

# Test sending message
curl -X POST "https://api.telegram.org/bot<YOUR_TOKEN>/sendMessage" \
  -d "chat_id=<YOUR_CHAT_ID>&text=Test message"
```

#### **BetSightly API Not Responding**
```bash
# Check API health
curl http://localhost:8000/health

# Check if FastAPI is running
ps aux | grep uvicorn

# Restart BetSightly
python -m uvicorn main:app --reload
```

### **🔧 Debug Mode**
```bash
# Enable N8N debug logging
export N8N_LOG_LEVEL=debug
./start_n8n.sh

# Check N8N logs
tail -f ~/.n8n/logs/n8n.log
```

---

## 📈 **MONITORING DASHBOARD**

### **🌐 Access Points**
- **N8N Interface**: http://localhost:5678
- **BetSightly API**: http://localhost:8000/docs
- **Analytics Dashboard**: http://localhost:8000/api/analytics/dashboard
- **System Health**: http://localhost:8000/api/n8n/health

### **📊 Key Metrics to Monitor**
- **Prediction Accuracy** (target: >80%)
- **System Uptime** (target: >99%)
- **Response Time** (target: <2s)
- **Error Rate** (target: <1%)
- **Data Freshness** (target: <1 hour old)

---

## 🎉 **SUCCESS METRICS**

After setup, you should see:
- ✅ **Daily Telegram messages** with performance summaries
- ✅ **Immediate alerts** when accuracy drops below 80%
- ✅ **System failure notifications** within 5 minutes
- ✅ **Weekly performance reports** every Sunday
- ✅ **Real-time monitoring** of all 39 ML models

**🚀 Your BetSightly system now rivals professional betting companies with enterprise-grade monitoring and alerting!**
