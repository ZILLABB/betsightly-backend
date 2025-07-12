# 📥 **N8N Workflow Import Instructions**

## 🎯 **Step-by-Step Import Process**

### **📂 Files to Import (in this order):**

1. **`betsightly_system_monitor.json`** - System health monitoring (every 5 minutes)
2. **`betsightly_performance_alerts.json`** - Performance alerts (every hour)  
3. **`betsightly_daily_summary.json`** - Daily summaries (8 AM daily)

---

## 🔄 **Import Process for Each File**

### **Step 1: Create New Workflow**
1. In N8N dashboard, click **"Workflows"** in left sidebar
2. Click the **"+"** button to create new workflow
3. You'll see a blank workflow canvas

### **Step 2: Import Workflow File**
1. Click the **"..."** menu (three dots) in the top right corner
2. Select **"Import from file"**
3. Click **"Choose file"** or drag and drop
4. Navigate to: `/home/kali/Desktop/betsightly-backend/n8n_workflows/`
5. Select the workflow file (start with `betsightly_system_monitor.json`)
6. Click **"Import"**

### **Step 3: Configure Workflow**
1. The workflow will appear on the canvas
2. **IMPORTANT**: Click **"Save"** to save the workflow
3. Give it a name if prompted (or keep the default name)

### **Step 4: Activate Workflow**
1. Look for the **"Active"** toggle switch (usually top right)
2. Click to turn it **ON** (should turn green/blue)
3. Click **"Save"** again to save the active state

### **Step 5: Verify Workflow**
1. Check that the workflow shows as **"Active"**
2. Look for any error indicators (red dots or warnings)
3. If you see errors, they're usually about missing credentials

---

## 🔧 **Telegram Credentials Setup**

If you see Telegram-related errors:

1. Go to **"Credentials"** in left sidebar
2. Click **"Add Credential"**
3. Search for **"Telegram"**
4. Configure:
   - **Name**: `BetSightly Bot`
   - **Access Token**: `7299245660:AAHS2EB9PABvLYAh37WS_lv8BO3OhAVEFqw`
5. Click **"Save"**
6. Go back to your workflows and assign this credential to Telegram nodes

---

## ✅ **Success Indicators**

You'll know it worked when:
- ✅ All 3 workflows are imported
- ✅ All 3 workflows show as "Active" 
- ✅ No error indicators on the workflows
- ✅ You receive test messages in Telegram

---

## 🚨 **Troubleshooting**

### **Common Issues:**

**"Missing Credentials" Error:**
- Go to Credentials → Add Credential → Telegram
- Use the bot token provided above

**"Webhook URL" Errors:**
- These are normal and will resolve once workflows are active

**"Chat ID" Errors:**
- Make sure TELEGRAM_CHAT_ID is set in your .env file
- Should be: `-4971231188`

**Import Fails:**
- Make sure you're selecting the correct .json files
- Try refreshing the N8N page and importing again

---

## 🎯 **Expected Results**

Once all workflows are imported and active:

### **🔍 System Monitor** (Every 5 minutes)
- Checks API health
- Monitors system resources
- Sends alerts if anything fails

### **🚨 Performance Alerts** (Every hour)  
- Checks prediction accuracy
- Alerts if performance drops
- Provides recommendations

### **📅 Daily Summary** (8 AM daily)
- Daily performance report
- Best model identification
- ROI analysis

---

## 🎉 **Completion Verification**

After importing all workflows, run this command to verify:
```bash
python complete_n8n_setup_final.py
```

You should see 100% completion status!
