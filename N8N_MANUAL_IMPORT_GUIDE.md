# 📋 N8N Manual Workflow Import Guide

## 🎯 **QUICK SETUP INSTRUCTIONS**

The N8N dashboard is already open at: **http://localhost:5678**

### **Step 1: Import Workflows**

1. **In N8N Dashboard:**
   - Click **"Workflows"** in the left sidebar
   - Click **"+ Add Workflow"** 
   - Click **"Import from file"** or **"Import from URL"**

2. **Import these 3 workflow files:**
   - `n8n_workflows/betsightly_system_monitor.json`
   - `n8n_workflows/betsightly_performance_alerts.json`
   - `n8n_workflows/betsightly_daily_summary.json`

### **Step 2: Configure Telegram Credentials**

1. **Create Telegram Credential:**
   - Go to **"Credentials"** → **"Add Credential"**
   - Select **"Telegram"**
   - Name: `BetSightly Bot`
   - Access Token: `7299245660:AAHS2EB9PABvLYAh37WS_lv8BO3OhAVEFqw`
   - Save the credential

2. **Update Chat ID in workflows:**
   - Open each imported workflow
   - Find Telegram nodes
   - Update Chat ID to: `-4971231188`
   - Select the `BetSightly Bot` credential

### **Step 3: Activate Workflows**

1. **For each workflow:**
   - Open the workflow
   - Click **"Active"** toggle (top right)
   - Save the workflow

### **Step 4: Test the System**

1. **Test API Health:**
   ```bash
   curl http://localhost:8000/api/n8n/health
   ```

2. **Test Telegram Connection:**
   ```bash
   curl -X POST "https://api.telegram.org/bot7299245660:AAHS2EB9PABvLYAh37WS_lv8BO3OhAVEFqw/sendMessage" \
     -d "chat_id=-4971231188&text=🧪 N8N Test Message - BetSightly Monitoring Active!"
   ```

## 🔧 **WORKFLOW DETAILS**

### **1. System Monitor (Every 5 minutes)**
- **Function:** Continuous health monitoring
- **Monitors:** API status, database health, resource usage
- **Alerts:** System failures, high resource usage

### **2. Performance Alerts (Every hour)**
- **Function:** Performance monitoring and alerts
- **Monitors:** Accuracy drops, system performance
- **Alerts:** Performance degradation, emergency conditions

### **3. Daily Summary (8 AM daily)**
- **Function:** Daily performance summary
- **Reports:** Predictions count, accuracy, best models, ROI analysis
- **Schedule:** Every day at 8:00 AM

## 🎉 **EXPECTED RESULTS**

Once configured, you'll receive:

### **📅 Daily Summary (8 AM)**
```
🎯 BetSightly Daily Summary
📅 Date: 2025-07-12

📊 Today's Performance:
• Total Predictions: 12
• Accuracy: 87.5%
• Successful: 10
• Failed: 2

🏆 Best Performing Model:
• Model: advanced_match_result
• Accuracy: 92.3%

📈 Trend: Improving
💰 Potential ROI: 15.5%
```

### **🚨 Performance Alerts**
```
🚨 PERFORMANCE ALERT

⚠️ Alert Type: Accuracy Below Threshold
📉 Current Accuracy: 75.2%
🎯 Threshold: 80.0%

🔧 Recommended Actions:
• Review recent predictions
• Check data quality
• Consider model retraining
```

### **🔴 System Failures**
```
🔴 SYSTEM FAILURE DETECTED
⚠️ BetSightly API is DOWN

⏰ Time: 2025-07-12 14:30:25
🔧 IMMEDIATE ACTION REQUIRED
```

## ✅ **COMPLETION CHECKLIST**

- [ ] Import 3 workflow files
- [ ] Create Telegram credential
- [ ] Update Chat ID in all workflows
- [ ] Activate all workflows
- [ ] Test Telegram connection
- [ ] Verify monitoring alerts

**🎯 Your BetSightly system will have enterprise-grade monitoring once complete!**
