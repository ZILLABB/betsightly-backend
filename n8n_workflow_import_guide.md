# 🚀 N8N Workflow Import Guide - BetSightly

## ✅ **CURRENT STATUS**
- **N8N Server**: ✅ Running on http://localhost:5678
- **BetSightly API**: ✅ Running on http://localhost:8000
- **Telegram Bot**: ✅ Working (@BetSightlyBot)
- **Chat ID**: ✅ Configured (-4971231188)
- **Test Message**: ✅ Sent successfully

## 📋 **QUICK IMPORT STEPS (5 minutes)**

### **Step 1: Open N8N Dashboard**
- Go to: http://localhost:5678
- You should see the N8N interface

### **Step 2: Import Workflows**
For each of these 3 files, do the following:

1. **Click "Import from file"** (or the "+" button → "Import from file")
2. **Select file** from your `n8n_workflows/` folder:
   - `betsightly_daily_summary.json`
   - `betsightly_performance_alerts.json`
   - `betsightly_system_monitor.json`
3. **Click "Import"**

### **Step 3: Configure Telegram Credentials**
1. Go to **Settings** → **Credentials** (or click the key icon)
2. Click **"Add Credential"**
3. Select **"Telegram"**
4. Enter:
   - **Name**: `BetSightly Bot`
   - **Access Token**: `7299245660:AAHS2EB9PABvLYAh37WS_lv8BO3OhAVEFqw`
5. Click **"Save"**

### **Step 4: Update Workflows**
For each imported workflow:
1. **Open the workflow**
2. **Find Telegram nodes** (usually at the end)
3. **Set Credential** to `BetSightly Bot`
4. **Set Chat ID** to `-4971231188`
5. **Save the workflow**

### **Step 5: Activate Workflows**
1. For each workflow, toggle the **"Active"** switch to ON
2. You should see them listed as "Active" in the workflows list

## 📊 **WHAT EACH WORKFLOW DOES**

### 🌅 **Daily Summary** (`betsightly_daily_summary.json`)
- **Runs**: Every day at 8:00 AM
- **Sends**: Daily performance summary
- **Includes**: Predictions count, accuracy, best models

### 🚨 **Performance Alerts** (`betsightly_performance_alerts.json`)
- **Runs**: Every hour
- **Monitors**: System performance
- **Alerts**: When accuracy drops below 80%

### 🔍 **System Monitor** (`betsightly_system_monitor.json`)
- **Runs**: Every 5 minutes
- **Checks**: API health, database status
- **Alerts**: System failures

## 🧪 **TEST THE SETUP**

After importing and activating, test each workflow:
1. **Open a workflow**
2. **Click "Test workflow"**
3. **Check your Telegram** for the test message

## 🎯 **EXPECTED TELEGRAM MESSAGES**

Once active, you'll receive:

### **Daily Summary (8 AM)**
```
🎯 BetSightly Daily Summary
📅 Date: 2025-07-12

📊 Today's Performance:
• Total Predictions: 12
• Accuracy: 87.5%
• Best Model: xgboost_match_result

📈 Trend: Improving
```

### **Performance Alerts (Hourly)**
```
🚨 PERFORMANCE ALERT
⚠️ Accuracy dropped to 75%
🎯 Threshold: 80%
🔧 Action needed: Check models
```

### **System Failures (Real-time)**
```
🔴 SYSTEM FAILURE
⚠️ BetSightly API is DOWN
⏰ Time: 2025-07-12 15:30
🔧 IMMEDIATE ACTION REQUIRED
```

## ✅ **COMPLETION CHECKLIST**

- [ ] N8N dashboard opened
- [ ] Telegram credential created
- [ ] Daily summary workflow imported
- [ ] Performance alerts workflow imported  
- [ ] System monitor workflow imported
- [ ] All workflows configured with correct Chat ID
- [ ] All workflows activated
- [ ] Test messages received in Telegram

## 🆘 **NEED HELP?**

If you encounter issues:
1. **Check N8N logs** in the terminal
2. **Verify Telegram credentials** are correct
3. **Test individual workflow nodes**
4. **Run the test script again**: `python test_telegram_integration.py`

**🎉 Once complete, you'll have enterprise-grade monitoring for your BetSightly system!**
