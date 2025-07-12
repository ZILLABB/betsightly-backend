# 🚀 BetSightly Production Deployment Guide

## 🎯 **OPTIMAL DEPLOYMENT STRATEGY**

### **🥇 RECOMMENDED: DigitalOcean App Platform**

**Why DigitalOcean?**
- ✅ Excellent Docker support
- ✅ Managed databases included
- ✅ Auto-scaling capabilities
- ✅ Cost-effective ($25-50/month)
- ✅ Simple deployment process
- ✅ Built-in monitoring

### **📋 DEPLOYMENT CHECKLIST**

#### **Phase 1: Infrastructure Setup (Day 1-2)**
```bash
# 1. Create DigitalOcean account and project
# 2. Set up managed PostgreSQL database
# 3. Set up managed Redis instance
# 4. Configure environment variables
# 5. Set up domain and SSL certificates
```

#### **Phase 2: Application Deployment (Day 3-4)**
```bash
# 1. Build and test Docker image locally
docker build -f Dockerfile.production -t betsightly-backend .
docker run -p 8000:8000 betsightly-backend

# 2. Deploy to DigitalOcean App Platform
doctl apps create --spec .do/app.yaml

# 3. Configure auto-scaling
# 4. Set up health checks
# 5. Configure logging and monitoring
```

#### **Phase 3: Optimization (Day 5-7)**
```bash
# 1. Performance tuning
# 2. Cache optimization
# 3. Database indexing
# 4. Load testing
# 5. Security hardening
```

### **🔧 INFRASTRUCTURE CONFIGURATION**

#### **App Platform Specification**
```yaml
# .do/app.yaml
name: betsightly-backend
services:
- name: api
  source_dir: /
  github:
    repo: your-username/betsightly-backend
    branch: main
  run_command: gunicorn main:app --bind 0.0.0.0:8000 --workers 2 --worker-class uvicorn.workers.UvicornWorker
  environment_slug: python
  instance_count: 2
  instance_size_slug: professional-xs  # $12/month per instance
  health_check:
    http_path: /api/health
  envs:
  - key: ENVIRONMENT
    value: production
  - key: DATABASE_URL
    value: ${db.DATABASE_URL}
  - key: REDIS_URL
    value: ${redis.REDIS_URL}

databases:
- name: db
  engine: PG
  version: "15"
  size: db-s-1vcpu-1gb  # $15/month

- name: redis
  engine: REDIS
  version: "7"
  size: db-s-1vcpu-1gb  # $15/month

workers:
- name: celery-worker
  source_dir: /
  run_command: celery -A app.celery worker --loglevel=info
  instance_count: 1
  instance_size_slug: basic-xxs  # $5/month

- name: celery-beat
  source_dir: /
  run_command: celery -A app.celery beat --loglevel=info
  instance_count: 1
  instance_size_slug: basic-xxs  # $5/month
```

### **💰 COST BREAKDOWN**
```
API Instances (2x): $24/month
PostgreSQL DB:     $15/month
Redis Cache:       $15/month
Celery Workers:    $10/month
Total:            ~$64/month
```

### **🔄 ALTERNATIVE PLATFORMS**

#### **🥈 AWS ECS/Fargate (Enterprise)**
```
Pros: Enterprise-grade, excellent scaling, AWS ecosystem
Cons: More complex, higher cost (~$100-200/month)
Best for: High-traffic production, enterprise requirements
```

#### **🥉 Railway (Simple)**
```
Pros: Very simple deployment, good for MVP
Cons: Limited scaling, fewer features
Cost: ~$20-40/month
Best for: Quick deployment, testing
```

### **📊 PERFORMANCE TARGETS**

#### **Response Time Targets**
```
Cached Predictions:    < 200ms (95th percentile)
Real-time Predictions: < 1.5s (95th percentile)
Health Checks:         < 100ms
Database Queries:      < 50ms
```

#### **Availability Targets**
```
Uptime:               99.9% (8.76 hours downtime/year)
Error Rate:           < 0.1%
Successful Requests:  > 99.9%
```

#### **Scalability Targets**
```
Concurrent Users:     1,000+
Requests per Second:  100+
Daily Predictions:    10,000+
Model Load Time:      < 30s
```

### **🛡️ SECURITY CONFIGURATION**

#### **Environment Variables**
```bash
# Production environment variables
ENVIRONMENT=production
SECRET_KEY=your-super-secret-key-here
DATABASE_URL=postgresql://user:pass@host:5432/db
REDIS_URL=redis://user:pass@host:6379/0
FOOTBALL_DATA_API_KEY=your-api-key
API_FOOTBALL_API_KEY=your-api-key
TELEGRAM_BOT_TOKEN=your-bot-token
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
CORS_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
```

#### **Security Headers**
```python
# Add to main.py
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

app.add_middleware(
    TrustedHostMiddleware, 
    allowed_hosts=["yourdomain.com", "*.yourdomain.com"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
```

### **📈 MONITORING SETUP**

#### **Health Checks**
```python
# Enhanced health check endpoint
@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "models_loaded": len(prediction_service.models),
        "database": "connected",
        "redis": "connected",
        "version": "1.0.0"
    }
```

#### **Metrics Collection**
```python
# Add Prometheus metrics
from prometheus_client import Counter, Histogram, generate_latest

prediction_counter = Counter('predictions_total', 'Total predictions made')
prediction_duration = Histogram('prediction_duration_seconds', 'Prediction duration')

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type="text/plain")
```

### **🔄 CI/CD PIPELINE**

#### **GitHub Actions Workflow**
```yaml
# .github/workflows/deploy.yml
name: Deploy to Production

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    
    - name: Deploy to DigitalOcean
      uses: digitalocean/app_action@v1
      with:
        app_name: betsightly-backend
        token: ${{ secrets.DIGITALOCEAN_ACCESS_TOKEN }}
```

### **📋 POST-DEPLOYMENT CHECKLIST**

#### **Immediate (Day 1)**
- [ ] Verify all 33 models are loading correctly
- [ ] Test all API endpoints
- [ ] Verify database connections
- [ ] Check Redis cache functionality
- [ ] Test Telegram bot integration
- [ ] Verify SSL certificates
- [ ] Check health endpoints

#### **Week 1**
- [ ] Monitor response times
- [ ] Check error rates
- [ ] Verify scheduled tasks
- [ ] Test auto-scaling
- [ ] Monitor resource usage
- [ ] Check logs for issues
- [ ] Verify backup systems

#### **Month 1**
- [ ] Performance optimization
- [ ] Cost optimization
- [ ] Security audit
- [ ] Load testing
- [ ] Disaster recovery testing
- [ ] Documentation updates
- [ ] Team training

### **🎯 SUCCESS METRICS**

After deployment, you should achieve:
- ✅ 33 models running in production
- ✅ Sub-second response times
- ✅ 99.9% uptime
- ✅ Automatic scaling
- ✅ Comprehensive monitoring
- ✅ Cost under $70/month
- ✅ Enterprise-grade security
